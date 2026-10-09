"""Snippen Doorman Service - Access control for Yale Doorman locks."""

from __future__ import annotations

__version__ = "0.8.0"

from snippen_doorman.allocator import NoSlotsAvailableError, SlotAllocator
from snippen_doorman.booking_client import (
    BookingApiError,
    BookingAuthError,
    BookingClientError,
    BookingNetworkError,
    RemoteBooking,
    SnippenBookingClient,
)
from snippen_doorman.db import Database, PinRecord, PinStatus
from snippen_doorman.poller import BookingPoller, PollTickResult
from snippen_doorman.provisioner import (
    PinProvisioner,
    ProvisionTickResult,
    run_provisioning_scheduler,
)
from snippen_doorman.state import (
    InMemoryReservationStore,
    JsonFileReservationStore,
    ReservationRecord,
    ReservationStatus,
    ReservationStore,
    SqliteReservationStore,
    create_reservation_store,
)

__all__ = [
    "BookingApiError",
    "BookingAuthError",
    "BookingClientError",
    "BookingNetworkError",
    "BookingPoller",
    "Database",
    "InMemoryReservationStore",
    "JsonFileReservationStore",
    "NoSlotsAvailableError",
    "PinProvisioner",
    "PinRecord",
    "PinStatus",
    "PollTickResult",
    "ProvisionTickResult",
    "RemoteBooking",
    "ReservationRecord",
    "ReservationStatus",
    "ReservationStore",
    "SlotAllocator",
    "SnippenBookingClient",
    "SqliteReservationStore",
    "__version__",
    "create_reservation_store",
    "run_provisioning_scheduler",
]
