"""Node and service identity resolution for multi-node Snippen Doorman deployments (issue #76)."""

from __future__ import annotations

import logging
import os
import re
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from snippen_doorman import __version__

logger = logging.getLogger(__name__)

MAC_COLON_PATTERN = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$")


def get_local_hostname() -> str:
    """Return local machine hostname."""
    try:
        return socket.gethostname() or "localhost"
    except OSError:
        return "localhost"


def get_local_ip() -> str:
    """Determine the primary local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_mac_address() -> str:
    """Detect primary network interface hardware MAC address (lowercase colon-separated)."""
    # 1. Try reading Linux /sys/class/net physical interfaces
    try:
        net_dir = Path("/sys/class/net")
        if net_dir.is_dir():
            candidates: list[Path] = [iface for iface in net_dir.iterdir() if iface.name != "lo"]

            # Prioritize eth/en, then wlan/wl, then others
            def iface_prio(p: Path) -> int:
                name = p.name.lower()
                if name.startswith(("eth", "en")):
                    return 0
                if name.startswith(("wlan", "wl")):
                    return 1
                return 2

            candidates.sort(key=iface_prio)

            for cand in candidates:
                addr_file = cand / "address"
                if addr_file.is_file():
                    raw = addr_file.read_text(encoding="utf-8").strip()
                    if MAC_COLON_PATTERN.match(raw) and raw != "00:00:00:00:00:00":
                        return raw.lower()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed reading MAC from /sys/class/net: %s", exc)

    # 2. Fallback to uuid.getnode()
    try:
        node = uuid.getnode()
        mac_hex = f"{node:012x}"
        if len(mac_hex) == 12 and mac_hex != "000000000000":
            return ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2)).lower()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed resolving MAC via uuid.getnode(): %s", exc)

    return "00:00:00:00:00:00"


@dataclass
class NodeIdentity:
    """Resolved identity and network telemetry for this Doorman service node."""

    service_id: str
    service_name: str
    hostname: str
    ip_address: str
    mac_address: str
    version: str = __version__
    lock_ids: list[str] = field(default_factory=list)

    def to_service_dict(self) -> dict[str, Any]:
        """Convert to the 'service' dictionary required by issue #76 / snippen-booking #372."""
        return {
            "id": self.service_id,
            "name": self.service_name,
            "version": self.version,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "lock_ids": [str(lid) for lid in self.lock_ids if lid is not None],
        }


def resolve_node_identity(
    service_id: str | None = None,
    service_name: str | None = None,
    hostname: str | None = None,
    ip_address: str | None = None,
    mac_address: str | None = None,
    lock_ids: list[str | int] | None = None,
    version: str | None = None,
    env: dict[str, str] | None = None,
) -> NodeIdentity:
    """Resolve node identity with fallback to environment, MAC address, and hostname.

    Args:
        service_id: Explicit service ID override.
        service_name: Explicit service display name override.
        hostname: Explicit hostname override (detected if None).
        ip_address: Explicit local IP override (detected if None).
        mac_address: Explicit MAC override (detected if None).
        lock_ids: List of lock IDs handled by this node.
        version: Service version override (defaults to __version__).
        env: Environment dict to consult (defaults to os.environ).

    Returns:
        Fully resolved NodeIdentity instance.
    """
    if env is None:
        env = os.environ  # type: ignore[assignment]

    # Resolve hostname, IP, MAC
    resolved_hostname = hostname if hostname is not None else get_local_hostname()
    resolved_ip = ip_address if ip_address is not None else get_local_ip()
    resolved_mac = mac_address if mac_address is not None else get_mac_address()
    resolved_version = version if version is not None else __version__

    # Resolve service_id:
    # 1. Parameter override
    # 2. Environment variable SNIPPEN_DOORMAN_SERVICE_ID
    # 3. Fallback to hardware MAC (doorman-<mac>) or hostname
    resolved_id = ""
    if service_id and str(service_id).strip():
        resolved_id = str(service_id).strip()
    elif env and env.get("SNIPPEN_DOORMAN_SERVICE_ID", "").strip():
        resolved_id = env["SNIPPEN_DOORMAN_SERVICE_ID"].strip()
    else:
        clean_mac = (
            resolved_mac.replace(":", "").replace("-", "").strip().lower() if resolved_mac else ""
        )
        if clean_mac and clean_mac != "000000000000":
            resolved_id = f"doorman-{clean_mac}"
        elif resolved_hostname and resolved_hostname != "localhost":
            resolved_id = resolved_hostname
        else:
            resolved_id = "doorman-node"

    # Resolve service_name:
    # 1. Parameter override
    # 2. Environment variable SNIPPEN_DOORMAN_SERVICE_NAME
    # 3. Fallback to 'Doorman (<service_id>)'
    resolved_name = ""
    if service_name and str(service_name).strip():
        resolved_name = str(service_name).strip()
    elif env and env.get("SNIPPEN_DOORMAN_SERVICE_NAME", "").strip():
        resolved_name = env["SNIPPEN_DOORMAN_SERVICE_NAME"].strip()
    else:
        resolved_name = f"Doorman ({resolved_id})"

    clean_lock_ids: list[str] = []
    if lock_ids:
        for lid in lock_ids:
            if lid is not None:
                lid_str = str(lid).strip()
                if lid_str and lid_str not in clean_lock_ids:
                    clean_lock_ids.append(lid_str)

    return NodeIdentity(
        service_id=resolved_id,
        service_name=resolved_name,
        hostname=resolved_hostname,
        ip_address=resolved_ip,
        mac_address=resolved_mac,
        version=resolved_version,
        lock_ids=clean_lock_ids,
    )
