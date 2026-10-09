"""Base protocol definition for reservation state storage backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from snippen_doorman.state.models import ReservationRecord, ReservationStatus


@runtime_checkable
class ReservationStore(Protocol):
    """Storage protocol for managing local reservation state."""

    def get_reservation(self, booking_id: str) -> ReservationRecord | None:
        """Fetch a single reservation by booking_id."""
        ...

    def list_reservations(
        self, status: ReservationStatus | str | None = None
    ) -> list[ReservationRecord]:
        """List all reservations, optionally filtered by status."""
        ...

    def save_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Create and persist a new reservation record."""
        ...

    def update_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Update an existing reservation record and refresh modified_at."""
        ...

    def delete_reservation(self, booking_id: str) -> bool:
        """Permanently delete a reservation record by booking_id."""
        ...

    def close(self) -> None:
        """Close any open storage resources."""
        ...
