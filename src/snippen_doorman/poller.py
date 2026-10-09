"""Polling service synchronizing reservations from Snippen Booking into local state."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from snippen_doorman.booking_client import (
    BookingClientError,
    RemoteBooking,
    SnippenBookingClient,
)
from snippen_doorman.state.base import ReservationStore
from snippen_doorman.state.models import (
    ReservationRecord,
    ReservationStatus,
    compute_content_hash,
)

logger = logging.getLogger(__name__)


def generate_secure_pin(length: int = 6) -> str:
    """Generate a random numeric PIN string of specified length (default 6 digits)."""
    # Generate 6 random digits between 000000 and 999999
    max_val = 10**length
    num = secrets.randbelow(max_val)
    return f"{num:0{length}d}"


@dataclass
class PollTickResult:
    """Summary of operations performed during a single polling cycle."""

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BookingPoller:
    """Synchronizes booking reservations from Snippen Booking into the local store."""

    def __init__(
        self,
        client: SnippenBookingClient,
        store: ReservationStore,
        auto_generate_pin: bool = True,
        pin_generator: Callable[[], str] | None = None,
    ) -> None:
        """Initialize poller with booking client, local store, and PIN strategy.

        Args:
            client: SnippenBookingClient instance.
            store: ReservationStore instance (SQLite or JSON).
            auto_generate_pin: Whether to generate and patch PIN if remote has none.
            pin_generator: Custom PIN generation callable (defaults to 6-digit random).
        """
        self.client = client
        self.store = store
        self.auto_generate_pin = auto_generate_pin
        self.pin_generator = pin_generator or generate_secure_pin

    def poll_once(self, now: datetime | None = None) -> PollTickResult:
        """Execute a single polling synchronization cycle.

        1. Fetches current and upcoming reservations from Snippen Booking platform.
        2. Detects new reservations and persists them.
        3. Detects updated reservations (time or code modified) and updates state.
        4. Detects unchanged reservations and updates last_seen timestamp.
        5. Identifies previously active reservations that are no longer returned and marks them REMOVED.
        6. Tolerates temporary network or API failures without mutating local state.

        Args:
            now: Current timestamp (defaults to UTC now).

        Returns:
            PollTickResult summarizing operations completed.
        """
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        result = PollTickResult()

        try:
            remote_bookings: list[RemoteBooking] = self.client.fetch_bookings()
        except BookingClientError as exc:
            msg = f"Failed to poll Snippen Booking: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            return result
        except Exception as exc:
            msg = f"Unexpected error during booking polling: {exc}"
            logger.exception(msg)
            result.errors.append(msg)
            return result

        remote_by_id: dict[str, RemoteBooking] = {rb.id: rb for rb in remote_bookings}

        # Step 1: Reconcile incoming remote bookings against local store
        for booking_id, remote in remote_by_id.items():
            existing = self.store.get_reservation(booking_id)

            if existing is None:
                # NEW reservation
                pin = remote.door_code
                if pin is None and self.auto_generate_pin:
                    pin = self.pin_generator()
                    try:
                        self.client.update_booking_code(booking_id, pin)
                    except BookingClientError as exc:
                        logger.warning(
                            "Failed to report generated PIN %s for booking %s: %s",
                            pin,
                            booking_id,
                            exc,
                        )

                content_hash = compute_content_hash(remote.start_time, remote.end_time, pin)
                record = ReservationRecord(
                    booking_id=booking_id,
                    valid_from=remote.start_time,
                    valid_to=remote.end_time,
                    pin=pin,
                    status=ReservationStatus.ACTIVE,
                    content_hash=content_hash,
                    last_seen_at=now,
                )
                self.store.save_reservation(record)
                result.added.append(booking_id)
                logger.info(
                    "New reservation detected: %s (valid %s to %s)",
                    booking_id,
                    remote.start_time,
                    remote.end_time,
                )

            else:
                # Existing reservation - check for content changes
                target_pin = remote.door_code if remote.door_code is not None else existing.pin
                if target_pin is None and self.auto_generate_pin:
                    target_pin = self.pin_generator()
                    try:
                        self.client.update_booking_code(booking_id, target_pin)
                    except BookingClientError as exc:
                        logger.warning(
                            "Failed to report generated PIN for existing booking %s: %s",
                            booking_id,
                            exc,
                        )

                new_hash = compute_content_hash(remote.start_time, remote.end_time, target_pin)
                has_changed = new_hash != existing.content_hash or existing.status in (
                    ReservationStatus.REMOVED,
                    ReservationStatus.CANCELLED,
                )

                if has_changed:
                    existing.valid_from = remote.start_time
                    existing.valid_to = remote.end_time
                    existing.pin = target_pin
                    existing.content_hash = new_hash
                    existing.status = ReservationStatus.UPDATED
                    existing.last_seen_at = now
                    self.store.update_reservation(existing)
                    result.updated.append(booking_id)
                    logger.info("Updated reservation detected: %s", booking_id)
                else:
                    existing.last_seen_at = now
                    self.store.update_reservation(existing)
                    result.unchanged.append(booking_id)

        # Step 2: Identify reservations missing from remote poll (removed/irrelevant)
        all_stored = self.store.list_reservations()
        for record in all_stored:
            if record.booking_id not in remote_by_id and record.status in (
                ReservationStatus.ACTIVE,
                ReservationStatus.NEW,
                ReservationStatus.UPDATED,
            ):
                record.status = ReservationStatus.REMOVED
                self.store.update_reservation(record)
                result.removed.append(record.booking_id)
                logger.info(
                    "Reservation no longer relevant in booking platform: %s", record.booking_id
                )

        return result

    async def run_loop(
        self,
        interval_seconds: float = 60.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Run periodic polling loop until stop_event is set."""
        logger.info("Starting BookingPoller loop (interval: %.1fs)", interval_seconds)
        while stop_event is None or not stop_event.is_set():
            try:
                # Run synchronous poll_once in thread pool to avoid blocking asyncio event loop
                res = await asyncio.to_thread(self.poll_once)
                logger.debug(
                    "Poll tick completed: %d added, %d updated, %d removed, %d unchanged, %d errors",
                    len(res.added),
                    len(res.updated),
                    len(res.removed),
                    len(res.unchanged),
                    len(res.errors),
                )
            except Exception:
                logger.exception("Unexpected exception in BookingPoller tick")

            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                    break
                except TimeoutError:
                    continue
            else:
                await asyncio.sleep(interval_seconds)
        logger.info("BookingPoller loop terminated cleanly.")
