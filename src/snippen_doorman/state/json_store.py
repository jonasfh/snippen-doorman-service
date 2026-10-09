"""JSON file-backed implementation of ReservationStore for lightweight deployments."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from snippen_doorman.state.models import (
    ReservationRecord,
    ReservationStatus,
)

logger = logging.getLogger(__name__)


class JsonFileReservationStore:
    """Lightweight JSON file implementation of the ReservationStore protocol.

    Uses atomic file replacement to prevent file corruption during crashes or power cuts.
    """

    def __init__(self, file_path: str | Path = "data/reservations.json") -> None:
        """Initialize JSON file store path and load or initialize data."""
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, ReservationRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load reservations from JSON file if it exists."""
        if not self.file_path.exists():
            self._cache = {}
            return

        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    self._cache = {}
                    return
                data = json.loads(content)
                records = data.get("reservations", [])
                self._cache = {
                    rec["booking_id"]: ReservationRecord.from_dict(rec) for rec in records
                }
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load JSON reservation store from %s: %s", self.file_path, exc)
            self._cache = {}

    def _save(self) -> None:
        """Atomically persist cache to disk via a temporary file."""
        temp_path = self.file_path.with_suffix(".json.tmp")
        records = [rec.to_dict() for rec in self._cache.values()]
        payload = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "reservations": records,
        }

        try:
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.file_path)
        except OSError as exc:
            logger.error("Failed to write JSON reservation store to %s: %s", self.file_path, exc)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def get_reservation(self, booking_id: str) -> ReservationRecord | None:
        """Fetch a reservation by booking_id."""
        return self._cache.get(str(booking_id).strip())

    def list_reservations(
        self, status: ReservationStatus | str | None = None
    ) -> list[ReservationRecord]:
        """List reservation records, optionally filtered by status."""
        records = list(self._cache.values())
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

        self._cache[record.booking_id.strip()] = record
        self._save()
        return record

    def update_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Update an existing reservation record and refresh modified_at."""
        now_utc = datetime.now(UTC)
        record.modified_at = now_utc
        if record.last_seen_at is None:
            record.last_seen_at = now_utc

        self._cache[record.booking_id.strip()] = record
        self._save()
        return record

    def delete_reservation(self, booking_id: str) -> bool:
        """Permanently delete a reservation record by booking_id."""
        key = str(booking_id).strip()
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def close(self) -> None:
        """Close storage (flush any pending operations)."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
