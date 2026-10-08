"""Time-driven Just-In-Time (JIT) PIN code provisioner for Yale Doorman locks."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from snippen_doorman.allocator import NoSlotsAvailableError, SlotAllocator
from snippen_doorman.ble.pin import YalePinError
from snippen_doorman.db import Database, PinRecord, PinStatus

logger = logging.getLogger(__name__)

DEFAULT_LEAD_TIME_MINUTES = 60
DEFAULT_GRACE_PERIOD_MINUTES = 15


@dataclass
class ProvisionTickResult:
    """Summary of operations performed during a provisioning tick."""

    activated: list[str] = field(default_factory=list)
    deprovisioned: list[str] = field(default_factory=list)
    expired_scheduled: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class PinProvisioner:
    """Orchestrates timely programming and deletion of keypad PIN codes on the lock."""

    def __init__(
        self,
        db: Database,
        allocator: SlotAllocator,
        lock_client: Any | None = None,
        lock_client_factory: Callable[[], Any] | None = None,
        lead_time: timedelta = timedelta(minutes=DEFAULT_LEAD_TIME_MINUTES),
        grace_period: timedelta = timedelta(minutes=DEFAULT_GRACE_PERIOD_MINUTES),
    ) -> None:
        """Initialize provisioner with database, slot allocator, and lock communication handler.

        Args:
            db: Database storage instance.
            allocator: SlotAllocator instance.
            lock_client: Pre-configured lock client or mock client.
            lock_client_factory: Callable returning a lock client (synchronous or async).
            lead_time: Time before booking start when PIN should be programmed onto lock.
            grace_period: Time after booking end before PIN is removed from lock.
        """
        self.db = db
        self.allocator = allocator
        self.lock_client = lock_client
        self.lock_client_factory = lock_client_factory
        self.lead_time = lead_time
        self.grace_period = grace_period
        self._sync_allocator_from_db()

    def _sync_allocator_from_db(self) -> None:
        """Hydrate slot allocator state with already provisioned slots from the database."""
        provisioned = self.db.list_pins(status=PinStatus.PROVISIONED)
        for rec in provisioned:
            if rec.slot is not None:
                try:
                    self.allocator.reserve(rec.slot, rec.booking_id)
                except ValueError as exc:
                    logger.warning(
                        "Could not reserve slot %d for booking '%s': %s",
                        rec.slot,
                        rec.booking_id,
                        exc,
                    )

    async def _get_lock_client(self) -> Any:
        """Resolve the active lock client instance."""
        if self.lock_client is not None:
            return self.lock_client
        if self.lock_client_factory is not None:
            client = self.lock_client_factory()
            if inspect.isawaitable(client):
                return await client
            return client
        return None

    def schedule_pin(
        self,
        booking_id: str,
        pin: str,
        valid_from: datetime,
        valid_to: datetime,
    ) -> PinRecord:
        """Register a new scheduled PIN code reservation without immediate lock programming.

        Args:
            booking_id: Unique booking identifier.
            pin: 4 to 6 digit numeric code.
            valid_from: Start time of booking.
            valid_to: End time of booking.

        Returns:
            The created PinRecord in SCHEDULED status.
        """
        return self.db.create_pin(
            booking_id=booking_id,
            pin=pin,
            valid_from=valid_from,
            valid_to=valid_to,
            status=PinStatus.SCHEDULED,
        )

    async def revoke_pin(self, booking_id: str) -> PinRecord:
        """Immediately revoke a PIN reservation, clearing it from the lock if active.

        Args:
            booking_id: Booking identifier to revoke.

        Returns:
            The updated PinRecord in REVOKED status.

        Raises:
            KeyError: If no record exists for booking_id.
        """
        rec = self.db.get_pin(booking_id)
        if rec is None:
            raise KeyError(f"No PIN record found for booking '{booking_id}'.")

        if rec.status == PinStatus.PROVISIONED and rec.slot is not None:
            client = await self._get_lock_client()
            if client is not None:
                try:
                    await client.delete_pin(slot=rec.slot, pin=rec.pin)
                except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                    logger.error(
                        "Error deleting PIN on lock during revoke for booking '%s': %s",
                        booking_id,
                        exc,
                    )
            self.allocator.release(rec.slot)
            rec.slot = None

        rec.status = PinStatus.REVOKED
        return self.db.update_pin(rec)

    async def tick(self, now: datetime | None = None) -> ProvisionTickResult:
        """Execute one provisioning reconciliation cycle.

        1. Deprovision expired active PINs past (valid_to + grace_period).
        2. Mark scheduled PINs that expired before activation as EXPIRED.
        3. Provision scheduled PINs in active window (valid_from - lead_time <= now <= valid_to + grace).

        Args:
            now: Current timestamp (defaults to datetime.now(UTC)).

        Returns:
            ProvisionTickResult summarizing operations completed.
        """
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        result = ProvisionTickResult()

        # Step 1: Deprovision expired active PINs
        provisioned = self.db.list_pins(status=PinStatus.PROVISIONED)
        for rec in provisioned:
            if now > rec.valid_to + self.grace_period:
                client = await self._get_lock_client()
                if client is not None and rec.slot is not None:
                    try:
                        await client.delete_pin(slot=rec.slot, pin=rec.pin)
                    except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        msg = (
                            f"Failed to delete PIN from lock for booking '{rec.booking_id}': {exc}"
                        )
                        logger.error(msg)
                        result.errors.append(msg)
                        continue

                if rec.slot is not None:
                    self.allocator.release(rec.slot)
                    rec.slot = None
                rec.status = PinStatus.EXPIRED
                self.db.update_pin(rec)
                result.deprovisioned.append(rec.booking_id)

        # Step 2: Expire scheduled PINs that are completely past booking window
        scheduled = self.db.list_pins(status=PinStatus.SCHEDULED)
        for rec in scheduled:
            if now > rec.valid_to + self.grace_period:
                rec.status = PinStatus.EXPIRED
                self.db.update_pin(rec)
                result.expired_scheduled.append(rec.booking_id)

        # Step 3: Activate scheduled PINs entering the lead-time window
        scheduled = self.db.list_pins(status=PinStatus.SCHEDULED)
        scheduled.sort(key=lambda r: r.valid_from)

        for rec in scheduled:
            earliest_activation = rec.valid_from - self.lead_time
            latest_activation = rec.valid_to + self.grace_period

            if earliest_activation <= now <= latest_activation:
                try:
                    slot = self.allocator.allocate(rec.booking_id)
                except NoSlotsAvailableError as exc:
                    msg = f"No slots available for booking '{rec.booking_id}': {exc}"
                    logger.warning(msg)
                    result.errors.append(msg)
                    continue

                client = await self._get_lock_client()
                if client is not None:
                    try:
                        await client.add_pin(
                            pin=rec.pin,
                            slot=slot,
                            valid_from=rec.valid_from,
                            valid_to=rec.valid_to,
                        )
                    except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        self.allocator.release(slot)
                        msg = f"Failed to program PIN on lock for booking '{rec.booking_id}': {exc}"
                        logger.error(msg)
                        result.errors.append(msg)
                        continue

                rec.slot = slot
                rec.status = PinStatus.PROVISIONED
                self.db.update_pin(rec)
                result.activated.append(rec.booking_id)

        return result


async def run_provisioning_scheduler(
    provisioner: PinProvisioner,
    interval_seconds: float = 60.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run provisioning reconciliation in a recurring background loop.

    Args:
        provisioner: PinProvisioner instance.
        interval_seconds: Polling interval between checks (default: 60s).
        stop_event: Optional asyncio.Event to trigger graceful shutdown.
    """
    logger.info(
        "Starting PIN provisioning scheduler loop (interval: %.1f seconds)",
        interval_seconds,
    )

    while stop_event is None or not stop_event.is_set():
        try:
            res = await provisioner.tick()
            if res.activated or res.deprovisioned or res.errors:
                logger.info(
                    "Provisioning tick: activated=%d, deprovisioned=%d, errors=%d",
                    len(res.activated),
                    len(res.deprovisioned),
                    len(res.errors),
                )
        except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError):
            logger.exception("Unexpected error during provisioning tick")

        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                break
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(interval_seconds)
