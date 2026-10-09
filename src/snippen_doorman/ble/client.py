"""BLE client wrapper for communicating with a Yale Doorman lock."""

from __future__ import annotations

import asyncio
import logging
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from bleak import BleakError, BleakScanner
from yalexs_ble import PushLock, util
from yalexs_ble.push import get_device
from yalexs_ble.session import AuthError, DisconnectedError, ResponseError, Session, YaleXSBLEError


# Yale Access Modules use 0xCC for keycode/credential command responses.
# Monkeypatch yalexs_ble.session.Session._validate_response to allow 0xCC alongside 0xAA and 0xBB.
def _patch_session_validation() -> None:
    def _extended_validate_response(self: Session, response: bytes | bytearray) -> None:
        checksum = util._simple_checksum(response)
        if checksum != 0:
            raise ResponseError(
                f"Simple checksum mismatch (expected 0, got {checksum}) in frame {response.hex()}"
            )
        if response[0x00] not in (0xAA, 0xBB, 0xCC):
            raise ResponseError(f"Incorrect flag in response: {response[0x00]}")

    Session._validate_response = _extended_validate_response  # type: ignore[method-assign]


def _patch_session_checksum() -> None:
    def _proper_write_checksum(self: Session, command: bytearray) -> None:
        command[0x03] = 0
        checksum = util._simple_checksum(command)
        command[0x03] = checksum

    Session._write_checksum = _proper_write_checksum  # type: ignore[method-assign]


_patch_session_checksum()
_patch_session_validation()


from .pin import (
    CMD_KEYCODE_ACCESS,
    CMD_KEYCODE_CLEAR,
    CMD_KEYCODE_COMMIT,
    CMD_KEYCODE_SET,
    CMD_SET_RTC,
    CMD_UNITY_GET_KEYCODE,
    YalePinCode,
    YalePinError,
    build_clear_pin_packet,
    build_commit_pin_packet,
    build_query_pin_packet,
    build_schedule_packet,
    build_set_pin_packet,
    build_set_rtc_packet,
    check_pin_response_error,
    decode_packed_bcd_pin,
    encode_packed_bcd_pin,
)

_LOGGER = logging.getLogger(__name__)

HEX_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass
class YaleLockState:
    """Represents current state of the Yale lock."""

    address: str
    lock_status: str
    door_status: str
    battery: int | None
    is_connected: bool


