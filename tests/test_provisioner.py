"""Unit and integration tests for PinProvisioner and JIT scheduling engine."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from snippen_doorman.allocator import SlotAllocator
from snippen_doorman.db import Database, PinStatus
from snippen_doorman.provisioner import (
    PinProvisioner,
    run_provisioning_scheduler,
)


@pytest.fixture
def mock_lock_client() -> AsyncMock:
    """Provide a mock Yale lock BLE client."""
    client = AsyncMock()
    client.add_pin = AsyncMock(return_value=None)
    client.delete_pin = AsyncMock(return_value=True)
    return client


@pytest.fixture
def test_setup(mock_lock_client: AsyncMock):
    """Fixture creating Database, SlotAllocator, and PinProvisioner."""
    db = Database(":memory:")
    allocator = SlotAllocator(min_slot=3, max_slot=9)
    provisioner = PinProvisioner(
        db=db,
        allocator=allocator,
        lock_client=mock_lock_client,
        lead_time=timedelta(minutes=60),
        grace_period=timedelta(minutes=15),
    )
    yield db, allocator, provisioner, mock_lock_client
    db.close()


@pytest.mark.asyncio
async def test_schedule_and_jit_activation(test_setup) -> None:
    """Test JIT activation of PIN within lead-time window."""
    db, allocator, provisioner, mock_client = test_setup

    base_time = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    valid_from = base_time + timedelta(hours=2)  # 14:00
    valid_to = base_time + timedelta(hours=4)  # 16:00

    # 1. Schedule PIN at 12:00 (booking starts at 14:00, lead time is 60 min -> starts 13:00)
    rec = provisioner.schedule_pin(
        booking_id="booking_jit_1",
        pin="654321",
        valid_from=valid_from,
        valid_to=valid_to,
    )
    assert rec.status == PinStatus.SCHEDULED
    assert rec.slot is None
    assert mock_client.add_pin.call_count == 0

    # 2. Tick at 12:30 (outside lead-time window: 14:00 - 60min = 13:00)
    tick_1230 = await provisioner.tick(now=base_time + timedelta(minutes=30))
    assert tick_1230.activated == []
    assert mock_client.add_pin.call_count == 0

    # 3. Tick at 13:05 (inside lead-time window)
    tick_1305 = await provisioner.tick(now=base_time + timedelta(minutes=65))
    assert tick_1305.activated == ["booking_jit_1"]
    assert mock_client.add_pin.call_count == 1

    # Verify assigned slot is 9 (descending order)
    mock_client.add_pin.assert_called_once_with(
        pin="654321",
        slot=9,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    persisted = db.get_pin("booking_jit_1")
    assert persisted is not None
    assert persisted.status == PinStatus.PROVISIONED
    assert persisted.slot == 9
    assert allocator.allocated_slots()[9] == "booking_jit_1"


@pytest.mark.asyncio
async def test_jit_expiration_and_deprovisioning(test_setup) -> None:
    """Test deprovisioning and slot freeing when booking expires plus grace period."""
    db, allocator, provisioner, mock_client = test_setup

    base_time = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    valid_from = base_time + timedelta(hours=1)  # 13:00
    valid_to = base_time + timedelta(hours=2)  # 14:00 (grace ends 14:15)

    provisioner.schedule_pin("b_expire", "123456", valid_from, valid_to)

    # Activate at 12:30
    await provisioner.tick(now=base_time + timedelta(minutes=30))
    assert db.get_pin("b_expire").status == PinStatus.PROVISIONED
    assert allocator.is_available(9) is False

    # Tick at 14:10 (within grace period: valid_to 14:00 + 15 min = 14:15)
    tick_1410 = await provisioner.tick(now=base_time + timedelta(hours=2, minutes=10))
    assert tick_1410.deprovisioned == []
    assert mock_client.delete_pin.call_count == 0

    # Tick at 14:16 (past grace period)
    tick_1416 = await provisioner.tick(now=base_time + timedelta(hours=2, minutes=16))
    assert tick_1416.deprovisioned == ["b_expire"]
    assert mock_client.delete_pin.call_count == 1
    mock_client.delete_pin.assert_called_once_with(slot=9, pin="123456")

    # Record updated and slot released
    rec = db.get_pin("b_expire")
    assert rec.status == PinStatus.EXPIRED
    assert rec.slot is None
    assert allocator.is_available(9) is True


@pytest.mark.asyncio
async def test_slot_saturation_and_queue_handling(test_setup) -> None:
    """Test handling when more bookings exist than available slots (slots 9 to 3 = 7 slots)."""
    db, _allocator, provisioner, _mock_client = test_setup

    base_time = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    valid_from = base_time + timedelta(hours=1)
    valid_to = base_time + timedelta(hours=3)

    # Schedule 8 bookings concurrently
    for i in range(8):
        provisioner.schedule_pin(f"booking_{i}", f"10000{i}", valid_from, valid_to)

    # Tick inside lead-time window
    res = await provisioner.tick(now=base_time + timedelta(minutes=30))

    # Exactly 7 bookings should be activated in descending order (9 down to 3)
    assert len(res.activated) == 7
    assert len(res.errors) == 1
    assert "No slots available" in res.errors[0]

    # Verify slots 9 down to 3 were used
    for i in range(7):
        rec = db.get_pin(f"booking_{i}")
        assert rec.status == PinStatus.PROVISIONED
        assert rec.slot == 9 - i

    # The 8th booking remains SCHEDULED
    b7 = db.get_pin("booking_7")
    assert b7.status == PinStatus.SCHEDULED
    assert b7.slot is None

    # Now expire booking_0 (in slot 9)
    await provisioner.tick(now=valid_to + timedelta(minutes=20))
    assert db.get_pin("booking_0").status == PinStatus.EXPIRED

    # Next tick within window should provision booking_7 into freed slot 9
    b7.valid_to = valid_to + timedelta(hours=2)
    db.update_pin(b7)

    res_retry = await provisioner.tick(now=valid_to + timedelta(minutes=21))
    assert res_retry.activated == ["booking_7"]
    assert db.get_pin("booking_7").slot == 9


@pytest.mark.asyncio
async def test_revoke_pin(test_setup) -> None:
    """Test manual revocation of both scheduled and provisioned PINs."""
    db, allocator, provisioner, mock_client = test_setup

    base_time = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    valid_from = base_time + timedelta(hours=1)
    valid_to = base_time + timedelta(hours=2)

    # 1. Revoke while SCHEDULED
    provisioner.schedule_pin("b_sched_rev", "111111", valid_from, valid_to)
    rev_sched = await provisioner.revoke_pin("b_sched_rev")
    assert rev_sched.status == PinStatus.REVOKED
    assert mock_client.delete_pin.call_count == 0

    # 2. Revoke while PROVISIONED
    provisioner.schedule_pin("b_prov_rev", "222222", valid_from, valid_to)
    await provisioner.tick(now=base_time + timedelta(minutes=30))
    assert db.get_pin("b_prov_rev").status == PinStatus.PROVISIONED
    assigned_slot = db.get_pin("b_prov_rev").slot

    rev_prov = await provisioner.revoke_pin("b_prov_rev")
    assert rev_prov.status == PinStatus.REVOKED
    assert rev_prov.slot is None
    assert mock_client.delete_pin.call_count == 1
    mock_client.delete_pin.assert_called_with(slot=assigned_slot, pin="222222")
    assert allocator.is_available(assigned_slot) is True


@pytest.mark.asyncio
async def test_allocator_rehydration_on_startup() -> None:
    """Test that restarting provisioner restores occupied slots from database."""
    db = Database(":memory:")
    now = datetime.now(UTC)

    # Create pre-existing provisioned record
    db.create_pin(
        booking_id="persisted_b",
        pin="999999",
        valid_from=now,
        valid_to=now + timedelta(hours=1),
        status=PinStatus.PROVISIONED,
        slot=8,
    )

    # Initialize brand new allocator and provisioner
    allocator = SlotAllocator()
    assert allocator.is_available(8) is True  # initially empty

    _ = PinProvisioner(db=db, allocator=allocator)
    # After sync on init, slot 8 is reserved
    assert allocator.is_available(8) is False
    assert allocator.allocated_slots()[8] == "persisted_b"
    # Allocating new slot gets 9
    assert allocator.allocate("new_b") == 9
    db.close()


@pytest.mark.asyncio
async def test_scheduler_background_loop(test_setup) -> None:
    """Test run_provisioning_scheduler execution and graceful stop."""
    _, _, provisioner, _ = test_setup

    stop_event = asyncio.Event()

    task = asyncio.create_task(
        run_provisioning_scheduler(
            provisioner=provisioner,
            interval_seconds=0.05,
            stop_event=stop_event,
        )
    )

    await asyncio.sleep(0.12)
    stop_event.set()
    await task
    assert task.done()
