"""Unit tests for status reporter building full JSON status snapshot (#75)."""

from datetime import UTC, datetime, timedelta

from snippen_doorman.ble.lock_config import LockConfig
from snippen_doorman.db import Database, PinStatus
from snippen_doorman.state import InMemoryReservationStore
from snippen_doorman.status_reporter import build_full_status_payload


def test_build_full_status_payload_multi_lock_and_history():
    db = Database(":memory:")
    store = InMemoryReservationStore()

    now = datetime(2026, 11, 7, 13, 15, 10, tzinfo=UTC)

    # Configure 2 physical locks sharing booking object lock_id 1
    lock1 = LockConfig(
        name="Inngangsdør 1 (Hoveddør)",
        address="98:1B:B5:0B:BB:35",
        key="0123456789abcdef0123456789abcdef",
        slot=1,
        lock_id=1,
    )
    lock2 = LockConfig(
        name="Inngangsdør 2 (Sidedør)",
        address="98:1B:B5:0B:BB:36",
        key="fedcba9876543210fedcba9876543210",
        slot=1,
        lock_id=1,
    )

    # Telemetry
    db.record_lock_status(
        lock_address=lock1.address,
        battery=85,
        lock_status="LOCKED",
        door_status="CLOSED",
    )
    db.record_lock_status(
        lock_address=lock2.address,
        battery=80,
        lock_status="LOCKED",
        door_status="CLOSED",
    )

    # 1. Provisioned booking on both locks
    db.create_pin(
        booking_id="101",
        pin="123456",
        valid_from=now + timedelta(hours=2),
        valid_to=now + timedelta(days=2),
        status=PinStatus.PROVISIONED,
        slot=3,
        lock_id="1",
    )
    db.upsert_pin_lock_state(
        booking_id="101",
        lock_address=lock1.address,
        lock_name=lock1.name,
        lock_id="1",
        slot=3,
        pin="123456",
        status=PinStatus.PROVISIONED,
    )
    db.upsert_pin_lock_state(
        booking_id="101",
        lock_address=lock2.address,
        lock_name=lock2.name,
        lock_id="1",
        slot=3,
        pin="123456",
        status=PinStatus.PROVISIONED,
    )

    # 2. Upcoming scheduled booking
    db.create_pin(
        booking_id="105",
        pin="789012",
        valid_from=now + timedelta(days=3),
        valid_to=now + timedelta(days=5),
        status=PinStatus.SCHEDULED,
        slot=None,
        lock_id="1",
    )
    db.upsert_pin_lock_state(
        booking_id="105",
        lock_address=lock1.address,
        lock_name=lock1.name,
        lock_id="1",
        slot=None,
        pin="789012",
        status=PinStatus.SCHEDULED,
    )
    db.upsert_pin_lock_state(
        booking_id="105",
        lock_address=lock2.address,
        lock_name=lock2.name,
        lock_id="1",
        slot=None,
        pin="789012",
        status=PinStatus.SCHEDULED,
    )

    # 3. Expired booking from 2 days ago (within 7-day window)
    db.create_pin(
        booking_id="98",
        pin="345678",
        valid_from=now - timedelta(days=4),
        valid_to=now - timedelta(days=2),
        status=PinStatus.EXPIRED,
        slot=None,
        lock_id="1",
    )
    db.upsert_pin_lock_state(
        booking_id="98",
        lock_address=lock1.address,
        lock_name=lock1.name,
        lock_id="1",
        slot=None,
        pin="345678",
        status=PinStatus.EXPIRED,
    )

    # 4. Old expired booking from 15 days ago (outside 7-day window)
    db.create_pin(
        booking_id="50",
        pin="999999",
        valid_from=now - timedelta(days=18),
        valid_to=now - timedelta(days=15),
        status=PinStatus.EXPIRED,
        slot=None,
        lock_id="1",
    )

    payload = build_full_status_payload(
        db=db,
        store=store,
        lock_configs=[lock1, lock2],
        expired_window_days=7,
        now=now,
    )

    assert payload["generated_at"] == now.isoformat()
    assert payload["expired_window_days"] == 7

    # Check locks
    assert len(payload["locks"]) == 2
    l1 = next(lk for lk in payload["locks"] if lk["address"] == lock1.address)
    assert l1["name"] == "Inngangsdør 1 (Hoveddør)"
    assert l1["battery"] == 85
    assert l1["lock_status"] == "LOCKED"
    assert l1["slots"]["3"] == "101"
    assert l1["slots"]["4"] is None

    # Check reservations_in_db
    res_db = payload["reservations_in_db"]
    assert len(res_db) == 2  # 101 and 105 (active & upcoming)
    r101 = next(r for r in res_db if r["booking_id"] == "101")
    assert r101["status"] == "PROVISIONED"
    assert r101["pin"] == "123456"
    assert r101["slot"] == 3
    assert r101["all_locks_provisioned"] is True
    assert len(r101["physical_locks"]) == 2
    assert r101["physical_locks"][0]["status"] == "PROVISIONED"
    assert r101["physical_locks"][1]["status"] == "PROVISIONED"

    r105 = next(r for r in res_db if r["booking_id"] == "105")
    assert r105["status"] == "SCHEDULED"
    assert r105["all_locks_provisioned"] is False

    # Check provisioned_on_locks
    prov = payload["provisioned_on_locks"]
    assert len(prov) == 2  # Both physical locks have 101 provisioned
    addrs = [item["lock_address"] for item in prov]
    assert lock1.address in addrs
    assert lock2.address in addrs
    for item in prov:
        assert item["booking_id"] == "101"
        assert item["slot"] == 3
        assert item["pin"] == "123456"
        assert item["status"] == "PROVISIONED"

    # Check recently_expired
    exp = payload["recently_expired"]
    assert len(exp) == 1
    assert exp[0]["booking_id"] == "98"
    assert exp[0]["status"] == "EXPIRED"
    assert len(exp[0]["physical_locks"]) >= 1

    db.close()
