"""Unit tests for BLE discovery module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from yalexs_ble.const import COMMAND_SERVICE_UUID, YALE_MFR_ID

from snippen_doorman.ble.discovery import (
    discover_yale_devices,
    is_yale_advertisement,
    parse_yale_serial,
)


def test_parse_yale_serial() -> None:
    """Test serial parsing from local name."""
    # Valid local name (7 chars: 'ab12345')
    assert parse_yale_serial("ab12345") == "abXXX12345"
    # Invalid length returns None
    assert parse_yale_serial("short") is None
    assert parse_yale_serial(None) is None


def test_is_yale_advertisement_service_uuid() -> None:
    """Test matching advertisement by service UUID."""
    device = MagicMock(spec=BLEDevice)
    device.name = "Unknown"
    adv = MagicMock(spec=AdvertisementData)
    adv.service_uuids = [COMMAND_SERVICE_UUID]
    adv.manufacturer_data = {}
    adv.local_name = "Unknown"

    assert is_yale_advertisement(device, adv) is True


def test_is_yale_advertisement_mfr_data() -> None:
    """Test matching advertisement by Yale manufacturer ID."""
    device = MagicMock(spec=BLEDevice)
    device.name = "Lock"
    adv = MagicMock(spec=AdvertisementData)
    adv.service_uuids = []
    adv.manufacturer_data = {YALE_MFR_ID: b"\x01\x02"}
    adv.local_name = None

    assert is_yale_advertisement(device, adv) is True


def test_is_yale_advertisement_name() -> None:
    """Test matching advertisement with 'Yale' in name."""
    device = MagicMock(spec=BLEDevice)
    device.name = "Yale Doorman"
    adv = MagicMock(spec=AdvertisementData)
    adv.service_uuids = []
    adv.manufacturer_data = {}
    adv.local_name = "Yale Doorman"

    assert is_yale_advertisement(device, adv) is True


def test_is_not_yale_advertisement() -> None:
    """Test non-matching generic Bluetooth device."""
    device = MagicMock(spec=BLEDevice)
    device.name = "Random Headset"
    adv = MagicMock(spec=AdvertisementData)
    adv.service_uuids = ["0000180f-0000-1000-8000-00805f9b34fb"]
    adv.manufacturer_data = {999: b"\x00"}
    adv.local_name = "Random Headset"

    assert is_yale_advertisement(device, adv) is False


def test_discover_yale_devices() -> None:
    """Test running discover_yale_devices with a mock scanner."""

    async def _run():
        mock_scanner = MagicMock()
        detected_callbacks = []

        def mock_register(cb):
            detected_callbacks.append(cb)

        mock_scanner.register_detection_callback = mock_register

        device = MagicMock(spec=BLEDevice)
        device.address = "AA:BB:CC:DD:EE:FF"
        device.name = "Yale Doorman"

        adv = MagicMock(spec=AdvertisementData)
        adv.local_name = "Yale Doorman"
        adv.service_uuids = [COMMAND_SERVICE_UUID]
        adv.manufacturer_data = {YALE_MFR_ID: b"\x01\x02"}
        adv.rssi = -65

        async def mock_start():
            for cb in detected_callbacks:
                cb(device, adv)

        mock_scanner.start = AsyncMock(side_effect=mock_start)
        mock_scanner.stop = AsyncMock()

        res = await discover_yale_devices(timeout=0.01, scanner=mock_scanner)

        assert len(res) == 1
        assert res[0].address == "AA:BB:CC:DD:EE:FF"
        assert res[0].name == "Yale Doorman"
        assert res[0].rssi == -65
        assert res[0].is_yale is True

    asyncio.run(_run())
