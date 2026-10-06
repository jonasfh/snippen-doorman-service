#!/usr/bin/env python3
"""Parse Home Assistant debug logs to extract Yale Doorman / August OfflineKeys.

This tool extracts:
- Offline Key (32 hex characters / 128-bit AES)
- Key Slot (integer, typically 1)
- Device Name, Serial Number, and MAC Address (if available in log)

Can output as formatted shell/env variables or directly update a .env file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ExtractedKey:
    """Represents an extracted Yale offline key."""

    key: str
    slot: int
    name: str | None = None
    serial: str | None = None
    address: str | None = None
    source_type: str = "loaded"  # 'loaded' or 'created'


def is_valid_hex_key(key: str) -> bool:
    """Check if the string is a valid 32-character hex key."""
    if len(key) != 32:
        return False
    try:
        int(key, 16)
        return True
    except ValueError:
        return False


def parse_log_content(content: str) -> list[ExtractedKey]:
    """Parse text/log content and extract all valid OfflineKeys entries."""
    extracted: list[ExtractedKey] = []
    seen_pairs: set[tuple[str, int]] = set()

    # Attempt to extract lock metadata like MAC, name, or serial
    mac_match = re.search(
        r"""['"](?:macAddress|bluetooth_mac|mac|address)['"]\s*:\s*['"]([0-9a-fA-F:]{17})['"]""",
        content,
    )
    name_match = re.search(
        r"""['"](?:LockName|lock_name|name)['"]\s*:\s*['"]([^'"]+)['"]""",
        content,
    )
    serial_match = re.search(
        r"""['"](?:serialNumber|serial_number|serial)['"]\s*:\s*['"]([^'"]+)['"]""",
        content,
    )

    common_mac = mac_match.group(1).upper() if mac_match else None
    common_name = name_match.group(1) if name_match else None
    common_serial = serial_match.group(1) if serial_match else None

    # Search for blocks like 'loaded': [ ... ] and 'created': [ ... ]
    list_pattern = re.compile(
        r"""['"](loaded|created)['"]\s*:\s*\[(.*?)\]""",
        re.DOTALL | re.IGNORECASE,
    )
    item_pattern_1 = re.compile(
        r"""['"]key['"]\s*:\s*['"]([0-9a-fA-F]{32})['"][^}]*?['"]slot['"]\s*:\s*(\d+)""",
        re.DOTALL | re.IGNORECASE,
    )
    item_pattern_2 = re.compile(
        r"""['"]slot['"]\s*:\s*(\d+)[^}]*?['"]key['"]\s*:\s*['"]([0-9a-fA-F]{32})['"]""",
        re.DOTALL | re.IGNORECASE,
    )

    for list_match in list_pattern.finditer(content):
        src_type = list_match.group(1).lower()
        list_body = list_match.group(2)
        for m in item_pattern_1.finditer(list_body):
            key_hex, slot_str = m.groups()
            pair = (key_hex.lower(), int(slot_str))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                extracted.append(
                    ExtractedKey(
                        key=pair[0],
                        slot=pair[1],
                        name=common_name,
                        serial=common_serial,
                        address=common_mac,
                        source_type=src_type,
                    )
                )
        for m in item_pattern_2.finditer(list_body):
            slot_str, key_hex = m.groups()
            pair = (key_hex.lower(), int(slot_str))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                extracted.append(
                    ExtractedKey(
                        key=pair[0],
                        slot=pair[1],
                        name=common_name,
                        serial=common_serial,
                        address=common_mac,
                        source_type=src_type,
                    )
                )

    # Fallback if content has OfflineKeys but without loaded/created lists
    if not extracted and "OfflineKeys" in content:
        loose_1 = re.compile(
            r"""['"]key['"]\s*:\s*['"]([0-9a-fA-F]{32})['"][^}]*?['"]slot['"]\s*:\s*(\d+)""",
            re.IGNORECASE,
        )
        loose_2 = re.compile(
            r"""['"]slot['"]\s*:\s*(\d+)[^}]*?['"]key['"]\s*:\s*['"]([0-9a-fA-F]{32})['"]""",
            re.IGNORECASE,
        )
        for m in loose_1.finditer(content):
            key_hex, slot_str = m.groups()
            pair = (key_hex.lower(), int(slot_str))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                extracted.append(
                    ExtractedKey(
                        key=pair[0],
                        slot=pair[1],
                        name=common_name,
                        serial=common_serial,
                        address=common_mac,
                        source_type="loaded",
                    )
                )
        for m in loose_2.finditer(content):
            slot_str, key_hex = m.groups()
            pair = (key_hex.lower(), int(slot_str))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                extracted.append(
                    ExtractedKey(
                        key=pair[0],
                        slot=pair[1],
                        name=common_name,
                        serial=common_serial,
                        address=common_mac,
                        source_type="loaded",
                    )
                )

    return extracted


