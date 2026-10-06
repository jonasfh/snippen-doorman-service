"""BLE discovery and scanning logic for Yale Doorman locks."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bleak import BleakScanner
from yalexs_ble.const import APPLE_MFR_ID, COMMAND_SERVICE_UUID, YALE_MFR_ID
from yalexs_ble.util import local_name_is_unique, local_name_to_serial

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

_LOGGER = logging.getLogger(__name__)


@dataclass
class YaleDiscoveredDevice:
    """Represents a discovered BLE device with Yale identification data."""

    address: str
    name: str
    rssi: int | None = None
    serial: str | None = None
    is_yale: bool = False
    manufacturer_data: dict[int, bytes] = field(default_factory=dict)
    service_uuids: list[str] = field(default_factory=list)


def parse_yale_serial(local_name: str | None) -> str | None:
    """Derive serial number from a Yale BLE local name if valid."""
    if not local_name or not local_name_is_unique(local_name):
        return None
    try:
        return local_name_to_serial(local_name)
    except (ValueError, IndexError):
        return None


def is_yale_advertisement(device: BLEDevice, advertisement: AdvertisementData) -> bool:
    """Check whether a BLE advertisement originates from a Yale lock or access module."""
    # Check 1: Command Service UUID advertisement
    uuids = [u.lower() for u in (advertisement.service_uuids or [])]
    if COMMAND_SERVICE_UUID.lower() in uuids:
        return True

    # Check 2: Yale manufacturer ID (465 / 0x01D1)
    mfr_data = advertisement.manufacturer_data or {}
    if YALE_MFR_ID in mfr_data:
        return True

    # Check 3: Apple manufacturer ID (76 / 0x004C) with HomeKit data from Yale
    if APPLE_MFR_ID in mfr_data:
        raw = mfr_data[APPLE_MFR_ID]
        # Yale HAP advertisements typically have 0x06 or 0x11 prefix
        if raw and raw[0] in (0x06, 0x11):
            name = (advertisement.local_name or device.name or "").lower()
            if "yale" in name or parse_yale_serial(advertisement.local_name):
                return True

    # Check 4: Local name matching Yale naming convention
    name = advertisement.local_name or device.name
    if name and parse_yale_serial(name):
        return True

    return bool(name and "yale" in name.lower())


async def discover_yale_devices(
    timeout: float = 10.0,
    scanner: BleakScanner | None = None,
) -> list[YaleDiscoveredDevice]:
    """Scan for BLE devices and filter for Yale locks/modules.

    Args:
        timeout: Scan duration in seconds.
        scanner: Optional custom BleakScanner instance (useful for testing).

    Returns:
        List of YaleDiscoveredDevice matching Yale signature or named devices.
    """
    discovered: dict[str, YaleDiscoveredDevice] = {}

    def callback(device: BLEDevice, advertisement: AdvertisementData) -> None:
        yale_match = is_yale_advertisement(device, advertisement)
        if not yale_match:
            return

        name = advertisement.local_name or device.name or "Unknown"
        serial = parse_yale_serial(advertisement.local_name) or parse_yale_serial(device.name)
        mfr_dict = dict(advertisement.manufacturer_data) if advertisement.manufacturer_data else {}
        uuids = list(advertisement.service_uuids) if advertisement.service_uuids else []

        discovered[device.address] = YaleDiscoveredDevice(
            address=device.address,
            name=name,
            rssi=advertisement.rssi,
            serial=serial,
            is_yale=True,
            manufacturer_data=mfr_dict,
            service_uuids=uuids,
        )

    _LOGGER.info("Starting BLE discovery for %s seconds...", timeout)
    if scanner is None:
        scanner = BleakScanner(detection_callback=callback)
    else:
        scanner.register_detection_callback(callback)

    try:
        await scanner.start()
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()

    _LOGGER.info("Discovery complete. Found %d Yale device(s).", len(discovered))
    return list(discovered.values())
