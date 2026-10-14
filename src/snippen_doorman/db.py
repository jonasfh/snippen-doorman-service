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
    PENDING_UPDATE = "PENDING_UPDATE"
    PENDING_REVOKE = "PENDING_REVOKE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


@dataclass
class LockStatusRecord:
    """Represents opportunistic status and battery telemetry recorded from a Yale lock."""

    lock_address: str
    lock_status: str | None = None
    door_status: str | None = None
    battery: int | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None


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
    lock_id: str = "default"
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
                    booking_id TEXT NOT NULL,
                    lock_id TEXT DEFAULT 'default',
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

            # Check if lock_id column exists (migration for existing databases)
            cursor = self._conn.execute("PRAGMA table_info(pins);")
            cols = [row["name"] for row in cursor.fetchall()]
            if "lock_id" not in cols:
                self._conn.execute("ALTER TABLE pins ADD COLUMN lock_id TEXT DEFAULT 'default';")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_pins_lock_id ON pins(lock_id);")

            # Telemetry table for opportunistic lock status and battery tracking
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lock_status (
                    lock_address TEXT PRIMARY KEY,
                    lock_status TEXT,
                    door_status TEXT,
                    battery INTEGER,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                );
                """
            )

    def record_lock_status(
        self,
        lock_address: str,
        lock_status: str | None = None,
        door_status: str | None = None,
        battery: int | None = None,
    ) -> LockStatusRecord:
        """Opportunistically record lock telemetry (status, door, battery)."""
        now_utc = datetime.now(UTC)
        now_str = _format_datetime(now_utc)
        clean_addr = lock_address.strip()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO lock_status (lock_address, lock_status, door_status, battery, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(lock_address) DO UPDATE SET
                    lock_status = COALESCE(excluded.lock_status, lock_status.lock_status),
                    door_status = COALESCE(excluded.door_status, lock_status.door_status),
                    battery = COALESCE(excluded.battery, lock_status.battery),
                    modified_at = excluded.modified_at;
                """,
                (clean_addr, lock_status, door_status, battery, now_str, now_str),
            )
        return LockStatusRecord(
            lock_address=clean_addr,
            lock_status=lock_status,
            door_status=door_status,
            battery=battery,
            created_at=now_utc,
            modified_at=now_utc,
        )

    def get_lock_status(self, lock_address: str) -> LockStatusRecord | None:
        """Get the latest recorded status for a lock."""
        cursor = self._conn.execute(
            "SELECT * FROM lock_status WHERE lock_address = ?",
            (lock_address.strip(),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LockStatusRecord(
            lock_address=row["lock_address"],
            lock_status=row["lock_status"],
            door_status=row["door_status"],
            battery=row["battery"],
            created_at=_parse_datetime(row["created_at"]),
            modified_at=_parse_datetime(row["modified_at"]),
        )

    def create_pin(
        self,
        booking_id: str,
        pin: str,
        valid_from: datetime,
        valid_to: datetime,
        status: PinStatus = PinStatus.SCHEDULED,
        slot: int | None = None,
        lock_id: str = "default",
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
                INSERT INTO pins (booking_id, lock_id, slot, pin, status, valid_from, valid_to, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id.strip(),
                    lock_id.strip(),
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
            lock_id=lock_id.strip(),
            slot=slot,
            pin=pin,
            status=status if isinstance(status, PinStatus) else PinStatus(status),
            valid_from=valid_from if valid_from.tzinfo else valid_from.replace(tzinfo=UTC),
            valid_to=valid_to if valid_to.tzinfo else valid_to.replace(tzinfo=UTC),
            created_at=now_utc,
            modified_at=now_utc,
        )

    def get_pin(self, booking_id: str, lock_id: str | None = None) -> PinRecord | None:
        """Fetch a PIN record by booking_id and optional lock_id."""
        if lock_id is not None:
            cursor = self._conn.execute(
                "SELECT * FROM pins WHERE booking_id = ? AND lock_id = ?",
                (booking_id.strip(), lock_id.strip()),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM pins WHERE booking_id = ?",
                (booking_id.strip(),),
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

    def list_pins(
        self,
        status: PinStatus | str | None = None,
        lock_id: str | None = None,
    ) -> list[PinRecord]:
        """List PIN records, optionally filtered by status and/or lock_id."""
        query = "SELECT * FROM pins"
        params: list[str] = []
        conditions: list[str] = []

        if status is not None:
            status_val = status.value if isinstance(status, PinStatus) else str(status)
            conditions.append("status = ?")
            params.append(status_val)
        if lock_id is not None:
            conditions.append("lock_id = ?")
            params.append(lock_id.strip())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY valid_from ASC"

        cursor = self._conn.execute(query, tuple(params))
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
                SET slot = ?, pin = ?, status = ?, valid_from = ?, valid_to = ?, lock_id = ?, modified_at = ?
                WHERE id = ?
                """,
                (
                    record.slot,
                    record.pin,
                    status_val,
                    _format_datetime(record.valid_from),
                    _format_datetime(record.valid_to),
                    record.lock_id,
                    modified_str,
                    record.id,
                ),
            )

        record.modified_at = now_utc
        return record

    def delete_pin(self, booking_id: str, lock_id: str | None = None) -> bool:
        """Permanently delete a record by booking_id and optional lock_id."""
        with self._conn:
            if lock_id is not None:
                cursor = self._conn.execute(
                    "DELETE FROM pins WHERE booking_id = ? AND lock_id = ?",
                    (booking_id.strip(), lock_id.strip()),
                )
            else:
                cursor = self._conn.execute(
                    "DELETE FROM pins WHERE booking_id = ?",
                    (booking_id.strip(),),
                )
            return cursor.rowcount > 0

    def _row_to_record(self, row: sqlite3.Row) -> PinRecord:
        """Convert a SQLite row to a PinRecord instance."""
        data = dict(row)
        lock_id = data.get("lock_id", "default")
        return PinRecord(
            id=row["id"],
            booking_id=row["booking_id"],
            lock_id=lock_id or "default",
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
