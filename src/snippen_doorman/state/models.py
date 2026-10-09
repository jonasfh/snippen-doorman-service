"""Data models for booking reservations and internal state."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReservationStatus(str, Enum):
    """Lifecycle status of a local reservation record."""

    NEW = "NEW"
    ACTIVE = "ACTIVE"
    UPDATED = "UPDATED"
    CANCELLED = "CANCELLED"
    REMOVED = "REMOVED"


def format_utc_iso(dt: datetime | None) -> str | None:
    """Format datetime as UTC ISO-8601 string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def parse_utc_iso(val: str | None) -> datetime | None:
    """Parse ISO-8601 string to timezone-aware UTC datetime."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_content_hash(
    start_time: datetime | str,
    end_time: datetime | str,
    door_code: str | None = None,
) -> str:
    """Compute deterministic SHA-256 hash of reservation properties.

    Privacy-by-design: Only start_time, end_time, and door_code are hashed.
    """
    start_str = format_utc_iso(start_time) if isinstance(start_time, datetime) else str(start_time)
    end_str = format_utc_iso(end_time) if isinstance(end_time, datetime) else str(end_time)
    code_str = str(door_code) if door_code is not None else ""
    raw = f"{start_str}|{end_str}|{code_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ReservationRecord:
    """Represents a locally tracked booking reservation record."""

    booking_id: str
    valid_from: datetime
    valid_to: datetime
    pin: str | None = None
    status: ReservationStatus = ReservationStatus.ACTIVE
    content_hash: str = ""
    last_seen_at: datetime | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.status, str) and not isinstance(self.status, ReservationStatus):
            self.status = ReservationStatus(self.status)
        if self.valid_from.tzinfo is None:
            self.valid_from = self.valid_from.replace(tzinfo=UTC)
        else:
            self.valid_from = self.valid_from.astimezone(UTC)
        if self.valid_to.tzinfo is None:
            self.valid_to = self.valid_to.replace(tzinfo=UTC)
        else:
            self.valid_to = self.valid_to.astimezone(UTC)
        if not self.content_hash:
            self.content_hash = compute_content_hash(self.valid_from, self.valid_to, self.pin)

    def to_dict(self) -> dict[str, Any]:
        """Convert record to a JSON-serializable dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        data["valid_from"] = format_utc_iso(self.valid_from)
        data["valid_to"] = format_utc_iso(self.valid_to)
        data["last_seen_at"] = format_utc_iso(self.last_seen_at)
        data["created_at"] = format_utc_iso(self.created_at)
        data["modified_at"] = format_utc_iso(self.modified_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReservationRecord:
        """Create a ReservationRecord instance from a dictionary."""
        return cls(
            booking_id=str(data["booking_id"]),
            valid_from=parse_utc_iso(data["valid_from"]) or datetime.now(UTC),
            valid_to=parse_utc_iso(data["valid_to"]) or datetime.now(UTC),
            pin=data.get("pin"),
            status=ReservationStatus(data.get("status", ReservationStatus.ACTIVE)),
            content_hash=data.get("content_hash", ""),
            last_seen_at=parse_utc_iso(data.get("last_seen_at")),
            created_at=parse_utc_iso(data.get("created_at")),
            modified_at=parse_utc_iso(data.get("modified_at")),
        )
