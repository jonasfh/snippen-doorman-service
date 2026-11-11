"""BLE client wrapper for communicating with a Yale Doorman lock."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import struct
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self, TypeVar

from bleak import BleakError, BleakScanner
from yalexs_ble import PushLock
from yalexs_ble.push import get_device
from yalexs_ble.session import (
    AuthError,
    DisconnectedError,
    KeycodeError,
    OperationFailedError,
    YaleXSBLEError,
)

from .pin import (
    CMD_KEYCODE_ACCESS,
    CMD_KEYCODE_COMMIT,
    CMD_KEYCODE_SET,
    CMD_SET_RTC,
    YalePinCode,
    YalePinError,
    build_commit_pin_packet,
    build_schedule_packet,
    build_set_pin_packet,
    build_set_rtc_packet,
    check_pin_response_error,
    validate_doorman_pin,
)

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

HEX_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


def _is_device_missing_error(exc: BaseException) -> bool:
    """Return True if an exception indicates BlueZ purged the device from its cache."""
    err_str = str(exc).lower()
    return "not found" in err_str or "disappeared" in err_str or "does not exist" in err_str


def _translate_ble_command_error(exc: KeycodeError | OperationFailedError) -> YalePinError:
    """Translate yalexs-ble KeycodeError/OperationFailedError to YalePinError with numeric code."""
    code = int(exc.error) if isinstance(exc.error, int) else None
    return YalePinError(str(exc), code=code)


@dataclass
class YaleLockState:
    """Represents current state of the Yale lock."""

    address: str
    lock_status: str
    door_status: str
    battery: int | None
    is_connected: bool


class MockLockClient:
    """Mock lock client for simulation and testing in Docker/CI without physical BLE hardware."""

    def __init__(
        self,
        address: str = "00:11:22:33:44:55",
        key: str = "0123456789abcdef0123456789abcdef",
        slot: int = 1,
        local_name: str | None = None,
        idle_disconnect_delay: float = 5.1,
        lock_id: int | str | None = None,
    ) -> None:
        self.address = address
        self.key = key
        self.slot = slot
        self.local_name = local_name
        self.idle_disconnect_delay = idle_disconnect_delay
        self.lock_id = str(lock_id) if lock_id is not None else None
        self.pins: dict[int, str] = {}
        self.disconnected = False
        self._state = YaleLockState(
            address=address,
            lock_status="UNKNOWN",
            door_status="UNKNOWN",
            battery=None,
            is_connected=False,
        )

    def _ensure_mock_connected(self) -> None:
        if not self._state.is_connected and not self.disconnected:
            self._state = YaleLockState(
                address=self.address,
                lock_status="locked",
                door_status="closed",
                battery=95,
                is_connected=True,
            )

    @property
    def is_running(self) -> bool:
        return not self.disconnected

    @property
    def state(self) -> YaleLockState:
        return self._state

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
        self._ensure_mock_connected()
        validate_doorman_pin(pin)
        if slot < 1:
            raise ValueError("Slot must be 1 or higher.")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from.")

        _LOGGER.info(
            "[MOCK BLE] Programming PIN %s into slot %d on lock %s (valid: %s - %s)",
            pin,
            slot,
            self.address,
            valid_from,
            valid_to,
        )
        self.pins[slot] = pin
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
        self._ensure_mock_connected()
        if slot < 1:
            raise ValueError("Slot must be 1 or higher.")
        _LOGGER.info("[MOCK BLE] Deleting PIN from slot %d on lock %s", slot, self.address)
        self.pins.pop(slot, None)
        return True

    async def list_pins(
        self,
        timeout: float = 20.0,
        max_slots: int = 10,
    ) -> list[YalePinCode]:
        self._ensure_mock_connected()
        return [
            YalePinCode(slot=s, pin=p) for s, p in sorted(self.pins.items()) if 1 <= s < max_slots
        ]

    async def get_status(self, timeout: float = 15.0) -> YaleLockState:
        self._ensure_mock_connected()
        return self._state

    async def set_rtc(
        self,
        timestamp: datetime | int | None = None,
        timeout: float = 20.0,
    ) -> int:
        self._ensure_mock_connected()
        _LOGGER.info("[MOCK BLE] Synchronized RTC clock on %s", self.address)
        return int(datetime.now(UTC).timestamp())

    async def lock(self, timeout: float = 20.0) -> YaleLockState:
        self._ensure_mock_connected()
        _LOGGER.info("[MOCK BLE] Locked %s", self.address)
        self._state = YaleLockState(
            address=self.address,
            lock_status="locked",
            door_status=self._state.door_status,
            battery=self._state.battery or 95,
            is_connected=True,
        )
        return self._state

    async def unlock(self, timeout: float = 20.0) -> YaleLockState:
        self._ensure_mock_connected()
        _LOGGER.info("[MOCK BLE] Unlocked %s", self.address)
        self._state = YaleLockState(
            address=self.address,
            lock_status="unlocked",
            door_status=self._state.door_status,
            battery=self._state.battery or 95,
            is_connected=True,
        )
        return self._state

    async def disconnect(self) -> None:
        self.disconnected = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.disconnect()


class YaleLockClient:
    """High-level proxy client for Yale Doorman BLE communication using yalexs-ble."""

    def __init__(
        self,
        address: str,
        key: str,
        slot: int = 1,
        local_name: str | None = None,
        idle_disconnect_delay: float = 5.1,
        lock_id: int | str | None = None,
        mock: bool = False,
    ) -> None:
        """Initialize the client with connection parameters and credentials.

        Args:
            address: Bluetooth MAC address of the lock/module.
            key: 16-byte offline key as a 32-character hex string.
            slot: Key index / slot number (default 1).
            local_name: Optional local BLE name.
            idle_disconnect_delay: Delay before disconnecting idle BLE connection.
            lock_id: Optional WordPress Booking door lock identifier.
            mock: If True, simulate BLE lock operations in-memory without hardware.
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
        self.lock_id = str(lock_id) if lock_id is not None else None

        self._mock_client: MockLockClient | None = None
        if mock or os.getenv("SNIPPEN_DOORMAN_MOCK_BLE", "").lower() in ("1", "true", "yes"):
            self._mock_client = MockLockClient(
                address=self.address,
                key=self.key,
                slot=self.slot,
                local_name=self.local_name,
                idle_disconnect_delay=self.idle_disconnect_delay,
                lock_id=self.lock_id,
            )

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
        if self._mock_client is not None:
            return self._mock_client.is_running
        if self._push_lock is None:
            return False
        return bool(getattr(self._push_lock, "_running", False))

    @property
    def state(self) -> YaleLockState:
        """Get the current known state of the lock."""
        if self._mock_client is not None:
            return self._mock_client.state
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

    async def _ensure_started(self, timeout: float = 15.0, force_scan: bool = False) -> PushLock:
        """Ensure PushLock is started, associated with a BLE device, and initialized."""
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        if (
            force_scan
            or not getattr(lock, "_running", False)
            or getattr(lock, "_ble_device", None) is None
        ):
            device = None
            if not force_scan:
                device = await get_device(self.address)
            if device is None:
                device = await BleakScanner.find_device_by_address(
                    self.address, timeout=min(5.0, timeout)
                )
            if device is not None:
                lock.set_ble_device(device)
            else:
                if self._cancel_cb is not None:
                    self._cancel_cb()
                    self._cancel_cb = None
                if hasattr(lock, "_running"):
                    lock._running = False
                raise YaleXSBLEError(f"Device {self.address} not discovered in Bluetooth scan")

            if hasattr(lock, "start") and not getattr(lock, "_running", False):
                start_result = lock.start()
                if asyncio.iscoroutine(start_result):
                    self._cancel_cb = await start_result
                else:
                    self._cancel_cb = start_result

            if getattr(lock, "_first_update_future", None):
                try:
                    await lock.wait_for_first_update(timeout=timeout)
                except Exception:
                    await self.disconnect()
                    raise

        return lock

    async def _run_with_rediscovery(
        self,
        op_name: str,
        timeout: float,
        operation: Callable[[PushLock], Awaitable[_T]],
    ) -> _T:
        """Run a PushLock operation, re-scanning once if BlueZ purged the device cache."""
        lock = await self._ensure_started(timeout=timeout)
        try:
            return await operation(lock)
        except (AuthError, KeycodeError, OperationFailedError):
            raise
        except (YaleXSBLEError, BleakError, OSError) as exc:
            if not _is_device_missing_error(exc):
                raise
            _LOGGER.warning(
                "Lock %s disappeared from BlueZ device cache in %s. Forcing BLE re-discovery...",
                self.address,
                op_name,
            )
            await self.disconnect()
            lock = await self._ensure_started(timeout=timeout, force_scan=True)
            return await operation(lock)

    async def disconnect(self) -> None:
        """Cleanly disconnect from the lock and cancel background watchers."""
        if self._mock_client is not None:
            await self._mock_client.disconnect()
            return

        if self._cancel_cb is not None:
            self._cancel_cb()
            self._cancel_cb = None

        if self._push_lock is not None:
            if hasattr(self._push_lock, "_running"):
                self._push_lock._running = False
            if hasattr(self._push_lock, "_ble_device"):
                self._push_lock._ble_device = None
            if hasattr(self._push_lock, "_execute_forced_disconnect"):
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
        if self._mock_client is not None:
            return await self._mock_client.get_status(timeout=timeout)

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
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (YaleXSBLEError, BleakError, OSError) as exc:
            if _is_device_missing_error(exc):
                _LOGGER.warning(
                    "Lock %s disappeared from BlueZ device cache in get_status. Forcing BLE re-discovery...",
                    self.address,
                )
                await self.disconnect()
                await self._ensure_started(timeout=timeout, force_scan=True)
            else:
                _LOGGER.error("BLE error while querying status for %s: %s", self.address, exc)
                raise
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while waiting for status from {self.address}."
            ) from exc

        return self.state

    async def lock(self, timeout: float = 20.0) -> YaleLockState:
        """Send lock command to the door lock."""
        if self._mock_client is not None:
            return await self._mock_client.lock(timeout=timeout)

        _LOGGER.info("Sending LOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                await self._run_with_rediscovery("lock()", timeout, lambda lk: lk.lock())
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to lock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (DisconnectedError, OperationFailedError, YaleXSBLEError) as exc:
            _LOGGER.error("BLE error while locking %s: %s", self.address, exc)
            raise

        return self.state

    async def unlock(self, timeout: float = 20.0) -> YaleLockState:
        """Send unlock command to the door lock."""
        if self._mock_client is not None:
            return await self._mock_client.unlock(timeout=timeout)

        _LOGGER.info("Sending UNLOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                await self._run_with_rediscovery("unlock()", timeout, lambda lk: lk.unlock())
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to unlock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc
        except (DisconnectedError, OperationFailedError, YaleXSBLEError) as exc:
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
        """Send raw August packet over the authenticated session (fallback path only)."""

        async def _send(lock: PushLock) -> bytes:
            connected_lock = await lock._ensure_connected()
            session = getattr(connected_lock, "session", None)
            if session is None:
                raise DisconnectedError(f"{self.address}: Lock session is not established.")

            matcher = lambda data: (
                len(data) >= 2 and data[0] in (0xAA, 0xBB) and data[1] == expected_opcode
            )
            return await session.execute(cmd, command_name, response_matcher=matcher)

        async with asyncio.timeout(timeout):
            return await self._run_with_rediscovery(command_name, timeout, _send)

    async def set_rtc(
        self,
        timestamp: datetime | int | None = None,
        timeout: float = 20.0,
    ) -> int:
        """Synchronize the internal Real-Time Clock (RTC) on the Yale lock."""
        if self._mock_client is not None:
            return await self._mock_client.set_rtc(timestamp=timestamp, timeout=timeout)

        pkt = build_set_rtc_packet(timestamp)
        ts = struct.unpack("<I", pkt[4:8])[0]
        _LOGGER.info("Synchronizing RTC clock on %s...", self.address)

        async def _op(lock: PushLock) -> int:
            if hasattr(lock, "set_rtc"):
                try:
                    return await lock.set_rtc(ts)
                except OperationFailedError as exc:
                    raise _translate_ble_command_error(exc) from exc
            resp = await self._execute_raw_command(pkt, "set_rtc", CMD_SET_RTC, timeout=timeout)
            check_pin_response_error(resp, CMD_SET_RTC)
            return ts

        try:
            async with asyncio.timeout(timeout):
                programmed_ts = await self._run_with_rediscovery("set_rtc()", timeout, _op)
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc

        _LOGGER.info(
            "Successfully synchronized RTC clock on %s to %d (UTC).",
            self.address,
            programmed_ts,
        )
        return programmed_ts

    async def _add_temporary_pin_fallback(
        self,
        lock: PushLock,
        pin: str,
        slot: int,
        valid_from: datetime | None,
        valid_to: datetime | None,
        step_timeout: float,
    ) -> None:
        """Fallback temporary PIN flow when installed yalexs-ble lacks schedule args."""
        try:
            await lock.clear_keycode(slot)
        except KeycodeError as exc:
            _LOGGER.debug(
                "Pre-clearing slot %d on %s returned (ignored): %s", slot, self.address, exc
            )

        resp1 = await self._execute_raw_command(
            build_set_pin_packet(pin), "add_pin_set", CMD_KEYCODE_SET, timeout=step_timeout
        )
        check_pin_response_error(resp1, CMD_KEYCODE_SET)

        resp2 = await self._execute_raw_command(
            build_schedule_packet(valid_from=valid_from, valid_to=valid_to),
            "add_pin_schedule",
            CMD_KEYCODE_ACCESS,
            timeout=step_timeout,
        )
        check_pin_response_error(resp2, CMD_KEYCODE_ACCESS)

        resp3 = await self._execute_raw_command(
            build_commit_pin_packet(pin, slot),
            "add_pin_commit",
            CMD_KEYCODE_COMMIT,
            timeout=step_timeout,
        )
        check_pin_response_error(resp3, CMD_KEYCODE_COMMIT)

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
        """Create or update a PIN code in a specific slot on the Yale lock."""
        if self._mock_client is not None:
            return await self._mock_client.add_pin(
                pin=pin,
                slot=slot,
                name=name,
                valid_from=valid_from,
                valid_to=valid_to,
                sync_rtc=sync_rtc,
                timeout=timeout,
            )

        validate_doorman_pin(pin)
        if slot < 1:
            raise ValueError("Slot must be 1 or higher.")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from.")

        _LOGGER.info("Adding PIN to %s (slot %d)...", self.address, slot)
        step_timeout = max(10.0, timeout / 4.0)

        if sync_rtc:
            await self.set_rtc(timeout=step_timeout)

        async def _op(lock: PushLock) -> None:
            try:
                if valid_from is None and valid_to is None:
                    await lock.set_keycode(slot, pin)
                elif "start_time" in inspect.signature(lock.set_keycode).parameters:
                    await lock.set_keycode(slot, pin, start_time=valid_from, end_time=valid_to)
                else:
                    await self._add_temporary_pin_fallback(
                        lock, pin, slot, valid_from, valid_to, step_timeout
                    )
            except KeycodeError as exc:
                raise _translate_ble_command_error(exc) from exc

        try:
            async with asyncio.timeout(timeout):
                await self._run_with_rediscovery("add_pin()", timeout, _op)
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc

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
        """Delete/clear a PIN code from a specific slot on the Yale lock."""
        if self._mock_client is not None:
            return await self._mock_client.delete_pin(slot=slot, pin=pin, timeout=timeout)

        if slot < 1:
            raise ValueError("Slot must be 1 or higher.")

        _LOGGER.info("Deleting PIN in slot %d on %s...", slot, self.address)

        async def _op(lock: PushLock) -> None:
            try:
                await lock.clear_keycode(slot)
            except KeycodeError as exc:
                raise _translate_ble_command_error(exc) from exc

        try:
            async with asyncio.timeout(timeout):
                await self._run_with_rediscovery("delete_pin()", timeout, _op)
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc

        _LOGGER.info("Successfully deleted PIN in slot %d on %s.", slot, self.address)
        return True

    async def list_pins(
        self,
        timeout: float = 20.0,
        max_slots: int = 10,
    ) -> list[YalePinCode]:
        """Query and return active PIN codes stored on the lock across slots 1..max_slots-1."""
        if self._mock_client is not None:
            return await self._mock_client.list_pins(timeout=timeout, max_slots=max_slots)

        _LOGGER.info("Listing PINs on %s (scanning slots 1..%d)...", self.address, max_slots - 1)
        lock = await self._ensure_started(timeout=timeout)
        pins: list[YalePinCode] = []
        per_slot_timeout = max(5.0, timeout / max(1, max_slots - 1))

        for slot_idx in range(1, max_slots):
            try:
                async with asyncio.timeout(per_slot_timeout):
                    pin_str = await lock.get_keycode(slot_idx)
                if pin_str:
                    pins.append(YalePinCode(slot=slot_idx, pin=pin_str))
            except (KeycodeError, YalePinError, TimeoutError, BleakError, ValueError) as exc:
                _LOGGER.debug("Could not query pin slot %d on %s: %s", slot_idx, self.address, exc)
                continue

        return pins


def create_lock_client(
    address: str,
    key: str,
    slot: int = 1,
    local_name: str | None = None,
    idle_disconnect_delay: float = 5.1,
    lock_id: int | str | None = None,
    mock: bool | None = None,
) -> YaleLockClient | MockLockClient:
    """Create a lock client, choosing MockLockClient if mock mode is requested or if BlueZ D-Bus is unavailable."""
    if mock is None:
        mock = os.getenv("SNIPPEN_DOORMAN_MOCK_BLE", "").lower() in ("1", "true", "yes")
        if not mock and (
            sys.platform.startswith("linux")
            and not os.path.exists("/var/run/dbus/system_bus_socket")
        ):
            _LOGGER.info(
                "BlueZ D-Bus socket not found (/var/run/dbus/system_bus_socket). "
                "Initializing lock client %s in mock/simulation mode.",
                address,
            )
            mock = True

    if mock:
        return MockLockClient(
            address=address,
            key=key,
            slot=slot,
            local_name=local_name,
            idle_disconnect_delay=idle_disconnect_delay,
            lock_id=lock_id,
        )
    return YaleLockClient(
        address=address,
        key=key,
        slot=slot,
        local_name=local_name,
        idle_disconnect_delay=idle_disconnect_delay,
        lock_id=lock_id,
    )
