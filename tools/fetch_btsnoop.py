#!/usr/bin/env python3
"""Automated helper to capture and pull Bluetooth HCI snoop log from Android device via ADB."""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def run_adb(cmd: list[str]) -> str:
    """Run an adb command and return stdout."""
    res = subprocess.run(["adb", *cmd], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ADB command failed: adb {' '.join(cmd)}\n{res.stderr.strip()}")
    return res.stdout.strip()


def check_device() -> str:
    """Check if an adb device is connected."""
    output = run_adb(["devices"])
    lines = [line for line in output.splitlines()[1:] if line.strip() and not line.startswith("*")]
    devices = [line.split()[0] for line in lines if "device" in line]
    if not devices:
        raise RuntimeError(
            "No ADB device found. Ensure phone is connected with USB/Wi-Fi debugging enabled."
        )
    return devices[0]


def capture_bugreport(output_dir: Path) -> Path:
    """Trigger bugreportz on device and pull the resulting archive."""
    print("[*] Triggering bugreportz on connected Android device...")
    res = run_adb(["shell", "bugreportz"])
    if not res.startswith("OK:"):
        raise RuntimeError(f"bugreportz failed or returned unexpected output: {res}")

    remote_path = res[3:].strip()
    print(f"[*] Generated bugreport on device: {remote_path}")

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    local_zip = output_dir / f"bugreport_{ts}.zip"
    print(f"[*] Pulling {remote_path} to {local_zip}...")
    run_adb(["pull", remote_path, str(local_zip)])
    return local_zip


def extract_snoop_log(zip_path: Path, output_dir: Path) -> Path:
    """Extract btsnoop_hci.log from bugreport zip archive."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        candidates = [
            name
            for name in zf.namelist()
            if "snoop" in name.lower() or "snooz" in name.lower() or name.endswith(".pcap")
        ]
        if not candidates:
            raise FileNotFoundError(f"No snoop logs found inside {zip_path.name}")

        target_name = next(
            (c for c in candidates if c.endswith("btsnoop_hci.log")),
            next(
                (c for c in candidates if c.endswith("btsnooz_hci.log")),
                candidates[0],
            ),
        )

        extracted_log = output_dir / "btsnoop_hci.log"
        print(f"[*] Extracting '{target_name}' to {extracted_log}...")
        extracted_log.write_bytes(zf.read(target_name))
        return extracted_log


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull Bluetooth HCI snoop log from Android device and decrypt Yale BLE sessions"
    )
    parser.add_argument(
        "-o",
        "--outdir",
        type=Path,
        default=Path("data"),
        help="Directory to store pulled bugreport and extracted btsnoop log (default: data/)",
    )
    parser.add_argument(
        "--decrypt",
        action="store_true",
        default=True,
        help="Run decrypt_ble_snoop.py immediately on the extracted log (default: True)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose decryption output",
    )
    args = parser.parse_args()

    try:
        dev = check_device()
        print(f"[*] Connected ADB device: {dev}")

        args.outdir.mkdir(parents=True, exist_ok=True)
        zip_path = capture_bugreport(args.outdir)
        log_path = extract_snoop_log(zip_path, args.outdir)

        print(
            f"[+] Successfully extracted snoop log to {log_path} ({log_path.stat().st_size} bytes)"
        )

        if args.decrypt:
            print("\n" + "=" * 80)
            print("[*] Running decrypt_ble_snoop.py...")
            print("=" * 80)
            decrypt_cmd = [
                sys.executable,
                str(Path(__file__).parent / "decrypt_ble_snoop.py"),
                str(log_path),
            ]
            if args.verbose:
                decrypt_cmd.append("-v")
            subprocess.run(decrypt_cmd, check=False)

    except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
        print(f"[!] Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
