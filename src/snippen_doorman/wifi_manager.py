"""Linux NetworkManager (nmcli) integration for WiFi scanning and connection management."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class WifiManager:
    """Manages WiFi scanning and connections using Linux NetworkManager (nmcli)."""

    def __init__(self, interface: str = "wlan0") -> None:
        """Initialize WiFi manager.

        Args:
            interface: Wireless interface name (default: 'wlan0').
        """
        self.interface = interface

    @property
    def is_available(self) -> bool:
        """Return True if nmcli command is available on host system."""
        return shutil.which("nmcli") is not None

    def list_networks(self, rescan: bool = True) -> list[dict[str, Any]]:
        """Scan for available wireless networks.

        Returns:
            List of network dictionaries with keys: ssid, signal, security, in_use.
        """
        if not self.is_available:
            logger.debug("nmcli not available. Returning empty network scan list.")
            return []

        cmd = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
        if rescan:
            cmd.append("--rescan")
            cmd.append("yes")

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15.0, check=False)
            if res.returncode != 0:
                logger.warning("nmcli wifi list failed (code %d): %s", res.returncode, res.stderr)
                return []

            networks: list[dict[str, Any]] = []
            seen_ssids: set[str] = set()

            for line in res.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    in_use = parts[0].strip() == "*"
                    ssid = parts[1].strip()
                    try:
                        signal = int(parts[2].strip())
                    except ValueError:
                        signal = 0
                    sec = ":".join(parts[3:]).strip()

                    # Filter out hidden/empty SSIDs and duplicates (keep strongest signal)
                    if not ssid or ssid.startswith("\\000") or ssid in seen_ssids:
                        continue

                    seen_ssids.add(ssid)
                    networks.append(
                        {
                            "ssid": ssid,
                            "signal": signal,
                            "security": sec or "Åpent",
                            "in_use": in_use,
                        }
                    )

            # Sort descending by signal strength
            networks.sort(key=lambda x: x["signal"], reverse=True)
            return networks
        except subprocess.TimeoutExpired:
            logger.warning("Timed out scanning for WiFi networks via nmcli.")
            return []
        except (subprocess.SubprocessError, OSError):
            logger.exception("Unexpected error scanning WiFi networks")
            return []

    def connect(self, ssid: str, password: str, timeout: float = 30.0) -> tuple[bool, str]:
        """Connect to a WiFi network.

        Args:
            ssid: Target network SSID.
            password: WPA/WPA2 password.
            timeout: Command timeout in seconds.

        Returns:
            Tuple of (success: bool, message: str).
        """
        if not self.is_available:
            return False, "nmcli er ikke tilgjengelig på dette systemet."

        if not ssid:
            return False, "SSID må oppgis."

        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            if res.returncode == 0:
                logger.info("Successfully connected to WiFi '%s': %s", ssid, res.stdout.strip())
                status = self.get_status()
                ip_info = f" (IP: {status.get('ip')})" if status.get("ip") else ""
                return True, f"Tilkoblet {ssid}{ip_info}"
            err_msg = res.stderr.strip() or res.stdout.strip() or "Tilkobling feilet."
            logger.warning("Failed to connect to WiFi '%s': %s", ssid, err_msg)
            return False, err_msg
        except subprocess.TimeoutExpired:
            return False, f"Tidsavbrudd ({timeout:.0f}s) ved tilkobling til {ssid}."
        except (subprocess.SubprocessError, OSError) as exc:
            return False, f"Uventet feil ved WiFi-oppkobling: {exc}"

    def get_status(self) -> dict[str, Any]:
        """Query current connection state of wireless interface."""
        if not self.is_available:
            return {
                "connected": False,
                "ssid": None,
                "ip": None,
                "signal": None,
            }

        try:
            # Check active WiFi connection
            res = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            connected = False
            ssid = None

            for line in res.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 4 and parts[1] == "wifi" and "connected" in parts[2]:
                    connected = True
                    ssid = parts[3]
                    break

            # Get IP address
            ip = None
            ip_res = subprocess.run(
                ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", self.interface],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            for line in ip_res.stdout.strip().splitlines():
                if line.startswith("IP4.ADDRESS[") and ":" in line:
                    ip = line.split(":", 1)[1].split("/")[0].strip()
                    break

            return {
                "connected": connected,
                "ssid": ssid,
                "ip": ip,
            }
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("Error retrieving WiFi status via nmcli: %s", exc)
            return {
                "connected": False,
                "ssid": None,
                "ip": None,
            }
