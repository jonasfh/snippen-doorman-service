"""Configuration manager for reading, validating, and updating Doorman service settings."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HEX_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")


@dataclass
class LockSetting:
    """Settings for an individual Yale Doorman lock."""

    name: str = "Hoveddør"
    address: str = ""
    key: str = ""
    slot: int = 1


@dataclass
class DoormanConfig:
    """Structured configuration for Snippen Doorman Service."""

    api_url: str = "https://vestreholmensameie.no/wp-json/snippen/v1/door"
    api_token: str = ""
    locks: list[LockSetting] = field(default_factory=list)
    lead_time_minutes: int = 60
    grace_period_minutes: int = 15
    sync_interval_seconds: float = 60.0
    guest_slot_min: int = 3
    guest_slot_max: int = 9
    gpio_button_pin: int = 26
    admin_password: str = "snippen2026"
    env_file_path: str = ".env"


def mask_secret(val: str, show_chars: int = 4) -> str:
    """Mask a secret string for safe display, preserving the start and end."""
    if not val:
        return ""
    if len(val) <= show_chars * 2:
        return "•" * len(val)
    return f"{val[:show_chars]}••••••••{val[-show_chars:]}"


class ConfigManager:
    """Loads, validates, and persists configuration from/to .env files."""

    def __init__(self, env_path: str | Path | None = None) -> None:
        """Initialize configuration manager.

        Args:
            env_path: Path to target .env or /etc/snippen-doorman/snippen-doorman.env.
        """
        if env_path is not None:
            self.env_path = Path(env_path)
        elif Path("/etc/snippen-doorman/snippen-doorman.env").is_file():
            self.env_path = Path("/etc/snippen-doorman/snippen-doorman.env")
        else:
            self.env_path = Path(".env")

    def load_config(self) -> DoormanConfig:
        """Load configuration from environment variables and env file."""
        env_map = self._read_env_file()

        def get_val(key: str, default: str) -> str:
            return os.getenv(key, env_map.get(key, default))

        api_url = get_val(
            "SNIPPEN_DOORMAN_API_URL", "https://vestreholmensameie.no/wp-json/snippen/v1/door"
        )
        api_token = get_val("SNIPPEN_DOORMAN_API_TOKEN", "")

        try:
            lead_time = int(get_val("SNIPPEN_LEAD_TIME_MINUTES", "60"))
        except ValueError:
            lead_time = 60

        try:
            grace_period = int(get_val("SNIPPEN_GRACE_PERIOD_MINUTES", "15"))
        except ValueError:
            grace_period = 15

        try:
            sync_interval = float(get_val("SNIPPEN_DOORMAN_SYNC_INTERVAL", "60.0"))
        except ValueError:
            sync_interval = 60.0

        try:
            slot_min = int(get_val("SNIPPEN_GUEST_SLOT_MIN", "3"))
        except ValueError:
            slot_min = 3

        try:
            slot_max = int(get_val("SNIPPEN_GUEST_SLOT_MAX", "9"))
        except ValueError:
            slot_max = 9

        try:
            gpio_pin = int(get_val("SNIPPEN_DOORMAN_GPIO_BUTTON", "26"))
        except ValueError:
            gpio_pin = 26

        admin_password = get_val("SNIPPEN_DOORMAN_ADMIN_PASSWORD", "snippen2026")

        # Parse locks
        locks: list[LockSetting] = []
        multi_locks_str = get_val("SNIPPEN_DOORMAN_LOCKS", "")
        single_addr = get_val("SNIPPEN_DOORMAN_BLE_ADDRESS", "")
        single_key = get_val("SNIPPEN_DOORMAN_BLE_KEY", "")
        try:
            single_slot = int(get_val("SNIPPEN_DOORMAN_BLE_SLOT", "1"))
        except ValueError:
            single_slot = 1

        if multi_locks_str.strip():
            # Format: Name1=MAC1:KEY1:SLOT1,Name2=MAC2:KEY2:SLOT2
            for part in multi_locks_str.split(","):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                name, rest = part.split("=", 1)
                pieces = rest.strip().split(":")
                addr = pieces[0].strip() if len(pieces) > 0 else ""
                k = pieces[1].strip() if len(pieces) > 1 else ""
                try:
                    s = int(pieces[2].strip()) if len(pieces) > 2 else 1
                except ValueError:
                    s = 1
                locks.append(LockSetting(name=name.strip(), address=addr, key=k, slot=s))

        if not locks and single_addr:
            locks.append(
                LockSetting(
                    name="Hoveddør",
                    address=single_addr,
                    key=single_key,
                    slot=single_slot,
                )
            )

        return DoormanConfig(
            api_url=api_url,
            api_token=api_token,
            locks=locks,
            lead_time_minutes=lead_time,
            grace_period_minutes=grace_period,
            sync_interval_seconds=sync_interval,
            guest_slot_min=slot_min,
            guest_slot_max=slot_max,
            gpio_button_pin=gpio_pin,
            admin_password=admin_password,
            env_file_path=str(self.env_path),
        )

    def to_safe_dict(self, cfg: DoormanConfig) -> dict[str, Any]:
        """Convert configuration to dictionary with masked secrets for UI display."""
        return {
            "api_url": cfg.api_url,
            "api_token_configured": bool(cfg.api_token),
            "api_token_masked": mask_secret(cfg.api_token),
            "lead_time_minutes": cfg.lead_time_minutes,
            "grace_period_minutes": cfg.grace_period_minutes,
            "sync_interval_seconds": cfg.sync_interval_seconds,
            "guest_slot_min": cfg.guest_slot_min,
            "guest_slot_max": cfg.guest_slot_max,
            "gpio_button_pin": cfg.gpio_button_pin,
            "env_file_path": cfg.env_file_path,
            "locks": [
                {
                    "name": lk.name,
                    "address": lk.address,
                    "key_configured": bool(lk.key),
                    "key_masked": mask_secret(lk.key),
                    "slot": lk.slot,
                }
                for lk in cfg.locks
            ],
        }

    def update_config(self, updates: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate and persist updated configuration.

        Args:
            updates: Dictionary with updated configuration fields.

        Returns:
            Tuple of (success: bool, errors: list[str]).
        """
        errors: list[str] = []
        current = self.load_config()
        new_env_entries: dict[str, str] = {}

        # API URL
        if "api_url" in updates:
            raw_url = str(updates["api_url"]).strip()
            if not raw_url.startswith(("http://", "https://")):
                errors.append("API-URL må starte med http:// eller https://")
            else:
                new_env_entries["SNIPPEN_DOORMAN_API_URL"] = raw_url

        # API Token
        if "api_token" in updates:
            token = str(updates["api_token"]).strip()
            # Only update if user didn't send a masked placeholder or empty value
            if token and "••••" not in token:
                new_env_entries["SNIPPEN_DOORMAN_API_TOKEN"] = token

        # Admin Password
        if "admin_password" in updates:
            pwd = str(updates["admin_password"]).strip()
            if pwd and "••••" not in pwd:
                if len(pwd) < 6:
                    errors.append("Admin-passord må være minst 6 tegn.")
                else:
                    new_env_entries["SNIPPEN_DOORMAN_ADMIN_PASSWORD"] = pwd

        # Timings
        if "lead_time_minutes" in updates:
            try:
                lt = int(updates["lead_time_minutes"])
                if lt < 0:
                    raise ValueError
                new_env_entries["SNIPPEN_LEAD_TIME_MINUTES"] = str(lt)
            except (ValueError, TypeError):
                errors.append("Lead time må være et positivt heltall.")

        if "grace_period_minutes" in updates:
            try:
                gp = int(updates["grace_period_minutes"])
                if gp < 0:
                    raise ValueError
                new_env_entries["SNIPPEN_GRACE_PERIOD_MINUTES"] = str(gp)
            except (ValueError, TypeError):
                errors.append("Grace period må være et positivt heltall.")

        if "sync_interval_seconds" in updates:
            try:
                si = float(updates["sync_interval_seconds"])
                if si < 1.0:
                    raise ValueError
                new_env_entries["SNIPPEN_DOORMAN_SYNC_INTERVAL"] = str(si)
            except (ValueError, TypeError):
                errors.append("Synkroniseringsintervall må være minst 1.0 sekund.")

        if "gpio_button_pin" in updates:
            try:
                pin = int(updates["gpio_button_pin"])
                new_env_entries["SNIPPEN_DOORMAN_GPIO_BUTTON"] = str(pin)
            except (ValueError, TypeError):
                errors.append("GPIO-pinne må være et heltall.")

        # Locks
        if "locks" in updates and isinstance(updates["locks"], list):
            valid_locks: list[LockSetting] = []
            for idx, item in enumerate(updates["locks"]):
                name = str(item.get("name", f"Dør {idx + 1}")).strip()
                addr = str(item.get("address", "")).strip().upper()
                raw_key = str(item.get("key", "")).strip()
                try:
                    slot = int(item.get("slot", 1))
                except (ValueError, TypeError):
                    slot = 1

                # If key was masked, look up existing key
                if "••••" in raw_key or not raw_key:
                    existing_match = next(
                        (lk for lk in current.locks if lk.name == name or lk.address == addr), None
                    )
                    if existing_match:
                        raw_key = existing_match.key

                if not MAC_PATTERN.match(addr):
                    errors.append(f"Ugyldig MAC-adresse for '{name}': {addr}")
                elif raw_key and not HEX_KEY_PATTERN.match(raw_key):
                    errors.append(
                        f"Offline-nøkkel for '{name}' må være 32 heksadesimale tegn (16 bytes)."
                    )
                else:
                    valid_locks.append(LockSetting(name=name, address=addr, key=raw_key, slot=slot))

            if not errors and valid_locks:
                if len(valid_locks) == 1:
                    new_env_entries["SNIPPEN_DOORMAN_BLE_ADDRESS"] = valid_locks[0].address
                    new_env_entries["SNIPPEN_DOORMAN_BLE_KEY"] = valid_locks[0].key
                    new_env_entries["SNIPPEN_DOORMAN_BLE_SLOT"] = str(valid_locks[0].slot)
                    # Clear multi-locks if only 1
                    new_env_entries["SNIPPEN_DOORMAN_LOCKS"] = ""
                else:
                    multi_str = ",".join(
                        f"{lk.name}={lk.address}:{lk.key}:{lk.slot}" for lk in valid_locks
                    )
                    new_env_entries["SNIPPEN_DOORMAN_LOCKS"] = multi_str
                    new_env_entries["SNIPPEN_DOORMAN_BLE_ADDRESS"] = valid_locks[0].address
                    new_env_entries["SNIPPEN_DOORMAN_BLE_KEY"] = valid_locks[0].key
                    new_env_entries["SNIPPEN_DOORMAN_BLE_SLOT"] = str(valid_locks[0].slot)

        if errors:
            return False, errors

        # Persist to env file
        self._write_env_file(new_env_entries)

        # Update running os.environ
        for k, v in new_env_entries.items():
            os.environ[k] = v

        return True, []

    def _read_env_file(self) -> dict[str, str]:
        """Read key-values from env file."""
        res: dict[str, str] = {}
        if not self.env_path.is_file():
            return res
        try:
            with self.env_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    res[k.strip()] = v.strip().strip("'\"")
        except OSError as exc:
            logger.warning("Could not read env file %s: %s", self.env_path, exc)
        return res

    def _write_env_file(self, updates: dict[str, str]) -> None:
        """Update env file in-place, preserving existing lines and comments."""
        lines: list[str] = []
        handled_keys: set[str] = set()

        if self.env_path.is_file():
            try:
                with self.env_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and "=" in stripped:
                            k, _ = stripped.split("=", 1)
                            k = k.strip()
                            if k in updates:
                                val = updates[k]
                                lines.append(f'{k}="{val}"\n')
                                handled_keys.add(k)
                                continue
                        lines.append(line)
            except OSError as exc:
                logger.warning("Error reading %s for update: %s", self.env_path, exc)

        # Append any new keys
        for k, val in updates.items():
            if k not in handled_keys:
                lines.append(f'{k}="{val}"\n')

        # Ensure directory exists
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        with self.env_path.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info("Persisted %d settings to %s", len(updates), self.env_path)
