"""Unit tests for pluggable reservation storage backends."""

from datetime import UTC, datetime, timedelta

import pytest

from snippen_doorman.state import (
    InMemoryReservationStore,
    JsonFileReservationStore,
    ReservationRecord,
    ReservationStatus,
    SqliteReservationStore,
    compute_content_hash,
    create_reservation_store,
)


@pytest.fixture(
    params=[
        "memory",
        "sqlite",
        "json",
    ]
)
def store(request, tmp_path):
    """Fixture providing instances of each ReservationStore implementation."""
    store_type = request.param
    if store_type == "memory":
        s = InMemoryReservationStore()
    elif store_type == "sqlite":
        db_file = tmp_path / "test_doorman.db"
        s = SqliteReservationStore(db_path=db_file)
    elif store_type == "json":
        json_file = tmp_path / "test_reservations.json"
        s = JsonFileReservationStore(file_path=json_file)
    else:
        raise ValueError(f"Unknown fixture type: {store_type}")

    yield s
    s.close()


def test_save_and_get_reservation(store):
    now = datetime.now(UTC)
    valid_from = now + timedelta(hours=1)
    valid_to = now + timedelta(hours=3)

    record = ReservationRecord(
        booking_id="res_101",
        valid_from=valid_from,
        valid_to=valid_to,
        pin="123456",
        status=ReservationStatus.ACTIVE,
    )

    saved = store.save_reservation(record)
    assert saved.booking_id == "res_101"
    assert saved.created_at is not None
    assert saved.modified_at is not None

    fetched = store.get_reservation("res_101")
    assert fetched is not None
    assert fetched.booking_id == "res_101"
    assert fetched.pin == "123456"
    assert fetched.status == ReservationStatus.ACTIVE
    assert fetched.valid_from.replace(microsecond=0) == valid_from.replace(microsecond=0)
    assert fetched.valid_to.replace(microsecond=0) == valid_to.replace(microsecond=0)
    assert fetched.content_hash == compute_content_hash(valid_from, valid_to, "123456")


def test_update_reservation(store):
    now = datetime.now(UTC)
    record = ReservationRecord(
        booking_id="res_102",
        valid_from=now,
        valid_to=now + timedelta(hours=2),
        pin=None,
        status=ReservationStatus.NEW,
    )
    store.save_reservation(record)

    first_modified = record.modified_at
    record.pin = "654321"
    record.status = ReservationStatus.ACTIVE
    record.content_hash = compute_content_hash(record.valid_from, record.valid_to, "654321")

    updated = store.update_reservation(record)
    assert updated.pin == "654321"
    assert updated.status == ReservationStatus.ACTIVE
    assert updated.modified_at is not None
    assert updated.modified_at >= first_modified

    fetched = store.get_reservation("res_102")
    assert fetched is not None
    assert fetched.pin == "654321"
    assert fetched.status == ReservationStatus.ACTIVE
    assert fetched.content_hash == record.content_hash


def test_delete_reservation(store):
    now = datetime.now(UTC)
    record = ReservationRecord(
        booking_id="res_103",
        valid_from=now,
        valid_to=now + timedelta(hours=1),
    )
    store.save_reservation(record)

    assert store.get_reservation("res_103") is not None
    deleted = store.delete_reservation("res_103")
    assert deleted is True
    assert store.get_reservation("res_103") is None
    assert store.delete_reservation("res_103") is False


def test_list_reservations_with_filter(store):
    now = datetime.now(UTC)
    r1 = ReservationRecord(
        booking_id="res_201",
        valid_from=now + timedelta(hours=1),
        valid_to=now + timedelta(hours=2),
        status=ReservationStatus.ACTIVE,
    )
    r2 = ReservationRecord(
        booking_id="res_202",
        valid_from=now + timedelta(hours=3),
        valid_to=now + timedelta(hours=4),
        status=ReservationStatus.CANCELLED,
    )
    store.save_reservation(r1)
    store.save_reservation(r2)

    all_recs = store.list_reservations()
    assert len(all_recs) == 2

    active_recs = store.list_reservations(status=ReservationStatus.ACTIVE)
    assert len(active_recs) == 1
    assert active_recs[0].booking_id == "res_201"

    cancelled_recs = store.list_reservations(status=ReservationStatus.CANCELLED)
    assert len(cancelled_recs) == 1
    assert cancelled_recs[0].booking_id == "res_202"


def test_json_store_persistence(tmp_path):
    json_file = tmp_path / "persist.json"
    now = datetime.now(UTC)
    store1 = JsonFileReservationStore(json_file)
    store1.save_reservation(
        ReservationRecord(
            booking_id="res_301",
            valid_from=now,
            valid_to=now + timedelta(hours=2),
            pin="999888",
        )
    )
    store1.close()

    # Re-open from disk and verify persistence
    store2 = JsonFileReservationStore(json_file)
    rec = store2.get_reservation("res_301")
    assert rec is not None
    assert rec.pin == "999888"
    store2.close()


def test_factory_create_reservation_store(tmp_path):
    mem = create_reservation_store("memory")
    assert isinstance(mem, InMemoryReservationStore)

    sqlite = create_reservation_store("sqlite", tmp_path / "f.db")
    assert isinstance(sqlite, SqliteReservationStore)

    js = create_reservation_store("json", tmp_path / "f.json")
    assert isinstance(js, JsonFileReservationStore)

    with pytest.raises(ValueError, match="Unknown storage_type"):
        create_reservation_store("unknown_backend")
