"""SQLite-backed implementation of ReservationStore."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from snippen_doorman.state.models import (
    ReservationRecord,
    ReservationStatus,
    format_utc_iso,
    parse_utc_iso,
)

logger = logging.getLogger(__name__)


class SqliteReservationStore:
    """SQLite implementation of the ReservationStore protocol."""

    def __init__(self, db_path: str | Path = "data/doorman.db") -> None:
        """Initialize database connection and ensure tables exist."""
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create reservations table and indexes if they do not exist."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    booking_id TEXT PRIMARY KEY NOT NULL,
                    lock_id TEXT,
                    pin TEXT,
                    status TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations(status);"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reservations_valid_from ON reservations(valid_from);"
            )

            # Check if lock_id column exists (migration for existing databases)
            cursor = self._conn.execute("PRAGMA table_info(reservations);")
            cols = [row["name"] for row in cursor.fetchall()]
            if "lock_id" not in cols:
                self._conn.execute("ALTER TABLE reservations ADD COLUMN lock_id TEXT;")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reservations_lock_id ON reservations(lock_id);"
            )

    def get_reservation(self, booking_id: str) -> ReservationRecord | None:
        """Fetch a reservation by booking_id."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM reservations WHERE booking_id = ?",
                (str(booking_id).strip(),),
            )
            row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def list_reservations(
        self, status: ReservationStatus | str | None = None
    ) -> list[ReservationRecord]:
        """List reservation records, optionally filtered by status."""
        with self._lock:
            if status is not None:
                status_val = status.value if isinstance(status, ReservationStatus) else str(status)
                cursor = self._conn.execute(
                    "SELECT * FROM reservations WHERE status = ? ORDER BY valid_from ASC",
                    (status_val,),
                )
            else:
                cursor = self._conn.execute("SELECT * FROM reservations ORDER BY valid_from ASC")
            rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def save_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Create and persist a new reservation record."""
        now_utc = datetime.now(UTC)
        created_at = record.created_at or now_utc
        modified_at = record.modified_at or now_utc
        last_seen_at = record.last_seen_at or now_utc

        record.created_at = created_at
        record.modified_at = modified_at
        record.last_seen_at = last_seen_at

        status_val = (
            record.status.value
            if isinstance(record.status, ReservationStatus)
            else str(record.status)
        )

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO reservations (
                    booking_id, lock_id, pin, status, valid_from, valid_to,
                    content_hash, last_seen_at, created_at, modified_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.booking_id.strip(),
                    record.lock_id,
                    record.pin,
                    status_val,
                    format_utc_iso(record.valid_from),
                    format_utc_iso(record.valid_to),
                    record.content_hash,
                    format_utc_iso(last_seen_at),
                    format_utc_iso(created_at),
                    format_utc_iso(modified_at),
                ),
            )
        return record

    def update_reservation(self, record: ReservationRecord) -> ReservationRecord:
        """Update an existing reservation record and refresh modified_at."""
        now_utc = datetime.now(UTC)
        record.modified_at = now_utc
        if record.last_seen_at is None:
            record.last_seen_at = now_utc

        status_val = (
            record.status.value
            if isinstance(record.status, ReservationStatus)
            else str(record.status)
        )

        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE reservations
                SET lock_id = COALESCE(?, lock_id), pin = ?, status = ?, valid_from = ?, valid_to = ?,
                    content_hash = ?, last_seen_at = ?, modified_at = ?
                WHERE booking_id = ?
                """,
                (
                    record.lock_id,
                    record.pin,
                    status_val,
                    format_utc_iso(record.valid_from),
                    format_utc_iso(record.valid_to),
                    record.content_hash,
                    format_utc_iso(record.last_seen_at),
                    format_utc_iso(record.modified_at),
                    record.booking_id.strip(),
                ),
            )
        return record

    def delete_reservation(self, booking_id: str) -> bool:
        """Permanently delete a reservation record by booking_id."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM reservations WHERE booking_id = ?",
                (str(booking_id).strip(),),
            )
            return cursor.rowcount > 0

    def _row_to_record(self, row: sqlite3.Row) -> ReservationRecord:
        """Convert a SQLite row to a ReservationRecord instance."""
        return ReservationRecord(
            booking_id=row["booking_id"],
            pin=row["pin"],
            status=ReservationStatus(row["status"]),
            valid_from=parse_utc_iso(row["valid_from"]) or datetime.now(UTC),
            valid_to=parse_utc_iso(row["valid_to"]) or datetime.now(UTC),
            content_hash=row["content_hash"],
            lock_id=row["lock_id"] if "lock_id" in set(row.keys()) else None,
            last_seen_at=parse_utc_iso(row["last_seen_at"]),
            created_at=parse_utc_iso(row["created_at"]),
            modified_at=parse_utc_iso(row["modified_at"]),
        )

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
