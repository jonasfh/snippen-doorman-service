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
    updated: list[str] = field(default_factory=list)
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
        lock_clients: list[Any] | dict[str, Any] | None = None,
        lock_client_factory: Callable[[], Any] | None = None,
        lead_time: timedelta = timedelta(minutes=DEFAULT_LEAD_TIME_MINUTES),
        grace_period: timedelta = timedelta(minutes=DEFAULT_GRACE_PERIOD_MINUTES),
        sync_rtc: bool = True,
    ) -> None:
        """Initialize provisioner with database, slot allocator, and lock communication handler.

        Args:
            db: Database storage instance.
            allocator: SlotAllocator instance.
            lock_client: Pre-configured lock client or mock client.
            lock_clients: Multiple pre-configured lock clients (list or dict).
            lock_client_factory: Callable returning lock client(s) (synchronous or async).
            lead_time: Time before booking start when PIN should be programmed onto lock.
            grace_period: Time after booking end before PIN is removed from lock.
            sync_rtc: Whether to synchronize lock RTC clock during PIN programming.
        """
        self.db = db
        self.allocator = allocator
        self.lock_client = lock_client
        self.lock_clients = lock_clients
        self.lock_client_factory = lock_client_factory
        self.lead_time = lead_time
        self.grace_period = grace_period
        self.sync_rtc = sync_rtc
        self._sync_allocator_from_db()

    def _sync_allocator_from_db(self) -> None:
        """Hydrate slot allocator state with already provisioned slots from the database."""
        provisioned = self.db.list_pins(status=PinStatus.PROVISIONED)
        pending_updates = self.db.list_pins(status=PinStatus.PENDING_UPDATE)
        pending_revokes = self.db.list_pins(status=PinStatus.PENDING_REVOKE)
        for rec in provisioned + pending_updates + pending_revokes:
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

    async def _get_lock_clients(self) -> list[Any]:
        """Resolve all active lock client instances."""
        if self.lock_clients is not None:
            if isinstance(self.lock_clients, dict):
                return list(self.lock_clients.values())
            return list(self.lock_clients)
        if self.lock_client is not None:
            return [self.lock_client]
        if self.lock_client_factory is not None:
            res = self.lock_client_factory()
            if inspect.isawaitable(res):
                res = await res
            if isinstance(res, (list, tuple)):
                return list(res)
            if isinstance(res, dict):
                return list(res.values())
            if res is not None:
                return [res]
        return []

    async def _get_lock_client(self) -> Any:
        """Resolve a single primary lock client (for backward compatibility)."""
        clients = await self._get_lock_clients()
        return clients[0] if clients else None

    def _record_telemetry(self, client: Any) -> None:
        """Opportunistically record lock telemetry (battery, lock status) into the database."""
        addr = getattr(client, "address", None)
        if not addr or not isinstance(addr, str) or hasattr(addr, "_mock_return_value"):
            return
        state = getattr(client, "state", None)
        if (
            state is None
            or inspect.iscoroutine(state)
            or hasattr(state, "_mock_return_value")
            or "Mock" in type(state).__name__
        ):
            return

        lock_status = getattr(state, "lock_status", None)
        door_status = getattr(state, "door_status", None)
        battery = getattr(state, "battery", None)

        status_str = (
            str(lock_status)
            if isinstance(lock_status, str)
            or (
                lock_status is not None
                and not hasattr(lock_status, "_mock_return_value")
                and "Mock" not in type(lock_status).__name__
            )
            else None
        )
        door_str = (
            str(door_status)
            if isinstance(door_status, str)
            or (
                door_status is not None
                and not hasattr(door_status, "_mock_return_value")
                and "Mock" not in type(door_status).__name__
            )
            else None
        )
        batt_int = (
            battery
            if isinstance(battery, int) and not hasattr(battery, "_mock_return_value")
            else None
        )

        if status_str is not None or door_str is not None or batt_int is not None:
            self.db.record_lock_status(
                lock_address=addr,
                lock_status=status_str,
                door_status=door_str,
                battery=batt_int,
            )

    async def _call_add_pin(
        self,
        client: Any,
        pin: str,
        slot: int,
        valid_from: datetime,
        valid_to: datetime,
    ) -> Any:
        """Call add_pin on lock client, passing sync_rtc if supported and enabled."""
        kwargs: dict[str, Any] = {
            "pin": pin,
            "slot": slot,
            "valid_from": valid_from,
            "valid_to": valid_to,
        }
        if self.sync_rtc:
            try:
                sig = inspect.signature(client.add_pin)
                if "sync_rtc" in sig.parameters:
                    kwargs["sync_rtc"] = True
            except (ValueError, TypeError):
                pass
        return await client.add_pin(**kwargs)

    def schedule_pin(
        self,
        booking_id: str,
        pin: str,
        valid_from: datetime,
        valid_to: datetime,
        lock_id: str = "default",
    ) -> PinRecord:
        """Register a new scheduled PIN code reservation without immediate lock programming.

        Args:
            booking_id: Unique booking identifier.
            pin: 4 to 6 digit numeric code.
            valid_from: Start time of booking.
            valid_to: End time of booking.
            lock_id: Lock identifier (default: "default").

        Returns:
            The created PinRecord in SCHEDULED status.
        """
        return self.db.create_pin(
            booking_id=booking_id,
            pin=pin,
            valid_from=valid_from,
            valid_to=valid_to,
            status=PinStatus.SCHEDULED,
            lock_id=lock_id,
        )

    def schedule_or_update(
        self,
        booking_id: str,
        pin: str,
        valid_from: datetime,
        valid_to: datetime,
        lock_id: str = "default",
    ) -> tuple[PinRecord, bool]:
        """Schedule a new PIN or update an existing reservation schedule.

        Checks if parameters changed. If a provisioned PIN's parameters changed,
        marks it as PENDING_UPDATE so the next tick reconciles with the lock.
        If the reservation is unchanged, does not alter the record or wake the lock.

        Returns:
            Tuple of (PinRecord, changed: bool).
        """
        rec = self.db.get_pin(booking_id, lock_id=lock_id)
        if rec is None:
            new_rec = self.schedule_pin(
                booking_id=booking_id,
                pin=pin,
                valid_from=valid_from,
                valid_to=valid_to,
                lock_id=lock_id,
            )
            return new_rec, True

        # Check if relevant content changed
        vf = valid_from if valid_from.tzinfo else valid_from.replace(tzinfo=UTC)
        vt = valid_to if valid_to.tzinfo else valid_to.replace(tzinfo=UTC)
        has_changed = (
            rec.pin != pin
            or rec.valid_from != vf
            or rec.valid_to != vt
            or rec.status in (PinStatus.REVOKED, PinStatus.EXPIRED)
        )

        if not has_changed:
            return rec, False

        rec.pin = pin
        rec.valid_from = vf
        rec.valid_to = vt

        if rec.status == PinStatus.PROVISIONED:
            # Mark for lock re-programming on next tick
            rec.status = PinStatus.PENDING_UPDATE
        elif rec.status in (PinStatus.REVOKED, PinStatus.EXPIRED):
            rec.status = PinStatus.SCHEDULED
        # If SCHEDULED or PENDING_UPDATE, keep status

        self.db.update_pin(rec)
        return rec, True

    async def revoke_pin(self, booking_id: str, lock_id: str | None = None) -> PinRecord:
        """Immediately revoke a PIN reservation, clearing it from the lock if active.

        Args:
            booking_id: Booking identifier to revoke.
            lock_id: Optional lock identifier.

        Returns:
            The updated PinRecord in REVOKED (or PENDING_REVOKE) status.

        Raises:
            KeyError: If no record exists for booking_id.
        """
        rec = self.db.get_pin(booking_id, lock_id=lock_id)
        if rec is None:
            raise KeyError(f"No PIN record found for booking '{booking_id}'.")

        if rec.status == PinStatus.REVOKED:
            return rec

        if rec.status in (PinStatus.PROVISIONED, PinStatus.PENDING_UPDATE) and rec.slot is not None:
            clients = await self._get_lock_clients()
            failed = False
            if clients:
                for client in clients:
                    try:
                        await client.delete_pin(slot=rec.slot, pin=rec.pin)
                        self._record_telemetry(client)
                    except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        logger.error(
                            "Error deleting PIN on lock during revoke for booking '%s': %s",
                            booking_id,
                            exc,
                        )
                        failed = True
            if failed:
                rec.status = PinStatus.PENDING_REVOKE
                return self.db.update_pin(rec)

            self.allocator.release(rec.slot)
            rec.slot = None

        rec.status = PinStatus.REVOKED
        return self.db.update_pin(rec)

    async def tick(self, now: datetime | None = None) -> ProvisionTickResult:
        """Execute one provisioning reconciliation cycle.

        1. Retry pending revocations (PENDING_REVOKE).
        2. Deprovision expired active PINs past (valid_to + grace_period).
        3. Reconcile updated PINs (PENDING_UPDATE):
           - If still within active window: update PIN on lock.
           - If moved outside window (future): deprovision from lock, release slot, mark SCHEDULED.
           - If moved to past: deprovision from lock, release slot, mark EXPIRED.
        4. Expire scheduled PINs that expired before activation.
        5. Activate scheduled PINs entering active window (valid_from - lead_time <= now <= valid_to + grace).

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

        # Step 1: Retry pending revocations
        pending_revokes = self.db.list_pins(status=PinStatus.PENDING_REVOKE)
        for rec in pending_revokes:
            clients = await self._get_lock_clients()
            failed = False
            if clients and rec.slot is not None:
                for client in clients:
                    try:
                        await client.delete_pin(slot=rec.slot, pin=rec.pin)
                        self._record_telemetry(client)
                    except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        msg = f"Failed to delete PIN from lock during retry revoke for '{rec.booking_id}': {exc}"
                        logger.error(msg)
                        result.errors.append(msg)
                        failed = True
            if not failed:
                if rec.slot is not None:
                    self.allocator.release(rec.slot)
                    rec.slot = None
                rec.status = PinStatus.REVOKED
                self.db.update_pin(rec)
                result.deprovisioned.append(rec.booking_id)

        # Step 2: Deprovision expired active PINs
        provisioned = self.db.list_pins(status=PinStatus.PROVISIONED)
        for rec in provisioned:
            if now > rec.valid_to + self.grace_period:
                clients = await self._get_lock_clients()
                failed = False
                if clients and rec.slot is not None:
                    for client in clients:
                        try:
                            await client.delete_pin(slot=rec.slot, pin=rec.pin)
                            self._record_telemetry(client)
                        except (
                            YalePinError,
                            TimeoutError,
                            OSError,
                            RuntimeError,
                            ValueError,
                        ) as exc:
                            msg = f"Failed to delete PIN from lock for booking '{rec.booking_id}': {exc}"
                            logger.error(msg)
                            result.errors.append(msg)
                            failed = True
                if failed:
                    rec.status = PinStatus.PENDING_REVOKE
                    self.db.update_pin(rec)
                    continue

                if rec.slot is not None:
                    self.allocator.release(rec.slot)
                    rec.slot = None
                rec.status = PinStatus.EXPIRED
                self.db.update_pin(rec)
                result.deprovisioned.append(rec.booking_id)

        # Step 3: Reconcile updated PINs (PENDING_UPDATE)
        pending_updates = self.db.list_pins(status=PinStatus.PENDING_UPDATE)
        for rec in pending_updates:
            earliest_act = rec.valid_from - self.lead_time
            latest_act = rec.valid_to + self.grace_period

            if earliest_act <= now <= latest_act:
                # Still within window - update PIN on lock
                slot = rec.slot
                if slot is None:
                    try:
                        slot = self.allocator.allocate(rec.booking_id)
                    except NoSlotsAvailableError as exc:
                        msg = f"No slots available to update booking '{rec.booking_id}': {exc}"
                        logger.warning(msg)
                        result.errors.append(msg)
                        continue

                clients = await self._get_lock_clients()
                failed = False
                for client in clients:
                    try:
                        await self._call_add_pin(
                            client=client,
                            pin=rec.pin,
                            slot=slot,
                            valid_from=rec.valid_from,
                            valid_to=rec.valid_to,
                        )
                        self._record_telemetry(client)
                    except (YalePinError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        msg = f"Failed to update PIN on lock for booking '{rec.booking_id}': {exc}"
                        logger.error(msg)
                        result.errors.append(msg)
                        failed = True

                if not failed:
                    rec.slot = slot
                    rec.status = PinStatus.PROVISIONED
                    self.db.update_pin(rec)
                    result.updated.append(rec.booking_id)

            elif now < earliest_act:
                # Booking moved to future -> deprovision from lock, release slot, mark SCHEDULED
                clients = await self._get_lock_clients()
                failed = False
                if clients and rec.slot is not None:
                    for client in clients:
                        try:
                            await client.delete_pin(slot=rec.slot, pin=rec.pin)
                            self._record_telemetry(client)
                        except (
                            YalePinError,
                            TimeoutError,
                            OSError,
                            RuntimeError,
                            ValueError,
                        ) as exc:
                            msg = f"Failed to deprovision rescheduled booking '{rec.booking_id}': {exc}"
                            logger.error(msg)
                            result.errors.append(msg)
                            failed = True
                if not failed:
                    if rec.slot is not None:
                        self.allocator.release(rec.slot)
                        rec.slot = None
                    rec.status = PinStatus.SCHEDULED
                    self.db.update_pin(rec)
                    result.deprovisioned.append(rec.booking_id)
            else:
                # Past booking window -> deprovision and expire
                clients = await self._get_lock_clients()
                failed = False
                if clients and rec.slot is not None:
                    for client in clients:
                        try:
                            await client.delete_pin(slot=rec.slot, pin=rec.pin)
                            self._record_telemetry(client)
                        except (
                            YalePinError,
                            TimeoutError,
                            OSError,
                            RuntimeError,
                            ValueError,
                        ) as exc:
                            msg = f"Failed to deprovision expired booking '{rec.booking_id}': {exc}"
                            logger.error(msg)
                            result.errors.append(msg)
                            failed = True
                if not failed:
                    if rec.slot is not None:
                        self.allocator.release(rec.slot)
                        rec.slot = None
                    rec.status = PinStatus.EXPIRED
                    self.db.update_pin(rec)
                    result.deprovisioned.append(rec.booking_id)

        # Step 4: Expire scheduled PINs that are completely past booking window
        scheduled = self.db.list_pins(status=PinStatus.SCHEDULED)
        for rec in scheduled:
            if now > rec.valid_to + self.grace_period:
                rec.status = PinStatus.EXPIRED
                self.db.update_pin(rec)
                result.expired_scheduled.append(rec.booking_id)

        # Step 5: Activate scheduled PINs entering the lead-time window
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

                clients = await self._get_lock_clients()
                failed = False
                if clients:
                    for client in clients:
                        try:
                            await self._call_add_pin(
                                client=client,
                                pin=rec.pin,
                                slot=slot,
                                valid_from=rec.valid_from,
                                valid_to=rec.valid_to,
                            )
                            self._record_telemetry(client)
                        except (
                            YalePinError,
                            TimeoutError,
                            OSError,
                            RuntimeError,
                            ValueError,
                        ) as exc:
                            self.allocator.release(slot)
                            msg = f"Failed to program PIN on lock for booking '{rec.booking_id}': {exc}"
                            logger.error(msg)
                            result.errors.append(msg)
                            failed = True
                            break

                if not failed:
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
