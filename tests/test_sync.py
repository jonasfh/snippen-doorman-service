"""Comprehensive tests for DoormanSyncEngine, change detection (#29) and BLE synchronization (#30)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from snippen_doorman.allocator import SlotAllocator
from snippen_doorman.ble.client import YaleLockState
from snippen_doorman.booking_client import RemoteBooking
from snippen_doorman.db import Database, PinStatus
from snippen_doorman.poller import BookingPoller
from snippen_doorman.provisioner import PinProvisioner
from snippen_doorman.state import InMemoryReservationStore
from snippen_doorman.state.models import ReservationRecord, ReservationStatus
from snippen_doorman.sync import DoormanSyncEngine


class FakeLockClient:
    """Simulates a physical Yale Lock BLE client for deterministic testing."""

    def __init__(
        self,
        address: str = "AA:BB:CC:DD:EE:01",
        local_name: str | None = None,
        lock_id: str | None = None,
    ) -> None:
        self.address = address
        self.local_name = local_name
        self.lock_id = lock_id
        self.pins: dict[int, str] = {}
        self.add_pin_calls: list[dict] = []
        self.delete_pin_calls: list[dict] = []
        self.fail_add_pin = False
        self.fail_delete_pin = False
        self.battery = 88
        self.lock_status = "LOCKED"
        self.door_status = "CLOSED"

    @property
    def state(self) -> YaleLockState:
        return YaleLockState(
            address=self.address,
            lock_status=self.lock_status,
            door_status=self.door_status,
            battery=self.battery,
            is_connected=True,
        )

    async def add_pin(
        self,
        pin: str,
        slot: int,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        sync_rtc: bool = False,
    ) -> None:
        if self.fail_add_pin:
            raise TimeoutError(f"BLE connection timeout to {self.address}")
        self.pins[slot] = pin
        self.add_pin_calls.append(
            {
                "pin": pin,
                "slot": slot,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "sync_rtc": sync_rtc,
            }
        )

    async def delete_pin(self, slot: int, pin: str | None = None) -> bool:
        if self.fail_delete_pin:
            raise TimeoutError(f"BLE connection timeout to {self.address}")
        self.delete_pin_calls.append({"slot": slot, "pin": pin})
        self.pins.pop(slot, None)
        return True

    async def disconnect(self) -> None:
        pass


@pytest.fixture
def mock_booking_client():
    client = MagicMock()
    client.fetch_bookings.return_value = []
    client.update_booking_code.return_value = True
    return client


@pytest.fixture
def sync_env(mock_booking_client):
    store = InMemoryReservationStore()
    db = Database(":memory:")
    allocator = SlotAllocator(min_slot=3, max_slot=9)
    fake_lock = FakeLockClient(address="AA:BB:CC:DD:EE:01")

    provisioner = PinProvisioner(
        db=db,
        allocator=allocator,
        lock_client=fake_lock,
        lead_time=timedelta(minutes=60),
        grace_period=timedelta(minutes=15),
        sync_rtc=True,
    )

    poller = BookingPoller(
        client=mock_booking_client,
        store=store,
        auto_generate_pin=True,
        pin_generator=lambda: "112233",
    )

    engine = DoormanSyncEngine(
        poller=poller,
        provisioner=provisioner,
        store=store,
        db=db,
        lock_id="default",
    )

    return {
        "engine": engine,
        "poller": poller,
        "provisioner": provisioner,
        "store": store,
        "db": db,
        "allocator": allocator,
        "lock": fake_lock,
        "booking_client": mock_booking_client,
    }


# =====================================================================
# ISSUE #29: Beslutnings- og dvaleprinsipp tester
# =====================================================================


@pytest.mark.asyncio
async def test_decision_new_booking_within_lead_time_provisions_lock(sync_env):
    """Booking starting within lead time (45 min) is scheduled and provisioned immediately."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    # Remote booking starting at 12:45 (in 45m, inside 60m lead time)
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_1",
            start_time=now + timedelta(minutes=45),
            end_time=now + timedelta(hours=2),
            door_code=None,
        )
    ]

    res = await sync_env["engine"].sync_once(now=now)

    assert "book_1" in res.poll.added
    assert "book_1" in res.scheduled
    assert "book_1" in res.provision.activated

    # Lock called once
    assert len(lock.add_pin_calls) == 1
    call = lock.add_pin_calls[0]
    assert call["pin"] == "112233"
    assert call["slot"] == 9  # highest available guest slot
    assert call["sync_rtc"] is True  # RTC clock synchronized opportunistically!


