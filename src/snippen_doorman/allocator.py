"""Keypad slot allocator for temporary guest PIN codes on Yale Doorman locks."""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_GUEST_SLOT_MIN: Final[int] = 3
DEFAULT_GUEST_SLOT_MAX: Final[int] = 9


class NoSlotsAvailableError(Exception):
    """Raised when all available guest slots in the configured range are occupied."""


class SlotAllocator:
    """Manages keypad slot allocation for temporary guest PIN codes.

    Allocates guest slots in descending order (e.g. 9 down to 3) to protect
    low-indexed slots (0 to 2) reserved for administrative and service codes
    managed via Yale Home.
    """

    def __init__(
        self,
        min_slot: int = DEFAULT_GUEST_SLOT_MIN,
        max_slot: int = DEFAULT_GUEST_SLOT_MAX,
    ) -> None:
        """Initialize slot allocator within specified guest slot boundaries.

        Args:
            min_slot: Minimum guest slot number (must be >= 3).
            max_slot: Maximum guest slot number (must be <= 9).
        """
        if min_slot < 0 or max_slot < 0:
            raise ValueError("Slot values must be non-negative.")
        if min_slot > max_slot:
            raise ValueError(f"min_slot ({min_slot}) cannot be greater than max_slot ({max_slot}).")
        if min_slot < 3:
            raise ValueError(
                f"min_slot ({min_slot}) cannot be lower than 3 (slots 0-2 are reserved for Yale Home admin)."
            )
        if max_slot > 9:
            raise ValueError(
                f"max_slot ({max_slot}) cannot exceed 9 (Yale Doorman V2N capacity is 10 slots: 0-9)."
            )

        self.min_slot = min_slot
        self.max_slot = max_slot
        self._allocated: dict[int, str] = {}

    def allocate(self, booking_id: str) -> int:
        """Allocate the next available slot in descending order (max_slot down to min_slot).

        Args:
            booking_id: Unique booking identifier associated with this slot.

        Returns:
            The allocated slot number.

        Raises:
            ValueError: If booking_id is empty.
            NoSlotsAvailableError: If no guest slots are currently available.
        """
        if not booking_id:
            raise ValueError("booking_id must not be empty.")

        for slot in range(self.max_slot, self.min_slot - 1, -1):
            if slot not in self._allocated:
                self._allocated[slot] = booking_id
                logger.info("Allocated slot %d for booking '%s'", slot, booking_id)
                return slot

        raise NoSlotsAvailableError(
            f"No guest slots available in range {self.min_slot}-{self.max_slot}."
        )

    def release(self, slot: int) -> bool:
        """Release a previously allocated slot, making it available for reuse.

        Args:
            slot: The slot number to release.

        Returns:
            True if the slot was allocated and is now freed, False otherwise.
        """
        if slot in self._allocated:
            booking_id = self._allocated.pop(slot)
            logger.info("Released slot %d (previously booking '%s')", slot, booking_id)
            return True
        return False

    def release_booking(self, booking_id: str) -> int | None:
        """Release any slot allocated to the given booking identifier.

        Args:
            booking_id: The booking identifier to release.

        Returns:
            The slot number that was freed, or None if the booking had no slot allocated.
        """
        for slot, b_id in list(self._allocated.items()):
            if b_id == booking_id:
                del self._allocated[slot]
                logger.info("Released slot %d for booking '%s'", slot, booking_id)
                return slot
        return None

    def reserve(self, slot: int, booking_id: str) -> None:
        """Explicitly reserve a specific slot (e.g. when restoring state from database).

        Args:
            slot: The slot number to reserve.
            booking_id: The booking identifier occupying this slot.

        Raises:
            ValueError: If slot is outside guest range or already allocated to another booking.
        """
        if not (self.min_slot <= slot <= self.max_slot):
            raise ValueError(f"Slot {slot} is outside guest range {self.min_slot}-{self.max_slot}.")
        if not booking_id:
            raise ValueError("booking_id must not be empty.")
        if slot in self._allocated and self._allocated[slot] != booking_id:
            raise ValueError(
                f"Slot {slot} is already allocated to booking '{self._allocated[slot]}'."
            )
        self._allocated[slot] = booking_id

    def is_available(self, slot: int) -> bool:
        """Check if a specific slot is valid and currently free."""
        return self.min_slot <= slot <= self.max_slot and slot not in self._allocated

    def available_slots(self) -> list[int]:
        """Return a list of available slots in descending order."""
        return [
            slot
            for slot in range(self.max_slot, self.min_slot - 1, -1)
            if slot not in self._allocated
        ]

    def allocated_slots(self) -> dict[int, str]:
        """Return a copy of the currently allocated slots mapping {slot: booking_id}."""
        return dict(self._allocated)

    @property
    def capacity(self) -> int:
        """Total number of slots managed by this allocator."""
        return self.max_slot - self.min_slot + 1

    @property
    def free_count(self) -> int:
        """Number of currently unallocated slots."""
        return self.capacity - len(self._allocated)
