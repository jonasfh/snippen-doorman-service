"""Main entry point for the Snippen Doorman Service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from snippen_doorman.ble.client import YaleLockClient
from snippen_doorman.ble.discovery import discover_yale_devices


def setup_logging(level_name: str) -> None:
    """Configure basic logging."""
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


async def run_discovery(timeout: float) -> None:
    """Run BLE discovery and output results."""
    print(f"Scanning for Yale BLE devices (duration: {timeout:.1f}s)...")
    devices = await discover_yale_devices(timeout=timeout)
    if not devices:
        print("No Yale BLE devices found within range.")
        return

    print(f"\nFound {len(devices)} Yale device(s):")
    print("-" * 65)
    print(f"{'Address':<20} {'Name':<22} {'RSSI':<8} {'Serial':<12}")
    print("-" * 65)
    for dev in devices:
        rssi_str = f"{dev.rssi} dBm" if dev.rssi is not None else "N/A"
        serial_str = dev.serial or "N/A"
        print(f"{dev.address:<20} {dev.name:<22} {rssi_str:<8} {serial_str:<12}")
    print("-" * 65)


async def run_lock_command(action: str, address: str, key: str, slot: int, timeout: float) -> None:
    """Connect to lock and run status/lock/unlock command."""
    client = YaleLockClient(address=address, key=key, slot=slot)
    print(f"Connecting to lock {address} (slot {slot})...")

    try:
        if action == "status":
            state = await client.get_status(timeout=timeout)
        elif action == "lock":
            state = await client.lock(timeout=timeout)
        elif action == "unlock":
            state = await client.unlock(timeout=timeout)
        else:
            raise ValueError(f"Unknown lock action: {action}")

        battery_str = f"{state.battery}%" if state.battery is not None else "Unknown"
        print("\n--- Lock Status ---")
        print(f"Address:    {state.address}")
        print(f"Lock state: {state.lock_status}")
        print(f"Door state: {state.door_status}")
        print(f"Battery:    {battery_str}")
        print(f"Connected:  {state.is_connected}")
    finally:
        await client.disconnect()


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Snippen Doorman Service - Access control for Yale Doorman locks"
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, etc.)")
    parser.add_argument("--database-path", default="data/doorman.db", help="Database path")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # discover subcommand
    disc_parser = subparsers.add_parser("discover", help="Scan for Yale BLE locks and modules")
    disc_parser.add_argument(
        "--timeout", type=float, default=10.0, help="Scan timeout in seconds (default: 10.0)"
    )

    # status subcommand
    status_parser = subparsers.add_parser("status", help="Get current status of a Yale lock")
    status_parser.add_argument("--address", required=True, help="Bluetooth MAC address of the lock")
    status_parser.add_argument(
        "--key", required=True, help="16-byte offline key (32 hex characters)"
    )
    status_parser.add_argument("--slot", type=int, default=1, help="Key slot index (default: 1)")
    status_parser.add_argument(
        "--timeout", type=float, default=15.0, help="Operation timeout in seconds (default: 15.0)"
    )

    # lock subcommand
    lock_parser = subparsers.add_parser("lock", help="Send lock command to Yale lock")
    lock_parser.add_argument("--address", required=True, help="Bluetooth MAC address of the lock")
    lock_parser.add_argument("--key", required=True, help="16-byte offline key (32 hex characters)")
    lock_parser.add_argument("--slot", type=int, default=1, help="Key slot index (default: 1)")
    lock_parser.add_argument(
        "--timeout", type=float, default=20.0, help="Operation timeout in seconds (default: 20.0)"
    )

    # unlock subcommand
    unlock_parser = subparsers.add_parser("unlock", help="Send unlock command to Yale lock")
    unlock_parser.add_argument("--address", required=True, help="Bluetooth MAC address of the lock")
    unlock_parser.add_argument(
        "--key", required=True, help="16-byte offline key (32 hex characters)"
    )
    unlock_parser.add_argument("--slot", type=int, default=1, help="Key slot index (default: 1)")
    unlock_parser.add_argument(
        "--timeout", type=float, default=20.0, help="Operation timeout in seconds (default: 20.0)"
    )

    return parser


def main_cli(argv: list[str] | None = None) -> None:
    """CLI entry point for the Snippen Doorman Service."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    if args.subcommand == "discover":
        try:
            asyncio.run(run_discovery(args.timeout))
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Error during discovery: %s", exc)
            sys.exit(1)
    elif args.subcommand in ("status", "lock", "unlock"):
        try:
            asyncio.run(
                run_lock_command(
                    action=args.subcommand,
                    address=args.address,
                    key=args.key,
                    slot=args.slot,
                    timeout=args.timeout,
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Error executing %s: %s", args.subcommand, exc)
            sys.exit(1)
    else:
        logger.info("Starting Snippen Doorman Service")


if __name__ == "__main__":
    main_cli()
