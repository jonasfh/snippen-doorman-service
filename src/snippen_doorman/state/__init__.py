"""State management and pluggable storage backends for Snippen Doorman."""

from __future__ import annotations

from pathlib import Path

from snippen_doorman.state.base import ReservationStore
from snippen_doorman.state.json_store import JsonFileReservationStore
from snippen_doorman.state.memory_store import InMemoryReservationStore
from snippen_doorman.state.models import (
    ReservationRecord,
    ReservationStatus,
    compute_content_hash,
    format_utc_iso,
    parse_utc_iso,
)
from snippen_doorman.state.sqlite_store import SqliteReservationStore


def create_reservation_store(
    storage_type: str = "sqlite",
    path: str | Path | None = None,
) -> ReservationStore:
    """Factory creating a configured ReservationStore instance.

    Args:
        storage_type: Storage backend type ('sqlite', 'json', or 'memory').
        path: Filepath for sqlite or json storage.
    """
    storage_type = storage_type.lower().strip()
    if storage_type == "sqlite":
        db_path = path or "data/doorman.db"
        return SqliteReservationStore(db_path=db_path)
    if storage_type in ("json", "file"):
        json_path = path or "data/reservations.json"
        return JsonFileReservationStore(file_path=json_path)
    if storage_type in ("memory", "inmemory", ":memory:"):
        return InMemoryReservationStore()
    raise ValueError(
        f"Unknown storage_type '{storage_type}'. Expected 'sqlite', 'json', or 'memory'."
    )


__all__ = [
    "InMemoryReservationStore",
    "JsonFileReservationStore",
    "ReservationRecord",
    "ReservationStatus",
    "ReservationStore",
    "SqliteReservationStore",
    "compute_content_hash",
    "create_reservation_store",
    "format_utc_iso",
    "parse_utc_iso",
]
