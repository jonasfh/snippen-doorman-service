"""Database models and SQLite storage for PIN code provisioning."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Self

logger = logging.getLogger(__name__)


class PinStatus(str, Enum):
    """Lifecycle status of a temporary PIN code reservation."""

    SCHEDULED = "SCHEDULED"
    PROVISIONED = "PROVISIONED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


@dataclass
class PinRecord:
    """Represents a stored PIN reservation record."""

    booking_id: str
    pin: str
    valid_from: datetime
    valid_to: datetime
    id: int | None = None
    slot: int | None = None
    status: PinStatus = PinStatus.SCHEDULED
    created_at: datetime | None = None
    modified_at: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.status, str) and not isinstance(self.status, PinStatus):
            self.status = PinStatus(self.status)


def _format_datetime(dt: datetime) -> str:
    """Format datetime as UTC ISO-8601 string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def _parse_datetime(val: str) -> datetime:
    """Parse UTC ISO-8601 string back to timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class Database:
    """SQLite storage for PIN management and audit tracking."""

    def __init__(self, db_path: str | Path = "data/doorman.db") -> None:
        """Initialize database connection and ensure tables exist."""
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create database tables and indexes if they do not exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_id TEXT UNIQUE NOT NULL,
                    slot INTEGER,
                    pin TEXT NOT NULL,
                    status TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pins_booking_id ON pins(booking_id);"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_pins_status ON pins(status);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_pins_slot ON pins(slot);")

    def create_pin(
        self,
        booking_id: str,
        pin: str,
        valid_from: datetime,
        valid_to: datetime,
        status: PinStatus = PinStatus.SCHEDULED,
        slot: int | None = None,
    ) -> PinRecord:
        """Create a new PIN reservation record.

        Args:
            booking_id: Unique booking identifier.
            pin: 4 to 6 digit numeric code.
            valid_from: Start of validity period (UTC).
            valid_to: End of validity period (UTC).
            status: Initial record status (default: SCHEDULED).
            slot: Keypad slot if already assigned.

        Returns:
            The created PinRecord with database ID and timestamps.
        """
        if not booking_id or not booking_id.strip():
            raise ValueError("booking_id must not be empty.")
        if not pin.isdigit() or not (4 <= len(pin) <= 6):
            raise ValueError(f"PIN must be 4-6 digits, got '{pin}'.")
        if valid_to <= valid_from:
            raise ValueError("valid_to must be after valid_from.")

        now_utc = datetime.now(UTC)
        created_str = _format_datetime(now_utc)
        valid_from_str = _format_datetime(valid_from)
        valid_to_str = _format_datetime(valid_to)

        status_val = status.value if isinstance(status, PinStatus) else str(status)

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO pins (booking_id, slot, pin, status, valid_from, valid_to, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id.strip(),
                    slot,
                    pin,
                    status_val,
                    valid_from_str,
                    valid_to_str,
                    created_str,
                    created_str,
                ),
            )
            record_id = cursor.lastrowid

        return PinRecord(
            id=record_id,
            booking_id=booking_id.strip(),
            slot=slot,
            pin=pin,
            status=status if isinstance(status, PinStatus) else PinStatus(status),
            valid_from=valid_from if valid_from.tzinfo else valid_from.replace(tzinfo=UTC),
            valid_to=valid_to if valid_to.tzinfo else valid_to.replace(tzinfo=UTC),
            created_at=now_utc,
            modified_at=now_utc,
        )

    def get_pin(self, booking_id: str) -> PinRecord | None:
        """Fetch a PIN record by booking_id."""
        cursor = self._conn.execute(
            "SELECT * FROM pins WHERE booking_id = ?",
            (booking_id,),
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def get_pin_by_id(self, pin_id: int) -> PinRecord | None:
        """Fetch a PIN record by internal primary key."""
        cursor = self._conn.execute(
            "SELECT * FROM pins WHERE id = ?",
            (pin_id,),
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def list_pins(self, status: PinStatus | str | None = None) -> list[PinRecord]:
        """List PIN records, optionally filtered by status."""
        if status is not None:
            status_val = status.value if isinstance(status, PinStatus) else str(status)
            cursor = self._conn.execute(
                "SELECT * FROM pins WHERE status = ? ORDER BY valid_from ASC",
                (status_val,),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM pins ORDER BY valid_from ASC")
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def update_pin(self, record: PinRecord) -> PinRecord:
        """Update an existing PIN record and refresh its modified_at timestamp."""
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")

        now_utc = datetime.now(UTC)
        modified_str = _format_datetime(now_utc)
        status_val = (
            record.status.value if isinstance(record.status, PinStatus) else str(record.status)
        )

        with self._conn:
            self._conn.execute(
                """
                UPDATE pins
                SET slot = ?, pin = ?, status = ?, valid_from = ?, valid_to = ?, modified_at = ?
                WHERE id = ?
                """,
                (
                    record.slot,
                    record.pin,
                    status_val,
                    _format_datetime(record.valid_from),
                    _format_datetime(record.valid_to),
                    modified_str,
                    record.id,
                ),
            )

        record.modified_at = now_utc
        return record

    def delete_pin(self, booking_id: str) -> bool:
        """Permanently delete a record by booking_id."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM pins WHERE booking_id = ?",
                (booking_id,),
            )
            return cursor.rowcount > 0

    def _row_to_record(self, row: sqlite3.Row) -> PinRecord:
        """Convert a SQLite row to a PinRecord instance."""
        return PinRecord(
            id=row["id"],
            booking_id=row["booking_id"],
            slot=row["slot"],
            pin=row["pin"],
            status=PinStatus(row["status"]),
            valid_from=_parse_datetime(row["valid_from"]),
            valid_to=_parse_datetime(row["valid_to"]),
            created_at=_parse_datetime(row["created_at"]),
            modified_at=_parse_datetime(row["modified_at"]),
        )

    def close(self) -> None:
        """Close database connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
