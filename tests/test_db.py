"""Unit tests for SQLite database storage and PinRecord models."""

from datetime import UTC, datetime, timedelta

import pytest

from snippen_doorman.db import Database, PinStatus


@pytest.fixture
def db() -> Database:
    """Provide an in-memory database instance."""
    database = Database(":memory:")
    yield database
    database.close()


def test_create_and_get_pin(db: Database) -> None:
    """Test creating and retrieving a PIN record with timestamps."""
    now = datetime.now(UTC)
    valid_from = now + timedelta(hours=1)
    valid_to = now + timedelta(hours=3)

    record = db.create_pin(
        booking_id="book_123",
        pin="482910",
        valid_from=valid_from,
        valid_to=valid_to,
    )

    assert record.id is not None
    assert record.booking_id == "book_123"
    assert record.pin == "482910"
    assert record.status == PinStatus.SCHEDULED
    assert record.slot is None
    assert record.created_at is not None
    assert record.modified_at is not None
    assert record.created_at.tzinfo == UTC
    assert record.modified_at.tzinfo == UTC

    # Fetch by booking_id
    fetched = db.get_pin("book_123")
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.booking_id == "book_123"
    assert fetched.pin == "482910"
    assert fetched.status == PinStatus.SCHEDULED

    # Fetch by id
    fetched_by_id = db.get_pin_by_id(record.id)
    assert fetched_by_id is not None
    assert fetched_by_id.booking_id == "book_123"


def test_pin_validation(db: Database) -> None:
    """Test validation on create_pin."""
    now = datetime.now(UTC)

    # Empty booking ID
    with pytest.raises(ValueError, match="booking_id must not be empty"):
        db.create_pin("", "123456", now, now + timedelta(hours=1))

    # Invalid PIN length
    with pytest.raises(ValueError, match="PIN must be 4-6 digits"):
        db.create_pin("b1", "123", now, now + timedelta(hours=1))
    with pytest.raises(ValueError, match="PIN must be 4-6 digits"):
        db.create_pin("b1", "1234567", now, now + timedelta(hours=1))

    # Non-digit PIN
    with pytest.raises(ValueError, match="PIN must be 4-6 digits"):
        db.create_pin("b1", "12ab56", now, now + timedelta(hours=1))

    # valid_to <= valid_from
    with pytest.raises(ValueError, match="valid_to must be after valid_from"):
        db.create_pin("b1", "123456", now, now)
    with pytest.raises(ValueError, match="valid_to must be after valid_from"):
        db.create_pin("b1", "123456", now + timedelta(hours=2), now)


def test_list_pins_with_filter(db: Database) -> None:
    """Test listing pins filtered by status."""
    now = datetime.now(UTC)
    db.create_pin("b1", "111111", now, now + timedelta(hours=1), status=PinStatus.SCHEDULED)
    db.create_pin(
        "b2",
        "222222",
        now + timedelta(hours=1),
        now + timedelta(hours=2),
        status=PinStatus.PROVISIONED,
        slot=9,
    )
    db.create_pin(
        "b3",
        "333333",
        now + timedelta(hours=2),
        now + timedelta(hours=3),
        status=PinStatus.SCHEDULED,
    )

    all_pins = db.list_pins()
    assert len(all_pins) == 3

    scheduled = db.list_pins(status=PinStatus.SCHEDULED)
    assert len(scheduled) == 2
    assert [p.booking_id for p in scheduled] == ["b1", "b3"]

    provisioned = db.list_pins(status=PinStatus.PROVISIONED)
    assert len(provisioned) == 1
    assert provisioned[0].booking_id == "b2"
    assert provisioned[0].slot == 9


def test_update_pin_refreshes_modified_at(db: Database) -> None:
    """Test updating a pin updates modified_at timestamp."""
    now = datetime.now(UTC)
    rec = db.create_pin("b_update", "555555", now, now + timedelta(hours=1))

    initial_modified = rec.modified_at
    assert initial_modified is not None

    rec.status = PinStatus.PROVISIONED
    rec.slot = 8
    updated = db.update_pin(rec)

    assert updated.status == PinStatus.PROVISIONED
    assert updated.slot == 8
    assert updated.modified_at >= initial_modified

    # Verify persisted in database
    fetched = db.get_pin("b_update")
    assert fetched is not None
    assert fetched.status == PinStatus.PROVISIONED
    assert fetched.slot == 8


def test_delete_pin(db: Database) -> None:
    """Test deleting a pin record."""
    now = datetime.now(UTC)
    db.create_pin("b_del", "666666", now, now + timedelta(hours=1))

    assert db.delete_pin("b_del") is True
    assert db.get_pin("b_del") is None
    assert db.delete_pin("b_del") is False
