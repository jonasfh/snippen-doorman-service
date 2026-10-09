"""In-memory implementation of ReservationStore for testing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from snippen_doorman.state.models import (
    ReservationRecord,
    ReservationStatus,
)


class InMemoryReservationStore:
    """In-memory dictionary implementation of the ReservationStore protocol."""

    def __init__(self) -> None:
        """Initialize in-memory store."""
        self._data: dict[str, ReservationRecord] = {}

    def get_reservation(self, booking_id: str) -> ReservationRecord | None:
        """Fetch a reservation by booking_id."""
        return self._data.get(str(booking_id).strip())

    def list_reservations(
        self, status: ReservationStatus | str | None = None
    ) -> list[ReservationRecord]:
        """List reservation records, optionally filtered by status."""
        records = list(self._data.values())
        if status is not None:
            status_val = (
                status if isinstance(status, ReservationStatus) else ReservationStatus(status)
            )
            records = [r for r in records if r.status == status_val]
        records.sort(key=lambda r: r.valid_from)
        return records

    def save_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Create and persist a new reservation record."""
        now_utc = datetime.now(UTC)
        if record.created_at is None:
            record.created_at = now_utc
        if record.modified_at is None:
            record.modified_at = now_utc
        if record.last_seen_at is None:
            record.last_seen_at = now_utc

        self._data[record.booking_id.strip()] = record
        return record

    def update_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Update an existing reservation record and refresh modified_at."""
        now_utc = datetime.now(UTC)
        record.modified_at = now_utc
        if record.last_seen_at is None:
            record.last_seen_at = now_utc

        self._data[record.booking_id.strip()] = record
        return record

    def delete_reservation(self, booking_id: str) -> bool:
        """Permanently delete a reservation record by booking_id."""
        key = str(booking_id).strip()
        if key in self._data:
            del self._data[key]
            return True
        return False

    def close(self) -> None:
        """Close storage."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
