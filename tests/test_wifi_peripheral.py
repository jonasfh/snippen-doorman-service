"""Tests for BLE WiFi setup peripheral controller."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from snippen_doorman.ble.wifi_peripheral import (
    CHAR_COMMAND_UUID,
    CHAR_CONFIG_UUID,
    CHAR_STATUS_UUID,
    DEVICE_NAME,
    SERVICE_UUID,
    BleWifiPeripheral,
)
from snippen_doorman.wifi_manager import WifiManager


def test_uuid_and_device_name_constants() -> None:
    """Verify UUID and name constants match the ecosystem standard."""
    assert SERVICE_UUID == "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    assert CHAR_CONFIG_UUID == "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
    assert CHAR_STATUS_UUID == "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
    assert CHAR_COMMAND_UUID == "6e400004-b5a3-f393-e0a9-e50e24dcca9e"
    assert DEVICE_NAME == "Snippen-Doorman"


def test_peripheral_initial_state() -> None:
    """Test initial deactivated state."""
    peripheral = BleWifiPeripheral(duration_seconds=10)
    assert not peripheral.is_active
    assert peripheral.remaining_seconds == 0
    assert peripheral.device_name == "Snippen-Doorman"


def test_activate_and_deactivate() -> None:
    """Test activation and deactivation lifecycle."""
    peripheral = BleWifiPeripheral(duration_seconds=300)
    with patch.object(peripheral, "_start_advertising", return_value=True) as mock_start:
        ok = peripheral.activate(duration=60)
        assert ok
        mock_start.assert_called_once()
        assert peripheral.is_active
        assert 0 < peripheral.remaining_seconds <= 60

    with patch.object(peripheral, "_stop_advertising") as mock_stop:
        peripheral.deactivate()
        mock_stop.assert_called_once()
        assert not peripheral.is_active
        assert peripheral.remaining_seconds == 0


def test_timeout_deactivates() -> None:
    """Test timeout trigger deactivates peripheral."""
    peripheral = BleWifiPeripheral(duration_seconds=1)
    with patch.object(peripheral, "_start_advertising", return_value=True):
        peripheral.activate(duration=1)
        assert peripheral.is_active
        peripheral._on_timeout()
        assert not peripheral.is_active


def test_get_status_payload() -> None:
    """Test status payload generation."""
    mock_wifi = MagicMock(spec=WifiManager)
    mock_wifi.get_status.return_value = {
        "connected": True,
        "ssid": "SnippenNet",
        "ip": "192.168.1.50",
    }
    peripheral = BleWifiPeripheral(wifi_manager=mock_wifi)
    peripheral.activate(duration=120)

    payload = peripheral.get_status_payload()
    assert payload["status"] == "ok"
    assert payload["device"] == "Snippen-Doorman"
    assert payload["wifi_connected"] is True
    assert payload["wifi_ssid"] == "SnippenNet"
    assert payload["ip"] == "192.168.1.50"
    assert payload["ble_setup_active"] is True
    assert payload["remaining_seconds"] > 0
    peripheral.deactivate()


def test_handle_command_scan_wifi() -> None:
    """Test handling of SCAN_WIFI command."""
    mock_wifi = MagicMock(spec=WifiManager)
    mock_wifi.list_networks.return_value = [{"ssid": "Net1", "signal": 80, "security": "WPA2"}]
    peripheral = BleWifiPeripheral(wifi_manager=mock_wifi)

    res = peripheral.handle_command({"cmd": "SCAN_WIFI"})
    assert res["status"] == "ok"
    assert res["cmd"] == "SCAN_WIFI"
    assert len(res["networks"]) == 1
    assert res["networks"][0]["ssid"] == "Net1"


def test_handle_command_test_wifi() -> None:
    """Test handling of TEST_WIFI command."""
    mock_wifi = MagicMock(spec=WifiManager)
    mock_wifi.connect.return_value = (True, "Connection activated")
    mock_wifi.get_status.return_value = {"ssid": "Net1", "ip": "192.168.1.80"}
    peripheral = BleWifiPeripheral(wifi_manager=mock_wifi)

    res = peripheral.handle_command(
        {"cmd": "TEST_WIFI", "wifi_ssid": "Net1", "wifi_password": "secret"}
    )
    assert res["status"] == "ok"
    assert res["connected"] is True
    assert res["ssid"] == "Net1"
    assert res["ip"] == "192.168.1.80"


def test_handle_command_apply_and_exit() -> None:
    """Test handling of APPLY_AND_EXIT command."""
    peripheral = BleWifiPeripheral()
    peripheral.activate(duration=60)
    assert peripheral.is_active

    res = peripheral.handle_command({"cmd": "APPLY_AND_EXIT"})
    assert res["status"] == "ok"
    assert res["cmd"] == "APPLY_AND_EXIT"
    assert not peripheral.is_active


def test_handle_command_unknown() -> None:
    """Test handling of unknown command."""
    peripheral = BleWifiPeripheral()
    res = peripheral.handle_command({"cmd": "INVALID_CMD"})
    assert res["status"] == "error"
    assert "Unknown command" in res["message"]


def test_start_advertising_bluetoothctl_success() -> None:
    """Test starting advertising when bluetoothctl succeeds."""
    peripheral = BleWifiPeripheral()
    with (
        patch("shutil.which", return_value="/usr/bin/bluetoothctl"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="Advertising started")
        ok = peripheral._start_advertising()
        assert ok
        mock_run.assert_called_once()
        cmd_input = mock_run.call_args[1]["input"]
        assert "Snippen-Doorman" in cmd_input
        assert SERVICE_UUID in cmd_input


def test_start_advertising_no_bluetoothctl() -> None:
    """Test starting advertising fallback when bluetoothctl is absent."""
    peripheral = BleWifiPeripheral()
    with patch("shutil.which", return_value=None):
        ok = peripheral._start_advertising()
        assert ok


def test_stop_advertising_subprocess() -> None:
    """Test stopping advertising with bluetoothctl."""
    peripheral = BleWifiPeripheral()
    with (
        patch("shutil.which", return_value="/usr/bin/bluetoothctl"),
        patch("subprocess.run") as mock_run,
    ):
        peripheral._stop_advertising()
        mock_run.assert_called_once()
        assert "advertise off" in mock_run.call_args[1]["input"]