@pytest.mark.asyncio
async def test_sleep_principle_booking_far_in_future_does_not_wake_lock(sync_env):
    """Booking starting tomorrow is scheduled in DB, but lock is NOT contacted (stays asleep)."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    # Starts tomorrow (24 hours in the future)
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_far",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
            door_code="654321",
        )
    ]

    res = await sync_env["engine"].sync_once(now=now)

    assert "book_far" in res.poll.added
    assert "book_far" in res.scheduled
    assert res.provision.activated == []

    # Yale Doorman was NOT contacted
    assert len(lock.add_pin_calls) == 0
    assert len(lock.delete_pin_calls) == 0

    # Record exists in DB as SCHEDULED
    pin_rec = sync_env["db"].get_pin("book_far")
    assert pin_rec is not None
    assert pin_rec.status == PinStatus.SCHEDULED
    assert pin_rec.slot is None


@pytest.mark.asyncio
async def test_sleep_principle_unchanged_booking_causes_zero_ble_calls(sync_env):
    """Polling cycle with unchanged reservations causes ZERO BLE traffic to the lock."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    # 1. First sync - activates PIN on lock
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_active",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            door_code="987123",
        )
    ]
    await sync_env["engine"].sync_once(now=now)
    assert len(lock.add_pin_calls) == 1

    # 2. Second sync - reservation is identical (unchanged)
    lock.add_pin_calls.clear()
    lock.delete_pin_calls.clear()

    res2 = await sync_env["engine"].sync_once(now=now + timedelta(seconds=60))

    assert "book_active" in res2.poll.unchanged
    assert res2.provision.activated == []
    assert res2.provision.updated == []
    assert res2.provision.deprovisioned == []

    # Crucial acceptance criteria: 0 calls to lock!
    assert len(lock.add_pin_calls) == 0
    assert len(lock.delete_pin_calls) == 0


@pytest.mark.asyncio
async def test_decision_updated_pin_or_time_updates_lock(sync_env):
    """When an active reservation's PIN or time is updated, lock is updated in-place."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    # Initial booking
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_mod",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            door_code="111111",
        )
    ]
    await sync_env["engine"].sync_once(now=now)
    assert lock.pins[9] == "111111"

    # User modifies booking PIN in WordPress to "222222"
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_mod",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=3),
            door_code="222222",
        )
    ]

    res2 = await sync_env["engine"].sync_once(now=now + timedelta(minutes=5))

    assert "book_mod" in res2.poll.updated
    assert "book_mod" in res2.provision.updated
    assert lock.pins[9] == "222222"


@pytest.mark.asyncio
async def test_decision_rescheduling_to_future_deprovisions_and_frees_slot(sync_env):
    """When active booking is postponed to next week, code is removed from lock and slot freed."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]
    allocator = sync_env["allocator"]

    # Active booking occupying slot 9
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_move",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            door_code="333333",
        )
    ]
    await sync_env["engine"].sync_once(now=now)
    assert allocator.is_available(9) is False

    # Moved to 3 days in the future
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_move",
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=2),
            door_code="333333",
        )
    ]

    res2 = await sync_env["engine"].sync_once(now=now + timedelta(minutes=1))

    assert "book_move" in res2.provision.deprovisioned
    # Slot 9 freed
    assert allocator.is_available(9) is True
    # Lock code deleted
    assert 9 not in lock.pins
    # DB status is SCHEDULED again
    assert sync_env["db"].get_pin("book_move").status == PinStatus.SCHEDULED


