"""Core synchronization engine linking BookingPoller, ReservationStore, and PinProvisioner."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from snippen_doorman.db import Database
from snippen_doorman.poller import BookingPoller, PollTickResult
from snippen_doorman.provisioner import PinProvisioner, ProvisionTickResult
from snippen_doorman.state.base import ReservationStore
from snippen_doorman.state.models import ReservationStatus

logger = logging.getLogger(__name__)


@dataclass
class SyncTickResult:
    """Summary of operations performed during a full service synchronization cycle."""

    poll: PollTickResult = field(default_factory=PollTickResult)
    provision: ProvisionTickResult = field(default_factory=ProvisionTickResult)
    scheduled: list[str] = field(default_factory=list)
    updated_schedules: list[str] = field(default_factory=list)
    revoked_schedules: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class DoormanSyncEngine:
    """Orchestrates end-to-end booking synchronization against Yale Doorman locks."""

    def __init__(
        self,
        poller: BookingPoller,
        provisioner: PinProvisioner,
        store: ReservationStore,
        db: Database,
        lock_id: str | int | None = "default",
        lock_ids: list[str | int] | None = None,
    ) -> None:
        """Initialize synchronization engine.

        Args:
            poller: BookingPoller polling the booking platform.
            provisioner: PinProvisioner controlling keypad slots and lock communication.
            store: ReservationStore holding local reservation state.
            db: Database holding PIN provisioning state.
            lock_id: Identifier for target lock (default: 'default').
            lock_ids: Optional list of lock IDs to poll for multi-door setups.
        """
        self.poller = poller
        self.provisioner = provisioner
        self.store = store
        self.db = db
        self.lock_id = str(lock_id) if lock_id is not None else "default"
        self.lock_ids = [str(lid) for lid in lock_ids if lid is not None] if lock_ids else None

    async def sync_once(self, now: datetime | None = None) -> SyncTickResult:
        """Execute a full synchronization cycle: poll remote, reconcile queues, and provision lock.

        1. Poll remote Snippen Booking API for new, modified, unchanged, or removed reservations.
           If multiple lock_ids are configured, polls each door endpoint (?lock_id=...).
        2. Reconcile store changes into the PIN provisioning database:
           - New reservations with PIN scheduled for JIT activation on their respective lock.
           - Changed reservations updated in-place (marked PENDING_UPDATE if already active on lock).
           - Removed/cancelled reservations immediately revoked and deprogrammed.
        3. Execute PinProvisioner tick:
           - Program pins in lead-time window over BLE to targeted locks.
           - Update modified pins on lock.
           - Deprovision expired pins and release keypad slots.
        4. Yale Doorman sleep principle:
           - Zero BLE communication if no reservations need activation, deprogramming, or updating.

        Args:
            now: Current timestamp (defaults to UTC now).

        Returns:
            SyncTickResult summarizing operations across both stages.
        """
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        result = SyncTickResult()

        target_locks: list[str | None] = (
            list(self.lock_ids)
            if self.lock_ids
            else [self.lock_id if self.lock_id != "default" else None]
        )

        all_poll_res = PollTickResult()

        # Step 1 & 2: Poll each door and reconcile changes
        for lid in target_locks:
            try:
                poll_res = await asyncio.to_thread(self.poller.poll_once, now, lid)
                all_poll_res.added.extend(poll_res.added)
                all_poll_res.updated.extend(poll_res.updated)
                all_poll_res.removed.extend(poll_res.removed)
                all_poll_res.unchanged.extend(poll_res.unchanged)
                all_poll_res.errors.extend(poll_res.errors)
                result.errors.extend(poll_res.errors)
            except Exception as exc:
                msg = f"Unexpected failure in booking polling for lock {lid}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
                poll_res = PollTickResult(errors=[msg])

            target_lock_id = str(lid) if lid is not None else self.lock_id

            # 2a. Added bookings
            for booking_id in poll_res.added:
                rec = self.store.get_reservation(booking_id)
                if rec and rec.pin and rec.valid_to + self.provisioner.grace_period >= now:
                    _, changed = self.provisioner.schedule_or_update(
                        booking_id=rec.booking_id,
                        pin=rec.pin,
                        valid_from=rec.valid_from,
                        valid_to=rec.valid_to,
                        lock_id=rec.lock_id or target_lock_id,
                    )
                    if changed:
                        result.scheduled.append(booking_id)

            # 2b. Updated bookings
            for booking_id in poll_res.updated:
                rec = self.store.get_reservation(booking_id)
                if rec and rec.pin:
                    _, changed = self.provisioner.schedule_or_update(
                        booking_id=rec.booking_id,
                        pin=rec.pin,
                        valid_from=rec.valid_from,
                        valid_to=rec.valid_to,
                        lock_id=rec.lock_id or target_lock_id,
                    )
                    if changed:
                        result.updated_schedules.append(booking_id)

            # 2c. Removed / cancelled bookings
            for booking_id in poll_res.removed:
                try:
                    await self.provisioner.revoke_pin(booking_id, lock_id=target_lock_id)
                    result.revoked_schedules.append(booking_id)
                except KeyError:
                    pass

        result.poll = all_poll_res

        # 2d. Reconcile any unhydrated active bookings (e.g., initial startup or crash recovery)
        for rec in self.store.list_reservations():
            if (
                rec.status
                in (
                    ReservationStatus.ACTIVE,
                    ReservationStatus.NEW,
                    ReservationStatus.UPDATED,
                )
                and rec.pin
                and rec.valid_to + self.provisioner.grace_period >= now
            ):
                rec_target_lock = rec.lock_id or self.lock_id
                pin_rec = self.db.get_pin(rec.booking_id, lock_id=rec_target_lock)
                if pin_rec is None:
                    self.provisioner.schedule_or_update(
                        booking_id=rec.booking_id,
                        pin=rec.pin,
                        valid_from=rec.valid_from,
                        valid_to=rec.valid_to,
                        lock_id=rec_target_lock,
                    )
                    result.scheduled.append(rec.booking_id)

        # Step 3: Execute JIT provisioning reconciliation on lock
        try:
            prov_res = await self.provisioner.tick(now=now)
            result.provision = prov_res
            result.errors.extend(prov_res.errors)
        except Exception as exc:
            msg = f"Unexpected failure in provisioning tick: {exc}"
            logger.exception(msg)
            result.errors.append(msg)
            result.provision = ProvisionTickResult(errors=[msg])

        return result

    async def run_loop(
        self,
        interval_seconds: float = 60.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Run periodic synchronization daemon until stop_event is signaled.

        Args:
            interval_seconds: Polling interval between sync cycles.
            stop_event: Optional asyncio.Event for graceful termination.
        """
        logger.info(
            "Starting DoormanSyncEngine loop (interval: %.1fs, lock_id: %s)",
            interval_seconds,
            self.lock_id,
        )

        while stop_event is None or not stop_event.is_set():
            try:
                res = await self.sync_once()
                if (
                    res.poll.added
                    or res.poll.updated
                    or res.poll.removed
                    or res.provision.activated
                    or res.provision.updated
                    or res.provision.deprovisioned
                    or res.errors
                ):
                    logger.info(
                        "Sync cycle: poll[added=%d, updated=%d, removed=%d] provision[activated=%d, updated=%d, deprovisioned=%d] errors=%d",
                        len(res.poll.added),
                        len(res.poll.updated),
                        len(res.poll.removed),
                        len(res.provision.activated),
                        len(res.provision.updated),
                        len(res.provision.deprovisioned),
                        len(res.errors),
                    )
            except Exception:
                logger.exception("Unexpected exception in sync loop")

            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                    break
                except TimeoutError:
                    continue
            else:
                await asyncio.sleep(interval_seconds)

        logger.info("DoormanSyncEngine loop terminated cleanly.")