def update_env_file(
    env_path: Path,
    key: str,
    slot: int,
    address: str | None = None,
) -> None:
    """Update or append variables to .env file."""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_vars: dict[str, str] = {
        "SNIPPEN_DOORMAN_BLE_KEY": f'"{key}"',
        "SNIPPEN_DOORMAN_BLE_SLOT": str(slot),
    }
    if address:
        updated_vars["SNIPPEN_DOORMAN_BLE_ADDRESS"] = f'"{address}"'

    new_lines: list[str] = []
    found_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()
        matched = False
        for var_name, var_val in updated_vars.items():
            if stripped.startswith((f"{var_name}=", f"export {var_name}=")):
                new_lines.append(f"{var_name}={var_val}")
                found_keys.add(var_name)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for var_name, var_val in updated_vars.items():
        if var_name not in found_keys:
            new_lines.append(f"{var_name}={var_val}")

    content = "\n".join(new_lines).strip() + "\n"
    env_path.write_text(content, encoding="utf-8")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Extract Yale OfflineKeys from Home Assistant debug logs."
    )
    parser.add_argument(
        "--log-file",
        "-f",
        type=Path,
        default=None,
        help="Path to Home Assistant log file (e.g., home-assistant_yalexs_...log)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read log content from standard input",
    )
    parser.add_argument(
        "--output-env",
        "-o",
        type=Path,
        default=None,
        help="Write or update the specified .env file with extracted credentials",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output extracted keys in JSON format",
    )
    args = parser.parse_args()

    content: str = ""
    if args.stdin or (not args.log_file and not sys.stdin.isatty()):
        content = sys.stdin.read()
    elif args.log_file:
        if not args.log_file.exists():
            print(f"Error: Log file not found at '{args.log_file}'", file=sys.stderr)
            return 1
        content = args.log_file.read_text(encoding="utf-8", errors="replace")
    else:
        parser.print_help()
        print("\nError: Please provide a log file with --log-file or pass content via stdin.")
        return 1

    keys = parse_log_content(content)

    if not keys:
        print("❌ No valid Yale OfflineKeys found in provided log content.", file=sys.stderr)
        print(
            "Tip: Ensure debug logging was enabled for yalexs in Home Assistant before downloading the log.",
            file=sys.stderr,
        )
        return 1

    # Prioritize 'loaded' keys over 'created' keys
    keys.sort(key=lambda k: 0 if k.source_type == "loaded" else 1)
    primary = keys[0]

    if args.json:
        print(json.dumps([asdict(k) for k in keys], indent=2))
        return 0

    print(f"✅ Found {len(keys)} Yale OfflineKey entry/entries:\n")
    for idx, k in enumerate(keys, start=1):
        status = "Primary (Loaded)" if k.source_type == "loaded" else "Secondary (Created)"
        print(f"[{idx}] {status}")
        if k.name:
            print(f"    Name:    {k.name}")
        if k.serial:
            print(f"    Serial:  {k.serial}")
        if k.address:
            print(f"    Address: {k.address}")
        print(f"    Key:     {k.key}")
        print(f"    Slot:    {k.slot}")
        print()

    print("Suggested environment variables for .env:")
    print("-" * 50)
    print(f'SNIPPEN_DOORMAN_BLE_KEY="{primary.key}"')
    print(f"SNIPPEN_DOORMAN_BLE_SLOT={primary.slot}")
    if primary.address:
        print(f'SNIPPEN_DOORMAN_BLE_ADDRESS="{primary.address}"')
    print("-" * 50)

    if args.output_env:
        update_env_file(
            args.output_env,
            key=primary.key,
            slot=primary.slot,
            address=primary.address,
        )
        print(f"\n📁 Successfully saved credentials to {args.output_env}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