@pytest.mark.asyncio
async def test_decision_cancelled_or_removed_booking_revokes_lock_code(sync_env):
    """When a booking is cancelled / deleted from remote, it is immediately removed from lock."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]
    allocator = sync_env["allocator"]

    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_del",
            start_time=now + timedelta(minutes=20),
            end_time=now + timedelta(hours=1),
            door_code="444444",
        )
    ]
    await sync_env["engine"].sync_once(now=now)
    assert allocator.is_available(9) is False

    # Remote poll returns empty list -> booking removed
    booking_client.fetch_bookings.return_value = []
    res2 = await sync_env["engine"].sync_once(now=now + timedelta(minutes=2))

    assert "book_del" in res2.poll.removed
    assert "book_del" in res2.revoked_schedules
    assert allocator.is_available(9) is True
    assert 9 not in lock.pins
    assert sync_env["db"].get_pin("book_del").status == PinStatus.REVOKED


# =====================================================================
# ISSUE #30: Robust BLE synkronisering & telemetri tester
# =====================================================================


@pytest.mark.asyncio
async def test_ble_failure_does_not_lose_state_and_retries_next_tick(sync_env):
    """If BLE connection fails during add_pin, status is NOT marked PROVISIONED and retries cleanly."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_fail",
            start_time=now + timedelta(minutes=20),
            end_time=now + timedelta(hours=1),
            door_code="778899",
        )
    ]

    # Lock fails BLE connection on first attempt
    lock.fail_add_pin = True
    res1 = await sync_env["engine"].sync_once(now=now)

    assert len(res1.errors) > 0
    assert res1.provision.activated == []
    # State in DB remained SCHEDULED
    pin_rec = sync_env["db"].get_pin("book_fail")
    assert pin_rec.status == PinStatus.SCHEDULED
    # Slot was freed / not leaked
    assert sync_env["allocator"].is_available(9) is True

    # Lock recovers on next polling tick
    lock.fail_add_pin = False
    res2 = await sync_env["engine"].sync_once(now=now + timedelta(seconds=30))

    assert "book_fail" in res2.provision.activated
    assert sync_env["db"].get_pin("book_fail").status == PinStatus.PROVISIONED
    assert lock.pins[9] == "778899"


@pytest.mark.asyncio
async def test_ble_failure_during_revoke_marks_pending_and_retries(sync_env):
    """If lock is unreachable during revoke, status is PENDING_REVOKE and retries until confirmed."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    booking_client = sync_env["booking_client"]

    # Successfully provisioned
    booking_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="book_rev_fail",
            start_time=now + timedelta(minutes=20),
            end_time=now + timedelta(hours=1),
            door_code="555666",
        )
    ]
    await sync_env["engine"].sync_once(now=now)

    # Now booking cancelled, but lock is temporarily unreachable
    lock.fail_delete_pin = True
    booking_client.fetch_bookings.return_value = []
    await sync_env["engine"].sync_once(now=now + timedelta(minutes=1))

    # Record marked PENDING_REVOKE
    pin_rec = sync_env["db"].get_pin("book_rev_fail")
    assert pin_rec.status == PinStatus.PENDING_REVOKE

    # Lock comes back online
    lock.fail_delete_pin = False
    res3 = await sync_env["engine"].sync_once(now=now + timedelta(minutes=2))

    assert "book_rev_fail" in res3.provision.deprovisioned
    assert sync_env["db"].get_pin("book_rev_fail").status == PinStatus.REVOKED
    assert sync_env["allocator"].is_available(9) is True


@pytest.mark.asyncio
async def test_opportunistic_telemetry_recording(sync_env):
    """When connecting to lock, battery and lock status are recorded in database."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    lock = sync_env["lock"]
    lock.battery = 76
    lock.lock_status = "UNLOCKED"
    lock.door_status = "OPEN"

    sync_env["booking_client"].fetch_bookings.return_value = [
        RemoteBooking(
            id="book_telem",
            start_time=now + timedelta(minutes=20),
            end_time=now + timedelta(hours=1),
            door_code="998877",
        )
    ]

    await sync_env["engine"].sync_once(now=now)

    status_rec = sync_env["db"].get_lock_status(lock.address)
    assert status_rec is not None
    assert status_rec.battery == 76
    assert status_rec.lock_status == "UNLOCKED"
    assert status_rec.door_status == "OPEN"


