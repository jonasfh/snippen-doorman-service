"""Main entry point for the Snippen Doorman Service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from snippen_doorman.allocator import SlotAllocator
from snippen_doorman.ble.client import YaleLockClient
from snippen_doorman.ble.discovery import discover_yale_devices
from snippen_doorman.ble.pin import YalePinError
from snippen_doorman.db import Database, PinStatus
from snippen_doorman.provisioner import PinProvisioner, run_provisioning_scheduler


def load_env_file(path: str | Path = ".env") -> None:
    """Load key-value pairs from .env into os.environ if not already present."""
    env_path = Path(path)
    if not env_path.is_file():
        return
    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


def setup_logging(level_name: str) -> None:
    """Configure basic logging."""
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def parse_iso_datetime(val: str | None) -> datetime | None:
    """Parse an ISO format datetime string."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except ValueError as exc:
        raise ValueError(
            f"Invalid ISO datetime format: '{val}'. Expected format: YYYY-MM-DDTHH:MM:SS"
        ) from exc


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


async def run_pin_command(
    action: str,
    address: str,
    key: str,
    key_slot: int,
    pin: str | None = None,
    slot: int | None = None,
    name: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    max_slots: int = 10,
    timeout: float = 20.0,
) -> None:
    """Connect to lock and execute PIN management operations."""
    client = YaleLockClient(address=address, key=key, slot=key_slot)
    print(f"Connecting to lock {address} (key slot {key_slot})...")

    try:
        if action == "add":
            if not pin or slot is None:
                raise ValueError("Both --pin and --slot are required for pin add.")
            print(f"Programming PIN to slot {slot}...")
            result = await client.add_pin(
                pin=pin,
                slot=slot,
                name=name,
                valid_from=valid_from,
                valid_to=valid_to,
                timeout=timeout,
            )
            print(f"\nPIN successfully added to slot {result.slot}.")
            print(f"Slot:       {result.slot}")
            print(f"PIN:        {result.pin}")
            if result.name:
                print(f"Name:       {result.name}")
            if result.valid_from:
                print(f"Valid from: {result.valid_from.isoformat()}")
            if result.valid_to:
                print(f"Valid to:   {result.valid_to.isoformat()}")
        elif action == "delete":
            if slot is None:
                raise ValueError("--slot is required for pin delete.")
            print(f"Deleting PIN in slot {slot}...")
            await client.delete_pin(slot=slot, pin=pin, timeout=timeout)
            print(f"\nPIN in slot {slot} successfully deleted.")
        elif action == "list":
            print(f"Scanning slots 0-{max_slots - 1} for configured PIN codes...")
            pins = await client.list_pins(timeout=timeout, max_slots=max_slots)
            if not pins:
                print(
                    "\nNo active PIN codes found (or slot querying not supported by lock firmware)."
                )
            else:
                print(f"\nFound {len(pins)} active PIN code(s):")
                print("-" * 30)
                print(f"{'Slot':<8} {'PIN':<12}")
                print("-" * 30)
                for p in pins:
                    print(f"{p.slot:<8} {p.pin:<12}")
                print("-" * 30)
        else:
            raise ValueError(f"Unknown PIN action: {action}")
    finally:
        await client.disconnect()


