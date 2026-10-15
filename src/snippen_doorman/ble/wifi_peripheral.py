"""BLE peripheral advertisement and WiFi setup service controller for Raspberry Pi."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import Any

from snippen_doorman.wifi_manager import WifiManager

logger = logging.getLogger(__name__)

# Nordic UART / Snippen BLE UUID constants (matching snippen-sms-service)
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_CONFIG_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_STATUS_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_COMMAND_UUID = "6e400004-b5a3-f393-e0a9-e50e24dcca9e"
DEVICE_NAME = "Snippen-Doorman"


class BleWifiPeripheral:
    """Controls the BLE advertising state and WiFi setup window on Raspberry Pi.

    When activated (e.g., at boot or via GPIO button press), advertises
    `Snippen-Doorman` for a limited duration (default: 600s / 10m).
    """

    def __init__(
        self,
        device_name: str = DEVICE_NAME,
        duration_seconds: int = 600,
        wifi_manager: WifiManager | None = None,
    ) -> None:
        """Initialize BLE peripheral manager.

        Args:
            device_name: BLE advertisement local name.
            duration_seconds: How long setup mode remains active.
            wifi_manager: NetworkManager WiFi manager instance.
        """
        self.device_name = device_name
        self.duration_seconds = duration_seconds
        self.wifi_manager = wifi_manager or WifiManager()
        self._active_until: float = 0.0
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    @property
    def is_active(self) -> bool:
        """Return True if BLE setup advertising is currently active."""
        with self._lock:
            return time.monotonic() < self._active_until

    @property
    def remaining_seconds(self) -> int:
        """Return remaining seconds in active setup window."""
        with self._lock:
            rem = int(self._active_until - time.monotonic())
            return max(0, rem)

    def activate(self, duration: int | None = None) -> bool:
        """Activate BLE advertising for setup mode.

        Args:
            duration: Optional override duration in seconds (default: 600).

        Returns:
            True if advertising was enabled, False if bluetooth is unavailable.
        """
        dur = duration if duration is not None else self.duration_seconds
        with self._lock:
            self._active_until = time.monotonic() + dur
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(dur, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()

        logger.info("BLE WiFi setup mode activated for %d seconds (%s)", dur, self.device_name)
        return self._start_advertising()

    def deactivate(self) -> None:
        """Deactivate BLE setup advertising."""
        with self._lock:
            self._active_until = 0.0
            if self._timer:
                self._timer.cancel()
                self._timer = None

        logger.info("BLE WiFi setup mode deactivated.")
        self._stop_advertising()

    def _on_timeout(self) -> None:
        """Timer callback when setup duration expires."""
        logger.info("BLE WiFi setup mode timed out after inactivity.")
        self.deactivate()

    def get_status_payload(self) -> dict[str, Any]:
        """Return status payload for BLE status characteristic."""
        status = self.wifi_manager.get_status()
        return {
            "status": "ok",
            "device": self.device_name,
            "wifi_connected": status.get("connected", False),
            "wifi_ssid": status.get("ssid"),
            "ip": status.get("ip"),
            "ble_setup_active": self.is_active,
            "remaining_seconds": self.remaining_seconds,
        }

    def handle_command(self, cmd_data: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming command payload from BLE command characteristic.

        Args:
            cmd_data: Parsed dictionary from BLE command characteristic.

        Returns:
            Response dictionary to send back via notification.
        """
        cmd = cmd_data.get("cmd")
        if cmd == "SCAN_WIFI":
            networks = self.wifi_manager.list_networks()
            return {"cmd": "SCAN_WIFI", "status": "ok", "networks": networks}
        if cmd == "TEST_WIFI":
            ssid = str(cmd_data.get("wifi_ssid", "")).strip()
            pwd = str(cmd_data.get("wifi_password", "")).strip()
            ok, msg = self.wifi_manager.connect(ssid=ssid, password=pwd)
            status = self.wifi_manager.get_status()
            return {
                "cmd": "TEST_WIFI",
                "status": "ok" if ok else "error",
                "connected": ok,
                "message": msg,
                "ssid": status.get("ssid"),
                "ip": status.get("ip"),
            }
        if cmd == "APPLY_AND_EXIT":
            self.deactivate()
            return {"cmd": "APPLY_AND_EXIT", "status": "ok"}
        return {"cmd": cmd or "UNKNOWN", "status": "error", "message": f"Unknown command: {cmd}"}

    def _start_advertising(self) -> bool:
        """Send bluetoothctl commands to configure and enable advertising."""
        if not shutil.which("bluetoothctl"):
            logger.debug(
                "bluetoothctl not available. Running BLE advertising in mock/software mode."
            )
            return True

        cmd = (
            "power on\n"
            "menu advertise\n"
            "clear\n"
            f"name {self.device_name}\n"
            f"uuids {SERVICE_UUID}\n"
            "back\n"
            "advertise on\n"
            "quit\n"
        )
        try:
            res = subprocess.run(
                ["bluetoothctl"],
                input=cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            logger.debug("bluetoothctl advertise on output: %s", res.stdout.strip())
            return res.returncode == 0
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("Could not execute bluetoothctl to start advertising: %s", exc)
            return False

    def _stop_advertising(self) -> None:
        """Stop BLE advertising via bluetoothctl."""
        if not shutil.which("bluetoothctl"):
            return

        cmd = "advertise off\nquit\n"
        try:
            subprocess.run(
                ["bluetoothctl"],
                input=cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("Error stopping advertising via bluetoothctl: %s", exc)