@pytest.mark.asyncio
async def test_multi_lock_synchronization(sync_env):
    """Test multi-lock configuration synchronizes PINs across all configured doors."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    lock1 = FakeLockClient(address="AA:BB:CC:DD:EE:01")
    lock2 = FakeLockClient(address="AA:BB:CC:DD:EE:02")

    # Multi-lock provisioner
    multi_provisioner = PinProvisioner(
        db=sync_env["db"],
        allocator=sync_env["allocator"],
        lock_clients=[lock1, lock2],
        lead_time=timedelta(minutes=60),
        grace_period=timedelta(minutes=15),
    )

    multi_engine = DoormanSyncEngine(
        poller=sync_env["poller"],
        provisioner=multi_provisioner,
        store=sync_env["store"],
        db=sync_env["db"],
    )

    sync_env["booking_client"].fetch_bookings.return_value = [
        RemoteBooking(
            id="book_multi",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            door_code="123456",
        )
    ]

    await multi_engine.sync_once(now=now)

    # Both locks got the PIN!
    assert lock1.pins[9] == "123456"
    assert lock2.pins[9] == "123456"

    # Both locks got telemetry recorded
    assert sync_env["db"].get_lock_status("AA:BB:CC:DD:EE:01") is not None
    assert sync_env["db"].get_lock_status("AA:BB:CC:DD:EE:02") is not None


@pytest.mark.asyncio
async def test_multi_door_targeted_sync(sync_env):
    """When lock_ids are configured, each door's reservations are routed to the matching lock."""
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    lock1 = FakeLockClient(address="AA:BB:CC:DD:EE:01", local_name="Hoveddør")
    lock1.lock_id = "1"
    lock2 = FakeLockClient(address="AA:BB:CC:DD:EE:02", local_name="Badstue")
    lock2.lock_id = "2"

    multi_provisioner = PinProvisioner(
        db=sync_env["db"],
        allocator=sync_env["allocator"],
        lock_clients=[lock1, lock2],
        lead_time=timedelta(minutes=60),
        grace_period=timedelta(minutes=15),
    )

    multi_engine = DoormanSyncEngine(
        poller=sync_env["poller"],
        provisioner=multi_provisioner,
        store=sync_env["store"],
        db=sync_env["db"],
        lock_ids=["1", "2"],
    )

    # Mock fetch_bookings based on lock_id parameter
    def mock_fetch(lock_id=None):
        if str(lock_id) == "1":
            return [
                RemoteBooking(
                    id="book_door1",
                    start_time=now + timedelta(minutes=30),
                    end_time=now + timedelta(hours=2),
                    door_code="111111",
                )
            ]
        elif str(lock_id) == "2":
            return [
                RemoteBooking(
                    id="book_door2",
                    start_time=now + timedelta(minutes=30),
                    end_time=now + timedelta(hours=2),
                    door_code="222222",
                )
            ]
        return []

    sync_env["booking_client"].fetch_bookings.side_effect = mock_fetch

    res = await multi_engine.sync_once(now=now)

    assert "book_door1" in res.scheduled
    assert "book_door2" in res.scheduled
    assert len(res.provision.activated) == 2

    # Lock 1 only has door 1's PIN
    assert "111111" in lock1.pins.values()
    assert "222222" not in lock1.pins.values()

    # Lock 2 only has door 2's PIN
    assert "222222" in lock2.pins.values()
    assert "111111" not in lock2.pins.values()