async def run_schedule_command(
    action: str,
    db_path: str,
    booking_id: str | None = None,
    pin: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    status: str | None = None,
    lead_time_minutes: int = 60,
    grace_period_minutes: int = 15,
    interval_seconds: float = 60.0,
    address: str | None = None,
    key: str | None = None,
    key_slot: int = 1,
    timeout: float = 20.0,
) -> None:
    """Execute booking PIN schedule operations."""
    lock_client = None
    if address and key:
        lock_client = YaleLockClient(address=address, key=key, slot=key_slot)

    try:
        with Database(db_path) as db:
            allocator = SlotAllocator()
            provisioner = PinProvisioner(
                db=db,
                allocator=allocator,
                lock_client=lock_client,
                lead_time=timedelta(minutes=lead_time_minutes),
                grace_period=timedelta(minutes=grace_period_minutes),
            )

            if action == "add":
                if not booking_id or not pin or not valid_from or not valid_to:
                    raise ValueError(
                        "--booking-id, --pin, --from, and --to are all required for schedule add."
                    )
                rec = provisioner.schedule_pin(
                    booking_id=booking_id,
                    pin=pin,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
                print(f"\nPIN reservation scheduled for booking '{rec.booking_id}'.")
                print(f"ID:         {rec.id}")
                print(f"Status:     {rec.status.value}")
                print(f"PIN:        {rec.pin}")
                print(f"Valid from: {rec.valid_from.isoformat()}")
                print(f"Valid to:   {rec.valid_to.isoformat()}")

            elif action == "list":
                status_filter = PinStatus(status) if status else None
                records = db.list_pins(status=status_filter)
                if not records:
                    print("\nNo PIN reservations found.")
                    return
                print(f"\nFound {len(records)} PIN reservation(s):")
                print("-" * 80)
                print(
                    f"{'Booking ID':<20} {'Slot':<6} {'Status':<13} {'Valid From':<19} {'Valid To':<19}"
                )
                print("-" * 80)
                for r in records:
                    slot_str = str(r.slot) if r.slot is not None else "-"
                    vf_str = r.valid_from.strftime("%Y-%m-%d %H:%M")
                    vt_str = r.valid_to.strftime("%Y-%m-%d %H:%M")
                    print(
                        f"{r.booking_id:<20} {slot_str:<6} {r.status.value:<13} {vf_str:<19} {vt_str:<19}"
                    )
                print("-" * 80)

            elif action == "revoke":
                if not booking_id:
                    raise ValueError("--booking-id is required for schedule revoke.")
                rec = await provisioner.revoke_pin(booking_id)
                print(
                    f"\nBooking '{rec.booking_id}' successfully revoked (status: {rec.status.value})."
                )

            elif action == "sync":
                print("Running provisioning reconciliation cycle...")
                res = await provisioner.tick()
                print("\nReconciliation completed:")
                print(f"Activated:          {res.activated if res.activated else 'None'}")
                print(f"Deprovisioned:      {res.deprovisioned if res.deprovisioned else 'None'}")
                print(
                    f"Expired (scheduled):{res.expired_scheduled if res.expired_scheduled else 'None'}"
                )
                if res.errors:
                    print(f"Errors:             {res.errors}")

            elif action == "run":
                print(
                    f"Starting provisioning scheduler daemon (poll interval: {interval_seconds:.1f}s)..."
                )
                await run_provisioning_scheduler(provisioner, interval_seconds=interval_seconds)

            else:
                raise ValueError(f"Unknown schedule action: {action}")
    finally:
        if lock_client is not None:
            await lock_client.disconnect()


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    load_env_file()

    env_address = os.getenv("SNIPPEN_DOORMAN_BLE_ADDRESS")
    env_key = os.getenv("SNIPPEN_DOORMAN_BLE_KEY")
    try:
        env_slot = int(os.getenv("SNIPPEN_DOORMAN_BLE_SLOT", "1"))
    except ValueError:
        env_slot = 1

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

    # Helper function for adding common connection arguments
    def add_common_conn_args(
        p: argparse.ArgumentParser,
        slot_name: str = "slot",
        required: bool = True,
    ) -> None:
        is_req = required and env_address is None
        p.add_argument(
            "--address",
            default=env_address,
            required=is_req,
            help="Bluetooth MAC address of the lock (default: from SNIPPEN_DOORMAN_BLE_ADDRESS)",
        )
        is_key_req = required and env_key is None
        p.add_argument(
            "--key",
            default=env_key,
            required=is_key_req,
            help="16-byte offline key (32 hex characters, default: from SNIPPEN_DOORMAN_BLE_KEY)",
        )
        if slot_name == "slot":
            p.add_argument(
                "--slot",
                type=int,
                default=env_slot,
                help=f"Key slot index (default: {env_slot})",
            )
        else:
            p.add_argument(
                "--key-slot",
                type=int,
                default=env_slot,
                help=f"Offline key slot index (default: {env_slot})",
            )
        p.add_argument(
            "--timeout",
            type=float,
            default=20.0,
            help="Operation timeout in seconds (default: 20.0)",
        )

    # status subcommand
    status_parser = subparsers.add_parser("status", help="Get current status of a Yale lock")
    add_common_conn_args(status_parser)

    # lock subcommand
    lock_parser = subparsers.add_parser("lock", help="Send lock command to Yale lock")
    add_common_conn_args(lock_parser)

    # unlock subcommand
    unlock_parser = subparsers.add_parser("unlock", help="Send unlock command to Yale lock")
    add_common_conn_args(unlock_parser)

    # pin subcommand
    pin_parser = subparsers.add_parser("pin", help="Manage keypad PIN codes on the lock")
    pin_subparsers = pin_parser.add_subparsers(dest="pin_subcommand", help="PIN operations")

    # pin add subcommand
    pin_add_parser = pin_subparsers.add_parser(
        "add", help="Add or update a PIN code in a keypad slot"
    )
    pin_add_parser.add_argument("--pin", required=True, help="4-6 digit numeric PIN")
    pin_add_parser.add_argument(
        "--slot", type=int, required=True, help="Keypad PIN slot (0 or higher)"
    )
    pin_add_parser.add_argument(
        "--name", default=None, help="Optional friendly name for the PIN credential"
    )
    pin_add_parser.add_argument(
        "--from",
        dest="valid_from",
        default=None,
        help="Optional start validity (ISO format: YYYY-MM-DDTHH:MM:SS)",
    )
    pin_add_parser.add_argument(
        "--to",
        dest="valid_to",
        default=None,
        help="Optional end validity (ISO format: YYYY-MM-DDTHH:MM:SS)",
    )
    add_common_conn_args(pin_add_parser, slot_name="key_slot")

    # pin delete subcommand
    pin_del_parser = pin_subparsers.add_parser(
        "delete", help="Delete a PIN code from a keypad slot"
    )
    pin_del_parser.add_argument(
        "--slot", type=int, required=True, help="Keypad PIN slot to clear (0 or higher)"
    )
    pin_del_parser.add_argument(
        "--pin", default=None, help="Optional PIN to match and delete specifically"
    )
    add_common_conn_args(pin_del_parser, slot_name="key_slot")

    # pin list subcommand
    pin_list_parser = pin_subparsers.add_parser(
        "list", help="List active PIN codes stored on the lock"
    )
    pin_list_parser.add_argument(
        "--max-slots", type=int, default=10, help="Maximum number of slots to query (default: 10)"
    )
    add_common_conn_args(pin_list_parser, slot_name="key_slot")

    # schedule subcommand
    schedule_parser = subparsers.add_parser(
        "schedule", help="Manage temporary PIN reservations and JIT provisioning"
    )
    sched_subparsers = schedule_parser.add_subparsers(
        dest="schedule_subcommand", help="Schedule operations"
    )

    # schedule add
    sched_add_parser = sched_subparsers.add_parser("add", help="Schedule a future PIN reservation")
    sched_add_parser.add_argument("--booking-id", required=True, help="Unique booking ID")
    sched_add_parser.add_argument("--pin", required=True, help="4-6 digit numeric PIN")
    sched_add_parser.add_argument(
        "--from",
        dest="valid_from",
        required=True,
        help="Start validity (ISO format: YYYY-MM-DDTHH:MM:SS)",
    )
    sched_add_parser.add_argument(
        "--to",
        dest="valid_to",
        required=True,
        help="End validity (ISO format: YYYY-MM-DDTHH:MM:SS)",
    )

    # schedule list
    sched_list_parser = sched_subparsers.add_parser(
        "list", help="List PIN reservations from database"
    )
    sched_list_parser.add_argument(
        "--status",
        choices=["SCHEDULED", "PROVISIONED", "REVOKED", "EXPIRED"],
        default=None,
        help="Filter by status",
    )

    # schedule revoke
    sched_revoke_parser = sched_subparsers.add_parser(
        "revoke", help="Revoke a PIN reservation and remove from lock"
    )
    sched_revoke_parser.add_argument("--booking-id", required=True, help="Unique booking ID")
    add_common_conn_args(sched_revoke_parser, slot_name="key_slot", required=False)

    # schedule sync
    sched_sync_parser = sched_subparsers.add_parser(
        "sync", help="Run a single provisioning reconciliation cycle"
    )
    sched_sync_parser.add_argument(
        "--lead-time",
        type=int,
        default=60,
        help="Lead time in minutes before booking start (default: 60)",
    )
    sched_sync_parser.add_argument(
        "--grace-period",
        type=int,
        default=15,
        help="Grace period in minutes after booking end (default: 15)",
    )
    add_common_conn_args(sched_sync_parser, slot_name="key_slot", required=False)

    # schedule run
    sched_run_parser = sched_subparsers.add_parser(
        "run", help="Run the JIT provisioning scheduler daemon"
    )
    sched_run_parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Polling interval in seconds (default: 60.0)",
    )
    sched_run_parser.add_argument(
        "--lead-time",
        type=int,
        default=60,
        help="Lead time in minutes before booking start (default: 60)",
    )
    sched_run_parser.add_argument(
        "--grace-period",
        type=int,
        default=15,
        help="Grace period in minutes after booking end (default: 15)",
    )
    add_common_conn_args(sched_run_parser, slot_name="key_slot", required=False)

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
    elif args.subcommand == "pin":
        if not args.pin_subcommand:
            parser.parse_args(["pin", "--help"])
            return

        try:
            valid_from = parse_iso_datetime(getattr(args, "valid_from", None))
            valid_to = parse_iso_datetime(getattr(args, "valid_to", None))
            asyncio.run(
                run_pin_command(
                    action=args.pin_subcommand,
                    address=args.address,
                    key=args.key,
                    key_slot=args.key_slot,
                    pin=getattr(args, "pin", None),
                    slot=getattr(args, "slot", None),
                    name=getattr(args, "name", None),
                    valid_from=valid_from,
                    valid_to=valid_to,
                    max_slots=getattr(args, "max_slots", 10),
                    timeout=args.timeout,
                )
            )
        except (OSError, RuntimeError, ValueError, YalePinError) as exc:
            logger.error("Error executing pin %s: %s", args.pin_subcommand, exc)
            sys.exit(1)
    elif args.subcommand == "schedule":
        if not args.schedule_subcommand:
            parser.parse_args(["schedule", "--help"])
            return

        try:
            valid_from = parse_iso_datetime(getattr(args, "valid_from", None))
            valid_to = parse_iso_datetime(getattr(args, "valid_to", None))
            asyncio.run(
                run_schedule_command(
                    action=args.schedule_subcommand,
                    db_path=args.database_path,
                    booking_id=getattr(args, "booking_id", None),
                    pin=getattr(args, "pin", None),
                    valid_from=valid_from,
                    valid_to=valid_to,
                    status=getattr(args, "status", None),
                    lead_time_minutes=getattr(args, "lead_time", 60),
                    grace_period_minutes=getattr(args, "grace_period", 15),
                    interval_seconds=getattr(args, "interval", 60.0),
                    address=getattr(args, "address", None),
                    key=getattr(args, "key", None),
                    key_slot=getattr(args, "key_slot", 1),
                    timeout=getattr(args, "timeout", 20.0),
                )
            )
        except (OSError, RuntimeError, ValueError, KeyError, YalePinError) as exc:
            logger.error("Error executing schedule %s: %s", args.schedule_subcommand, exc)
            sys.exit(1)
    else:
        logger.info("Starting Snippen Doorman Service")


if __name__ == "__main__":
    main_cli()
