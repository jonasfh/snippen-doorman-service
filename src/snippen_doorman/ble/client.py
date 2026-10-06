"""BLE client wrapper for communicating with a Yale Doorman lock."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from yalexs_ble import PushLock
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

        return YaleLockState(
            address=self.address,
            lock_status=lock_status_str,
            door_status=door_status_str,
            battery=lock.battery,
            is_connected=lock.is_connected,
        )

    async def get_status(self, timeout: float = 15.0) -> YaleLockState:
        """Connect to the lock, query its current status, and return state."""
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        _LOGGER.info("Querying lock status for %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                await lock.update()
                # Give lock brief window to process status update
                await asyncio.sleep(0.5)
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
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        _LOGGER.info("Sending LOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                await lock.lock()
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to lock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc

        return self.state

    async def unlock(self, timeout: float = 20.0) -> YaleLockState:
        """Send unlock command to the door lock."""
        lock = self._get_or_create_push_lock()
        self._push_lock = lock
        _LOGGER.info("Sending UNLOCK command to %s...", self.address)
        try:
            async with asyncio.timeout(timeout):
                await lock.unlock()
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out after {timeout}s while attempting to unlock {self.address}."
            ) from exc
        except AuthError as exc:
            raise AuthError(
                f"Authentication failed for {self.address}. Check key and slot ({self.slot})."
            ) from exc

        return self.state
