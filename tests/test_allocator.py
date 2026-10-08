"""Unit tests for keypad SlotAllocator."""

import pytest

from snippen_doorman.allocator import (
    DEFAULT_GUEST_SLOT_MAX,
    DEFAULT_GUEST_SLOT_MIN,
    NoSlotsAvailableError,
    SlotAllocator,
)


def test_default_initialization() -> None:
    """Test default slot allocator boundaries and capacity."""
    allocator = SlotAllocator()
    assert allocator.min_slot == DEFAULT_GUEST_SLOT_MIN
    assert allocator.max_slot == DEFAULT_GUEST_SLOT_MAX
    assert allocator.capacity == 7
    assert allocator.free_count == 7
    assert allocator.available_slots() == [9, 8, 7, 6, 5, 4, 3]


def test_invalid_slot_boundaries() -> None:
    """Test validation protecting admin slots 0-2 and hardware maximum 9."""
    # Attempting to allocate admin slots 0, 1, or 2 must fail
    with pytest.raises(ValueError, match="cannot be lower than 3"):
        SlotAllocator(min_slot=2, max_slot=9)

    with pytest.raises(ValueError, match="cannot be lower than 3"):
        SlotAllocator(min_slot=0, max_slot=9)

    # Attempting to allocate beyond hardware slot 9 must fail
    with pytest.raises(ValueError, match="cannot exceed 9"):
        SlotAllocator(min_slot=3, max_slot=10)

    # min_slot > max_slot
    with pytest.raises(ValueError, match="cannot be greater than max_slot"):
        SlotAllocator(min_slot=8, max_slot=5)

    # Negative slot values
    with pytest.raises(ValueError, match="non-negative"):
        SlotAllocator(min_slot=-1, max_slot=5)


def test_descending_allocation_order() -> None:
    """Test that slots are allocated in strictly descending order from 9 down to 3."""
    allocator = SlotAllocator()
    expected_order = [9, 8, 7, 6, 5, 4, 3]

    allocated = []
    for i in range(7):
        slot = allocator.allocate(f"booking_{i}")
        allocated.append(slot)

    assert allocated == expected_order
    assert allocator.free_count == 0
    assert allocator.available_slots() == []


def test_slot_saturation_and_error() -> None:
    """Test NoSlotsAvailableError when all guest slots are occupied."""
    allocator = SlotAllocator()
    for i in range(7):
        allocator.allocate(f"booking_{i}")

    with pytest.raises(NoSlotsAvailableError, match="No guest slots available"):
        allocator.allocate("overflow_booking")


def test_release_and_reuse() -> None:
    """Test releasing slots and subsequent reuse in descending order."""
    allocator = SlotAllocator()
    s9 = allocator.allocate("b1")  # slot 9
    s8 = allocator.allocate("b2")  # slot 8
    s7 = allocator.allocate("b3")  # slot 7

    assert (s9, s8, s7) == (9, 8, 7)

    # Release slot 8
    released = allocator.release(8)
    assert released is True
    assert allocator.is_available(8) is True

    # Releasing an unallocated slot returns False
    assert allocator.release(8) is False

    # Next allocation should pick the highest available slot (8, not 6)
    next_slot = allocator.allocate("b4")
    assert next_slot == 8

    # Now release slot 9
    allocator.release(9)
    # Next allocation should pick 9
    assert allocator.allocate("b5") == 9


def test_release_booking() -> None:
    """Test releasing slots by booking identifier."""
    allocator = SlotAllocator()
    allocator.allocate("booking_abc")
    allocator.allocate("booking_def")

    freed = allocator.release_booking("booking_abc")
    assert freed == 9
    assert allocator.is_available(9) is True

    # Unknown booking returns None
    assert allocator.release_booking("unknown") is None


def test_reserve_and_conflict() -> None:
    """Test explicit reservation for database hydration."""
    allocator = SlotAllocator()

    # Valid reservation
    allocator.reserve(7, "restored_booking")
    assert allocator.is_available(7) is False
    assert allocator.allocated_slots()[7] == "restored_booking"

    # Reserving same slot for same booking is idempotent
    allocator.reserve(7, "restored_booking")

    # Reserving already allocated slot for different booking raises ValueError
    with pytest.raises(ValueError, match="already allocated"):
        allocator.reserve(7, "conflicting_booking")

    # Reserving slot out of range
    with pytest.raises(ValueError, match="outside guest range"):
        allocator.reserve(2, "admin_slot")
    with pytest.raises(ValueError, match="outside guest range"):
        allocator.reserve(10, "high_slot")


def test_empty_booking_id_validation() -> None:
    """Test that empty booking_id is rejected."""
    allocator = SlotAllocator()
    with pytest.raises(ValueError, match="must not be empty"):
        allocator.allocate("")
    with pytest.raises(ValueError, match="must not be empty"):
        allocator.reserve(5, "")
