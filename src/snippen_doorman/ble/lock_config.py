"""Lock configuration and multi-lock parsing utilities."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HEX_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass
class LockConfig:
    """Configuration for a single Yale Doorman lock."""

    name: str
    address: str
    key: str
    slot: int = 1
    lock_id: int | None = None

    def __post_init__(self) -> None:
        self.address = self.address.strip()
        self.key = self.key.strip().lower()
        if not self.address:
            raise ValueError("Lock address cannot be empty.")
        if not HEX_KEY_PATTERN.match(self.key):
            raise ValueError(
                f"Invalid offline key for lock '{self.name}'. Expected 32 hex characters."
            )
        if self.slot < 1:
            raise ValueError(
                f"Invalid key slot ({self.slot}) for lock '{self.name}'. Must be >= 1."
            )
        if self.lock_id is not None:
            try:
                self.lock_id = int(self.lock_id)
            except (ValueError, TypeError):
                self.lock_id = None


def parse_lock_configs(
    locks_val: str | None = None,
    default_address: str | None = None,
    default_key: str | None = None,
    default_slot: int = 1,
    default_lock_id: int | None = None,
) -> list[LockConfig]:
    """Parse one or more lock configurations from JSON string or env variables.

    Supports:
    1. JSON list or dict in locks_val, e.g.:
       '[{"name": "ytterdor", "address": "AA:BB:CC:DD:EE:01", "key": "...", "slot": 1}, ...]'
    2. Comma-separated string:
       'ytterdor=AA:BB:CC:DD:EE:01:0123456789abcdef0123456789abcdef:1,fellesrom=...'
    3. Fallback to default_address, default_key, default_slot (single-lock).

    Returns:
        List of validated LockConfig objects.
    """
    if locks_val and locks_val.strip():
        raw = locks_val.strip()
        # Attempt JSON decoding
        if raw.startswith(("[", "{")):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    # Dict of name -> dict or name -> "addr:key:slot:lock_id"
                    configs: list[LockConfig] = []
                    for name, details in data.items():
                        if isinstance(details, dict):
                            lid = details.get("lock_id")
                            configs.append(
                                LockConfig(
                                    name=name,
                                    address=details.get("address", ""),
                                    key=details.get("key", ""),
                                    slot=int(details.get("slot", 1)),
                                    lock_id=int(lid) if lid is not None else None,
                                )
                            )
                        elif isinstance(details, str):
                            parts = details.split(":")
                            lid_val = int(parts[3]) if len(parts) > 3 and parts[3].strip() else None
                            configs.append(
                                LockConfig(
                                    name=name,
                                    address=parts[0],
                                    key=parts[1],
                                    slot=int(parts[2]) if len(parts) > 2 else 1,
                                    lock_id=lid_val,
                                )
                            )
                    return configs
                elif isinstance(data, list):
                    configs = []
                    for idx, item in enumerate(data):
                        if isinstance(item, dict):
                            name = item.get("name", f"lock_{idx + 1}")
                            lid = item.get("lock_id")
                            configs.append(
                                LockConfig(
                                    name=name,
                                    address=item.get("address", ""),
                                    key=item.get("key", ""),
                                    slot=int(item.get("slot", 1)),
                                    lock_id=int(lid) if lid is not None else None,
                                )
                            )
                    return configs
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Failed to parse locks as JSON: %s. Trying string format.", exc)

        # Attempt comma-separated or semicolon-separated format
        configs = []
        entries = [e.strip() for e in raw.split(",") if e.strip()]
        for idx, entry in enumerate(entries):
            name = f"lock_{idx + 1}"
            spec = entry
            if "=" in entry:
                name, spec = entry.split("=", 1)
                name = name.strip()
                spec = spec.strip()

            # Check if using alternative delimiter like '@' or ';'
            if "@" in spec:
                parts = spec.split("@")
                addr = parts[0].strip()
                key = parts[1].strip()
                slot = int(parts[2].strip()) if len(parts) > 2 else 1
                lid = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else None
                configs.append(LockConfig(name=name, address=addr, key=key, slot=slot, lock_id=lid))
            elif ";" in spec:
                parts = spec.split(";")
                addr = parts[0].strip()
                key = parts[1].strip()
                slot = int(parts[2].strip()) if len(parts) > 2 else 1
                lid = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else None
                configs.append(LockConfig(name=name, address=addr, key=key, slot=slot, lock_id=lid))
            else:
                tokens = spec.split(":")
                # A standard MAC address has 6 octets: XX:XX:XX:XX:XX:XX
                if len(tokens) >= 9:
                    addr = ":".join(tokens[:6]).strip()
                    key = tokens[6].strip()
                    slot = int(tokens[7].strip())
                    lid = int(tokens[8].strip()) if tokens[8].strip() else None
                    configs.append(
                        LockConfig(name=name, address=addr, key=key, slot=slot, lock_id=lid)
                    )
                elif len(tokens) >= 8:
                    addr = ":".join(tokens[:6]).strip()
                    key = tokens[6].strip()
                    slot = int(tokens[7].strip())
                    configs.append(LockConfig(name=name, address=addr, key=key, slot=slot))
                elif len(tokens) == 7:
                    addr = ":".join(tokens[:6]).strip()
                    key = tokens[6].strip()
                    configs.append(LockConfig(name=name, address=addr, key=key, slot=1))
                elif len(tokens) >= 4:
                    addr = tokens[0].strip()
                    key = tokens[1].strip()
                    slot = int(tokens[2].strip()) if tokens[2].strip() else 1
                    lid = int(tokens[3].strip()) if tokens[3].strip() else None
                    configs.append(
                        LockConfig(name=name, address=addr, key=key, slot=slot, lock_id=lid)
                    )
                elif len(tokens) >= 2:
                    addr = tokens[0].strip()
                    key = tokens[1].strip()
                    slot = int(tokens[2].strip()) if len(tokens) > 2 else 1
                    configs.append(LockConfig(name=name, address=addr, key=key, slot=slot))
        if configs:
            return configs

    # Fallback to single lock from default address and key
    if default_address and default_key:
        return [
            LockConfig(
                name="default",
                address=default_address,
                key=default_key,
                slot=default_slot,
                lock_id=default_lock_id,
            )
        ]

    return []