class YaleLockClient:
    """High-level client for Yale Doorman BLE communication using yalexs-ble."""

    def __init__(
        self,
        address: str,
        key: str,
        slot: int = 1,
        local_name: str | None = None,
        idle_disconnect_delay: float = 5.1,
    ) -> None:
        """Initialize the client with connection parameters and credentials.

        Args:
            address: Bluetooth MAC address of the lock/module.
            key: 16-byte offline key as a 32-character hex string.
            slot: Key index / slot number (default 1).
            local_name: Optional local BLE name.
            idle_disconnect_delay: Delay before disconnecting idle BLE connection.
        """
        if not address or not address.strip():
            raise ValueError("BLE address must not be empty.")

        clean_key = key.strip()
        if not HEX_KEY_PATTERN.match(clean_key):
            raise ValueError("Offline key must be a 32-character hexadecimal string (16 bytes).")

        if slot < 1:
            raise ValueError("Slot / key index must be 1 or higher.")

        self.address = address.strip()
        self.key = clean_key.lower()
        self.slot = slot
        self.local_name = local_name
        self.idle_disconnect_delay = idle_disconnect_delay

        self._push_lock: PushLock | None = None
        self._cancel_cb: Callable[[], None] | None = None

    def _get_or_create_push_lock(self) -> PushLock:
        """Lazily initialize PushLock within an active asyncio event loop."""
        if self._push_lock is None:
            self._push_lock = PushLock(
                address=self.address,
                key=self.key,
                key_index=self.slot,
                local_name=self.local_name,
                idle_disconnect_delay=self.idle_disconnect_delay,
            )
        return self._push_lock

    @property
    def is_running(self) -> bool:
        """Return whether the underlying PushLock is active."""
        if self._push_lock is None:
            return False
        return bool(getattr(self._push_lock, "_running", False))

    @property
    def state(self) -> YaleLockState:
        """Get the current known state of the lock."""
        lock = self._push_lock
        if lock is None:
            return YaleLockState(
                address=self.address,
                lock_status="UNKNOWN",
                door_status="UNKNOWN",
                battery=None,
                is_connected=False,
            )

        lock_status_str = (
            lock.lock_status.name if hasattr(lock.lock_status, "name") else str(lock.lock_status)
        )
        door_status_str = (
            lock.door_status.name if hasattr(lock.door_status, "name") else str(lock.door_status)
        )

        battery_pct: int | None = None
        if lock.battery is not None:
            if hasattr(lock.battery, "percentage"):
                battery_pct = lock.battery.percentage
            elif isinstance(lock.battery, (int, float)):
                battery_pct = int(lock.battery)

        return YaleLockState(
            address=self.address,
            lock_status=lock_status_str,
            door_status=door_status_str,
            battery=battery_pct,
            is_connected=lock.is_connected,
        )

    async def _ensure_started(self, timeout: float = 15.0) -> PushLock:
        """Ensure PushLock is started, associated with a BLE device, and initialized."""
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        if not getattr(lock, "_running", False):
            # Ensure the BLE device is discovered and attached to the lock watcher
            if hasattr(lock, "_ble_device") and lock._ble_device is None:
                device = await get_device(self.address)
                if device is None:
                    device = await BleakScanner.find_device_by_address(
                        self.address, timeout=min(5.0, timeout)
                    )
                if device is not None:
                    lock.set_ble_device(device)

            if hasattr(lock, "start"):
                start_result = lock.start()
                if asyncio.iscoroutine(start_result):
                    self._cancel_cb = await start_result
                else:
                    self._cancel_cb = start_result

            if getattr(lock, "_first_update_future", None):
                await lock.wait_for_first_update(timeout=timeout)

        return lock

    async def disconnect(self) -> None:
        """Cleanly disconnect from the lock and cancel background watchers."""
        if self._cancel_cb is not None:
            self._cancel_cb()
            self._cancel_cb = None

        if self._push_lock is not None and hasattr(self._push_lock, "_execute_forced_disconnect"):
            try:
                await self._push_lock._execute_forced_disconnect("client disconnect")
            except (BleakError, YaleXSBLEError, OSError) as exc:
                _LOGGER.debug("Non-fatal error disconnecting lock %s: %s", self.address, exc)

    async def __aenter__(self) -> Self:
        """Context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit, ensures clean disconnect."""
        await self.disconnect()

    async def get_status(self, timeout: float = 15.0) -> YaleLockState:
        """Connect to the lock, query its current status, and return state."""
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        _LOGGER.info("Querying lock status for %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                if not getattr(lock, "_running", False):
                    await self._ensure_started(timeout=timeout)
                else:
                    update_result = lock.update()
                    if asyncio.iscoroutine(update_result):
                        await update_result
                    await asyncio.sleep(0.06)
                    update_task = getattr(lock, "_update_task", None)
                    if update_task and not update_task.done():
                        await update_task
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while waiting for status from {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (DisconnectedError, YaleXSBLEError) as exc:
            _LOGGER.error("BLE error while querying status for %s: %s", self.address, exc)
            raise

        return self.state

    async def lock(self, timeout: float = 20.0) -> YaleLockState:
        """Send lock command to the door lock."""
        _LOGGER.info("Sending LOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                lock = await self._ensure_started(timeout=timeout)
                await lock.lock()
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to lock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (DisconnectedError, YaleXSBLEError) as exc:
            _LOGGER.error("BLE error while locking %s: %s", self.address, exc)
            raise

        return self.state

    async def unlock(self, timeout: float = 20.0) -> YaleLockState:
        """Send unlock command to the door lock."""
        _LOGGER.info("Sending UNLOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                lock = await self._ensure_started(timeout=timeout)
                await lock.unlock()
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to unlock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (DisconnectedError, YaleXSBLEError) as exc:
            _LOGGER.error("BLE error while unlocking %s: %s", self.address, exc)
            raise

        return self.state

    async def _execute_raw_command(
        self,
        cmd: bytearray,
        command_name: str,
        expected_opcode: int,
        timeout: float = 15.0,
    ) -> bytes:
        """Send raw August packet over the authenticated session and return response."""
        async with asyncio.timeout(timeout):
            lock = await self._ensure_started(timeout=timeout)
            connected_lock = await lock._ensure_connected()
            session = getattr(connected_lock, "session", None)
            if session is None:
                raise DisconnectedError(f"{self.address}: Lock session is not established.")

            matcher = lambda data: (
                len(data) >= 2 and data[0] in (0xAA, 0xBB, 0xCC) and data[1] == expected_opcode
            )
            response = await session.execute(cmd, command_name, response_matcher=matcher)

            return response

    async def set_rtc(
        self,
        timestamp: datetime | int | None = None,
        timeout: float = 20.0,
    ) -> int:
        """Synchronize the internal Real-Time Clock (RTC) on the Yale lock.

        Args:
            timestamp: Optional datetime or Unix epoch timestamp to set. Defaults to now (UTC).
            timeout: Maximum timeout for the BLE operation in seconds.

        Returns:
            The Unix epoch timestamp (seconds) programmed onto the lock.

        Raises:
            YalePinError: If the lock rejects the RTC command or operation fails.
            TimeoutError: If the BLE operation times out.
            AuthError: If authentication fails.
        """
        _LOGGER.info("Synchronizing RTC clock on %s...", self.address)
        await self._ensure_started(timeout=timeout)
        pkt = build_set_rtc_packet(timestamp)
        ts = struct.unpack("<I", pkt[4:8])[0]
        resp = await self._execute_raw_command(pkt, "set_rtc", CMD_SET_RTC, timeout=timeout)
        check_pin_response_error(resp, CMD_SET_RTC)
        _LOGGER.info("Successfully synchronized RTC clock on %s to %d (UTC).", self.address, ts)
        return ts

    async def add_pin(
        self,
        pin: str,
        slot: int,
        name: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        sync_rtc: bool = False,
        timeout: float = 20.0,
    ) -> YalePinCode:
        """Create or update a PIN code in a specific slot on the Yale lock.

        Args:
            pin: 4 to 6 digit numeric PIN.
            slot: Key slot index (1 or higher).
            name: Optional friendly name for the credential.
            valid_from: Optional starting datetime for validity.
            valid_to: Optional ending datetime for validity.
            sync_rtc: Whether to synchronize the lock's RTC clock before programming the PIN.
            timeout: Maximum timeout for the entire operation in seconds.

        Returns:
            YalePinCode object on success.

        Raises:
            ValueError: If PIN, slot, or date parameters are invalid.
            YalePinError: If the lock rejects the PIN or operation fails.
            TimeoutError: If the BLE operation times out.
            AuthError: If authentication fails.
        """
        # Validate parameters early
        encode_packed_bcd_pin(pin)  # validates digits and length 4-6
        if slot < 0:
            raise ValueError("Slot must be 0 or higher.")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from.")

        _LOGGER.info("Adding PIN to %s (slot %d)...", self.address, slot)
        await self._ensure_started(timeout=timeout)
        step_timeout = max(10.0, timeout / 4.0)

        if sync_rtc:
            await self.set_rtc(timeout=step_timeout)

        # 0. CMD_KEYCODE_CLEAR (0x28) to ensure slot is clean (matches official Yale Home flow)
        clear_pkt = build_clear_pin_packet(slot, pin=pin)
        try:
            resp0 = await self._execute_raw_command(
                clear_pkt, f"add_pin_preclear_slot_{slot}", CMD_KEYCODE_CLEAR, timeout=step_timeout
            )
            check_pin_response_error(resp0, CMD_KEYCODE_CLEAR)
        except YalePinError as exc:
            _LOGGER.debug(
                "Pre-clearing slot %d on %s returned (ignored): %s", slot, self.address, exc
            )

        # 1. CMD_KEYCODE_SET (0x27)
        set_pkt = build_set_pin_packet(pin)
        resp1 = await self._execute_raw_command(
            set_pkt, "add_pin_set", CMD_KEYCODE_SET, timeout=step_timeout
        )
        check_pin_response_error(resp1, CMD_KEYCODE_SET)

        # 2. CMD_KEYCODE_ACCESS (0x2B)
        sched_pkt = build_schedule_packet(valid_from=valid_from, valid_to=valid_to)
        resp2 = await self._execute_raw_command(
            sched_pkt, "add_pin_schedule", CMD_KEYCODE_ACCESS, timeout=step_timeout
        )
        check_pin_response_error(resp2, CMD_KEYCODE_ACCESS)

        # 3. CMD_KEYCODE_COMMIT (0x2C)
        commit_pkt = build_commit_pin_packet(pin, slot)
        resp3 = await self._execute_raw_command(
            commit_pkt, "add_pin_commit", CMD_KEYCODE_COMMIT, timeout=step_timeout
        )
        check_pin_response_error(resp3, CMD_KEYCODE_COMMIT)

        _LOGGER.info("Successfully added PIN to %s in slot %d.", self.address, slot)
        return YalePinCode(
            slot=slot,
            pin=pin,
            name=name,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    async def delete_pin(
        self,
        slot: int,
        pin: str | None = None,
        timeout: float = 20.0,
    ) -> bool:
        """Delete/clear a PIN code from a specific slot on the Yale lock.

        Args:
            slot: Key slot index (0 or higher).
            pin: Optional PIN to clear specifically.
            timeout: Operation timeout in seconds.

        Returns:
            True if deletion was successful.

        Raises:
            ValueError: If slot is invalid.
            YalePinError: If the lock rejects the delete operation.
        """
        if slot < 0:
            raise ValueError("Slot must be 0 or higher.")

        _LOGGER.info("Deleting PIN in slot %d on %s...", slot, self.address)
        await self._ensure_started(timeout=timeout)
        clear_pkt = build_clear_pin_packet(slot, pin=pin)
        resp = await self._execute_raw_command(
            clear_pkt, "delete_pin", CMD_KEYCODE_CLEAR, timeout=timeout
        )
        check_pin_response_error(resp, CMD_KEYCODE_CLEAR)
        _LOGGER.info("Successfully deleted PIN in slot %d on %s.", slot, self.address)
        return True

    async def list_pins(
        self,
        timeout: float = 20.0,
        max_slots: int = 10,
    ) -> list[YalePinCode]:
        """Query and return active PIN codes stored on the lock across slots 0..max_slots-1.

        Args:
            timeout: Overall timeout for querying slots.
            max_slots: Number of slots to inspect (default: 10).

        Returns:
            List of YalePinCode objects found on the lock.
        """
        _LOGGER.info("Listing PINs on %s (scanning up to %d slots)...", self.address, max_slots)
        await self._ensure_started(timeout=timeout)
        pins: list[YalePinCode] = []
        per_slot_timeout = max(5.0, timeout / max(1, max_slots))

        for slot_idx in range(max_slots):
            query_pkt = build_query_pin_packet(slot_idx)
            try:
                resp = await self._execute_raw_command(
                    query_pkt,
                    f"query_pin_slot_{slot_idx}",
                    CMD_UNITY_GET_KEYCODE,
                    timeout=per_slot_timeout,
                )
                if len(resp) >= 16 and resp[15] == 0:
                    pin_str = decode_packed_bcd_pin(resp[6:13])
                    if pin_str:
                        pins.append(YalePinCode(slot=slot_idx, pin=pin_str))
            except (YalePinError, TimeoutError, BleakError) as exc:
                _LOGGER.debug("Could not query pin slot %d on %s: %s", slot_idx, self.address, exc)
                continue

        return pins