@pytest.mark.asyncio
async def test_sync_offline_mode_stateful_logging(sync_env):
    """Verify that sync-engine operates in offline mode without crashing and tracks network state."""
    engine = sync_env["engine"]
    now = datetime.now(UTC)

    # Put a scheduled reservation in store and schedule with provisioner before network drops
    record = ReservationRecord(
        booking_id="offline_book",
        pin="998877",
        valid_from=now + timedelta(minutes=15),
        valid_to=now + timedelta(hours=2),
        status=ReservationStatus.ACTIVE,
    )
    sync_env["store"].save_reservation(record)
    engine.provisioner.schedule_pin(
        booking_id="offline_book",
        pin="998877",
        valid_from=now + timedelta(minutes=15),
        valid_to=now + timedelta(hours=2),
        lock_id=engine.lock_id,
    )

    # Simulate network outage on booking client
    sync_env["booking_client"].fetch_bookings.side_effect = ConnectionError("Network unreachable")

    # Sync tick 1: Network fails, but local provisioning proceeds
    res1 = await engine.sync_once(now=now)
    assert engine._network_down is True
    assert len(res1.errors) > 0
    # Provisioning still activated the local offline reservation!
    assert "offline_book" in res1.provision.activated

    # Sync tick 2: Still offline, remains in offline mode
    await engine.sync_once(now=now + timedelta(minutes=1))
    assert engine._network_down is True

    # Sync tick 3: Network restored
    sync_env["booking_client"].fetch_bookings.side_effect = None
    sync_env["booking_client"].fetch_bookings.return_value = []
    await engine.sync_once(now=now + timedelta(minutes=2))
    assert engine._network_down is False


@pytest.mark.asyncio
async def test_multi_door_fault_isolation(sync_env):
    """Verify that a failing lock (BLE timeout) does not prevent provisioning to other working locks."""
    now = datetime.now(UTC)

    lock1 = FakeLockClient(address="AA:BB:CC:DD:EE:01", local_name="Festsalen")
    lock1.lock_id = "1"
    lock1.fail_add_pin = True  # Lock 1 is offline / failing

    lock2 = FakeLockClient(address="AA:BB:CC:DD:EE:02", local_name="Peisestua")
    lock2.lock_id = "2"
    lock2.fail_add_pin = False  # Lock 2 is working

    multi_provisioner = PinProvisioner(
        db=sync_env["db"],
        allocator=sync_env["allocator"],
        lock_clients=[lock1, lock2],
        lead_time=timedelta(minutes=60),
        grace_period=timedelta(minutes=15),
    )

    multi_engine = DoormanSyncEngine(
        poller=sync_env["poller"],
        provisioner=multi_provisioner,
        store=sync_env["store"],
        db=sync_env["db"],
        lock_ids=["1", "2"],
    )

    def mock_fetch(lock_id=None):
        if str(lock_id) == "1":
            return [
                RemoteBooking(
                    id="book_fail_door",
                    start_time=now + timedelta(minutes=20),
                    end_time=now + timedelta(hours=2),
                    door_code="111111",
                )
            ]
        elif str(lock_id) == "2":
            return [
                RemoteBooking(
                    id="book_success_door",
                    start_time=now + timedelta(minutes=20),
                    end_time=now + timedelta(hours=2),
                    door_code="222222",
                )
            ]
        return []

    sync_env["booking_client"].fetch_bookings.side_effect = mock_fetch

    res = await multi_engine.sync_once(now=now)

    # Lock 1 failed
    assert any("Failed to program PIN" in err for err in res.errors)
    assert "book_fail_door" not in res.provision.activated

    # Lock 2 succeeded!
    assert "book_success_door" in res.provision.activated
    assert "222222" in lock2.pins.values()
