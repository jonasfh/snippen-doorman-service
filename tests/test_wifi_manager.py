"""Unit tests for WifiManager."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from snippen_doorman.wifi_manager import WifiManager


def test_list_networks_parsing() -> None:
    wm = WifiManager(interface="wlan0")

    mock_stdout = (
        "*:Home-WiFi:90:WPA2\n"
        " :Guest-WiFi:65:WPA2 WPA3\n"
        " :Weak-WiFi:30:WEP\n"
        " :Home-WiFi:70:WPA2\n"  # duplicate with lower signal, should be filtered
    )

    with (
        patch("shutil.which", return_value="/usr/bin/nmcli"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=mock_stdout, stderr=""
        )
        networks = wm.list_networks(rescan=False)

        assert len(networks) == 3
        assert networks[0]["ssid"] == "Home-WiFi"
        assert networks[0]["signal"] == 90
        assert networks[0]["in_use"] is True
        assert networks[1]["ssid"] == "Guest-WiFi"


def test_connect_wifi_success() -> None:
    wm = WifiManager(interface="wlan0")

    with (
        patch("shutil.which", return_value="/usr/bin/nmcli"),
        patch("subprocess.run") as mock_run,
        patch.object(wm, "get_status", return_value={"connected": True, "ip": "192.168.68.56"}),
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Connection successfully activated", stderr=""
        )
        ok, msg = wm.connect("MySSID", "mypassword")
        assert ok is True
        assert "192.168.68.56" in msg


def test_connect_wifi_failure() -> None:
    wm = WifiManager(interface="wlan0")

    with (
        patch("shutil.which", return_value="/usr/bin/nmcli"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Error: Secrets were required, but not provided.",
        )
        ok, msg = wm.connect("MySSID", "wrongpassword")
        assert ok is False
        assert "Secrets were required" in msg
