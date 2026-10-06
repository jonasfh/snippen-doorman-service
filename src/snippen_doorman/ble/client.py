"""BLE client wrapper for communicating with a Yale Doorman lock."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from bleak import BleakError, BleakScanner
from yalexs_ble import PushLock
from yalexs_ble.push import get_device
from yalexs_ble.session import AuthError, DisconnectedError, YaleXSBLEError

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
