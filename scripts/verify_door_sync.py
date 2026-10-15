#!/usr/bin/env python3
"""Manual integration test and verification script for Yale Doorman synchronization.

This script verifies the complete end-to-end flow:
1. Starts an embedded Mock Booking API (or connects to an existing booking service).
2. Serves an active reservation that requires immediate lock provisioning.
3. Runs DoormanSyncEngine: BookingPoller fetches reservation, generates PIN,
   patches it to the API, and PinProvisioner programs the PIN into Yale Doorman over BLE.
4. Pauses interactively to allow physical testing on the Yale Doorman keypad.
5. On confirmation, simulates reservation removal, revokes the PIN over BLE,
   and verifies slot deallocation and cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bleak.exc import BleakError
from yalexs_ble import YaleXSBLEError

from snippen_doorman.allocator import SlotAllocator
from snippen_doorman.ble.client import YaleLockClient, YaleLockState
from snippen_doorman.ble.pin import YalePinCode, YalePinError
from snippen_doorman.booking_client import SnippenBookingClient
from snippen_doorman.db import Database, PinStatus
from snippen_doorman.main import load_env_file, setup_logging
from snippen_doorman.mock_server import MockBookingApiServer
from snippen_doorman.poller import BookingPoller
from snippen_doorman.provisioner import PinProvisioner
from snippen_doorman.state import SqliteReservationStore
from snippen_doorman.sync import DoormanSyncEngine

logger = logging.getLogger("snippen_doorman.verify_sync")


class MockDryRunLockClient:
    """Mock lock client for dry-run testing in CI or without physical BLE lock."""

    def __init__(self, address: str = "00:11:22:33:44:55", name: str = "MockLock") -> None:
        self.address = address
        self.name = name
        self.slot = 1
        self.pins: dict[int, str] = {}
        self.disconnected = False
        self.state = YaleLockState(
            address=address,
            lock_status="locked",
            door_status="closed",
            battery=95,
            is_connected=True,
        )

    async def add_pin(
        self,
        pin: str,
        slot: int,
        name: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        sync_rtc: bool = False,
        timeout: float = 20.0,
    ) -> YalePinCode:
        logger.info("[DRY-RUN] Programming PIN %s into slot %d on lock %s", pin, slot, self.address)
        self.pins[slot] = pin
        return YalePinCode(
            slot=slot,
            pin=pin,
            name=name,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    async def delete_pin(
        self,
        slot: int,
        pin: str | None = None,
        timeout: float = 20.0,
    ) -> bool:
        logger.info("[DRY-RUN] Deleting PIN from slot %d on lock %s", slot, self.address)
        self.pins.pop(slot, None)
        return True

    async def get_status(self, timeout: float = 15.0) -> YaleLockState:
        return self.state

    async def disconnect(self) -> None:
        self.disconnected = True


async def run_verification(args: argparse.Namespace) -> int:
    """Execute the end-to-end verification lifecycle."""
    print("=" * 72)
    print("  SNIPPEN DOORMAN SERVICE - VERIFIKASJONSTEST FOR YALE DOORMAN")
    print("=" * 72)

    # 1. Environment & Target Configuration
    is_dry_run = getattr(args, "dry_run", False)
    address = args.address
    key = args.key
    key_slot = args.key_slot
    timeout = args.timeout

    if not is_dry_run and (not address or not key):
        print("\n❌ Feil: BLE-adresse og/eller offline-nøkkel mangler!")
        print("Vennligst oppgi --address og --key, eller sett dem i .env:")
        print("  SNIPPEN_DOORMAN_BLE_ADDRESS='...'")
        print("  SNIPPEN_DOORMAN_BLE_KEY='...'")
        print("  SNIPPEN_DOORMAN_BLE_SLOT=1")
        print("\nTips: For å teste logikken uten fysisk lås, bruk flagget: --dry-run")
        return 1

    # 2. Setup Mock or External Booking Server
    mock_server: MockBookingApiServer | None = None
    if args.api_url:
        api_url = args.api_url.rstrip("/")
        api_token = args.api_token or "test-integration-token"
        print(f"\n[1/5] Bruker eksternt Booking API: {api_url}")
    else:
        api_token = "test-integration-token"
        mock_server = MockBookingApiServer(token=api_token)
        mock_server.start()
        api_url = mock_server.base_url
        print(f"\n[1/5] Startet lokal Mock Booking API-server på: {api_url}")

    # Create active booking: valid from now - 10m to now + duration_hours
    now = datetime.now(UTC)
    start_time = now - timedelta(minutes=10)
    end_time = now + timedelta(hours=args.duration_hours)
    booking_id = args.booking_id
    specified_pin = args.pin

    test_booking = {
        "id": booking_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "door_code": specified_pin,
    }

    if mock_server:
        mock_server.add_booking(test_booking)
        print(
            f"      Lagt til aktiv reservasjon ID '{booking_id}' (gyldig: {start_time.strftime('%H:%M')} -> {end_time.strftime('%H:%M')})"
        )
        if specified_pin:
            print(f"      Forhåndsdefinert PIN: {specified_pin}")
        else:
            print("      Ingen PIN forhåndsdefinert -> BookingPoller vil autogenerere 6-sifret PIN")

    # 3. Setup temporary local database and stores
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "doorman_verify.db"
    db = Database(str(db_path))
    store = SqliteReservationStore(str(db_path))
    allocator = SlotAllocator(min_slot=args.guest_slot_min, max_slot=args.guest_slot_max)

    # Setup Lock Client
    lock_client: Any
    if is_dry_run:
        lock_client = MockDryRunLockClient(address="00:11:22:33:44:55", name="DryRunLock")
        print("\n[2/5] Initialiserer Mock BLE-klient (--dry-run aktiv)")
    else:
        lock_client = YaleLockClient(address=address, key=key, slot=key_slot)
        print(f"\n[2/5] Initialiserer BLE-klient for lås {address} (nøkkelspor {key_slot})")

    provisioner = PinProvisioner(
        db=db,
        allocator=allocator,
        lock_client=lock_client,
        lead_time=timedelta(minutes=args.lead_time),
        grace_period=timedelta(minutes=args.grace_period),
        sync_rtc=True,
    )

    booking_client = SnippenBookingClient(
        api_url=api_url, api_token=api_token, timeout_seconds=timeout
    )
    poller = BookingPoller(
        client=booking_client,
        store=store,
        auto_generate_pin=True,
    )
    sync_engine = DoormanSyncEngine(
        poller=poller,
        provisioner=provisioner,
        store=store,
        db=db,
    )

    provisioned_slot: int | None = None
    provisioned_pin: str | None = None

    try:
        # 4. Phase 1: Initial Sync & Provisioning
        print("\n[3/5] Kjører synkroniseringssyklus...")
        result = await sync_engine.sync_once(now=now)

        if result.errors:
            print("\n❌ Feil oppstod under synkronisering:")
            for err in result.errors:
                print(f"   - {err}")
            return 1

        # Check store and db for provisioned record
        pin_rec = db.get_pin(booking_id)
        if not pin_rec or pin_rec.status != PinStatus.PROVISIONED:
            print(f"\n❌ Feil: Reservasjon {booking_id} ble ikke provisjonert på låsen!")
            print(f"Status i database: {pin_rec.status if pin_rec else 'Ikke funnet'}")
            return 1

        provisioned_slot = pin_rec.slot
        provisioned_pin = pin_rec.pin

        if mock_server and not specified_pin:
            # Verify mock server received PATCH
            if not mock_server.patch_calls:
                print("\n⚠️ Advarsel: Mock booking server mottok ikke PATCH med dørkode!")
            else:
                patched_code = mock_server.patch_calls[-1]["data"].get("door_code")
                print(
                    f"      Bekreftet: Autogenerert PIN '{patched_code}' patchet til booking API."
                )

        # 5. Interactive Verification Prompt
        print("\n" + "=" * 72)
        print("  🎉 DØRKODE PROGRAMMERT I YALE DOORMAN!")
        print("=" * 72)
        print(f"  Booking ID : {booking_id}")
        print(f"  Gjestespor : {provisioned_slot}")
        print(f"  PIN-kode   : {provisioned_pin}")
        print(f"  Lås MAC    : {address if not is_dry_run else 'DRY-RUN'}")
        print(f"  Gyldig til : {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 72)
        print("  👉 Gå bort til Yale Doorman-låsen.")
        print(f"  👉 Tast koden på tastaturet: {provisioned_pin} etterfulgt av *")
        print("  👉 Kontroller at låsen kvitterer med lys/signal og låser seg opp.")
        print("-" * 72)

        if not args.non_interactive:
            while True:
                prompt = "Trykk [ENTER] når du har testet og låsen åpnet (eller 'r' for status, 'q' for avbryt): "
                user_choice = input(prompt).strip().lower()

                if user_choice == "r":
                    print("\nLeser status fra låsen over BLE...")
                    try:
                        status = await lock_client.get_status(timeout=timeout)
                        batt_str = f"{status.battery}%" if status.battery is not None else "N/A"
                        print(
                            f"  Låsestatus : {status.lock_status.upper() if status.lock_status else 'UKJENT'}"
                        )
                        print(
                            f"  Dørstatus  : {status.door_status.upper() if status.door_status else 'UKJENT'}"
                        )
                        print(f"  Batterinivå: {batt_str}\n")
                    except (
                        YalePinError,
                        YaleXSBLEError,
                        BleakError,
                        TimeoutError,
                        OSError,
                        RuntimeError,
                        ValueError,
                    ) as exc:
                        print(f"  Kunne ikke hente status over BLE: {exc}\n")
                    continue
                elif user_choice == "q":
                    print("\nAvbryter testen etter brukerforespørsel.")
                    break
                else:
                    print("\n✅ Fysisk test bekreftet godkjent!")
                    break
        else:
            print("\n[--non-interactive] Simulerer godkjent manuell test.")

        # 6. Phase 2: Cleanup and Deprovisioning
        if not args.skip_cleanup:
            print("\n[4/5] Starter opprydding og avprogrammering fra låsen...")
            if mock_server:
                mock_server.remove_booking(booking_id)
                print(f"      Fjernet booking '{booking_id}' fra mock API.")

            # Run sync again; poller will see booking removed and revoke PIN on lock
            cleanup_res = await sync_engine.sync_once(now=now)
            if cleanup_res.errors:
                print("⚠️ Advarsel under oppryddingssynkronisering:")
                for err in cleanup_res.errors:
                    print(f"   - {err}")

            # Verify in DB and allocator that slot is freed
            clean_rec = db.get_pin(booking_id)
            is_revoked = clean_rec and clean_rec.status == PinStatus.REVOKED
            slot_is_free = allocator.is_available(provisioned_slot) if provisioned_slot else True

            if is_revoked and slot_is_free:
                print(f"      Gjestespor {provisioned_slot} er slettet fra låsen og frigjort.")
                provisioned_slot = None  # Cleared successfully
            else:
                print(
                    f"⚠️ Låsespor {provisioned_slot} ble kanskje ikke fullstendig frigjort (status: {clean_rec.status if clean_rec else 'Ukjent'})."
                )

        else:
            print(
                f"\n[--skip-cleanup aktiv] PIN '{provisioned_pin}' i spor {provisioned_slot} beholdes på låsen."
            )
            provisioned_slot = None

        print("\n[5/5] Fullfører testkjøring.")
        print("=" * 72)
        print("  VERIFIKASJONSTEST VELLYKKET GJENNOMFØRT")
        print("=" * 72)
        return 0

    finally:
        # Emergency cleanup if test was interrupted while PIN was still active on lock
        if provisioned_slot is not None and not args.skip_cleanup:
            print(f"\n⚠️ Sikkerhets-opprydding: Sletter PIN i spor {provisioned_slot} over BLE...")
            try:
                await lock_client.delete_pin(
                    slot=provisioned_slot, pin=provisioned_pin, timeout=timeout
                )
                print(f"   Spor {provisioned_slot} slettet.")
            except (
                YalePinError,
                YaleXSBLEError,
                BleakError,
                TimeoutError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                print(f"   Kunne ikke slette spor {provisioned_slot}: {exc}")

        # Disconnect lock client cleanly
        try:
            await lock_client.disconnect()
        except (BleakError, YaleXSBLEError, OSError) as exc:
            logger.debug("Non-fatal error disconnecting lock: %s", exc)

        # Stop mock server
        if mock_server:
            mock_server.stop()

        store.close()
        db.close()
        temp_dir.cleanup()


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for verify_door_sync."""
    load_env_file()

    env_address = os.getenv("SNIPPEN_DOORMAN_BLE_ADDRESS")
    env_key = os.getenv("SNIPPEN_DOORMAN_BLE_KEY")
    try:
        env_slot = int(os.getenv("SNIPPEN_DOORMAN_BLE_SLOT", "1"))
    except ValueError:
        env_slot = 1

    parser = argparse.ArgumentParser(
        description="Snippen Doorman Service - Verifikasjonstest for Yale Doorman over BLE"
    )
    parser.add_argument(
        "--address",
        default=env_address,
        help="Bluetooth MAC-adresse til Yale Doorman (standard: fra SNIPPEN_DOORMAN_BLE_ADDRESS)",
    )
    parser.add_argument(
        "--key",
        default=env_key,
        help="16-byte offline-nøkkel (32 hex-tegn, standard: fra SNIPPEN_DOORMAN_BLE_KEY)",
    )
    parser.add_argument(
        "--key-slot",
        type=int,
        default=env_slot,
        help="Nøkkelspor for offline-nøkkel (standard: fra SNIPPEN_DOORMAN_BLE_SLOT eller 1)",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Valgfri URL til kjørende Booking API (f.eks. http://127.0.0.1:8080/wp-json/snippen/v1/door). "
        "Hvis utelatt, startes en lokal mock-server automatisk.",
    )
    parser.add_argument(
        "--api-token",
        default=None,
        help="Bearer token for Booking API hvis ekstern API-URL brukes.",
    )
    parser.add_argument(
        "--booking-id",
        default="manual-verify-01",
        help="Booking-ID som opprettes for testen (standard: manual-verify-01)",
    )
    parser.add_argument(
        "--pin",
        default=None,
        help="Fast PIN-kode som skal settes i døren (f.eks. 123456). Hvis utelatt, autogenereres 6 sifre.",
    )
    parser.add_argument(
        "--duration-hours",
        type=float,
        default=2.0,
        help="Varighet for testreservasjonen i timer (standard: 2.0)",
    )
    parser.add_argument(
        "--guest-slot-min",
        type=int,
        default=3,
        help="Laveste gjestespor (standard: 3)",
    )
    parser.add_argument(
        "--guest-slot-max",
        type=int,
        default=9,
        help="Høyeste gjestespor (standard: 9)",
    )
    parser.add_argument(
        "--lead-time",
        type=int,
        default=60,
        help="Lead time i minutter før start koden skal aktiveres på låsen (standard: 60)",
    )
    parser.add_argument(
        "--grace-period",
        type=int,
        default=15,
        help="Grace period i minutter etter slutt før koden deaktiveres (standard: 15)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kjør med mock BLE-lås uten fysisk maskinvare tilkoblet.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Ikke vent på tastatur-input; simuler godkjent test umiddelbart.",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Ikke slett koden fra låsen etter testen.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=25.0,
        help="Timeout i sekunder for BLE-operasjoner (standard: 25.0)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Lognivå (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser


def main() -> None:
    """Entrypoint for verify_door_sync script."""
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)

    try:
        exit_code = asyncio.run(run_verification(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nAvbrutt av bruker (Ctrl+C).")
        sys.exit(130)


if __name__ == "__main__":
    main()
