"""Snippen Doorman Service - Access control for Yale Doorman locks."""

from __future__ import annotations

from snippen_doorman.allocator import NoSlotsAvailableError, SlotAllocator
from snippen_doorman.db import Database, PinRecord, PinStatus
from snippen_doorman.provisioner import (
    PinProvisioner,
    ProvisionTickResult,
    run_provisioning_scheduler,
)

__version__ = "0.6.0"

__all__ = [
    "Database",
    "NoSlotsAvailableError",
    "PinProvisioner",
    "PinRecord",
    "PinStatus",
    "ProvisionTickResult",
    "SlotAllocator",
    "__version__",
    "run_provisioning_scheduler",
]
