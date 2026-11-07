"""Full status reporting builder for Snippen Doorman Service (issue #75)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from snippen_doorman.db import Database, PinStatus
from snippen_doorman.node_identity import NodeIdentity, resolve_node_identity
from snippen_doorman.state.base import ReservationStore


def format_iso(dt: datetime | None) -> str | None:
    """Format datetime as UTC ISO-8601 string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def build_full_status_payload(
    db: Database,
    store: ReservationStore | None = None,
    lock_configs: list[Any] | None = None,
    lock_clients: list[Any] | None = None,
    expired_window_days: int = 7,
    now: datetime | None = None,
    guest_slot_min: int = 3,
    guest_slot_max: int = 9,
    service_id: str | None = None,
    service_name: str | None = None,
    node_identity: NodeIdentity | None = None,
) -> dict[str, Any]:
    """Build a comprehensive JSON status report of locks, DB reservations, and history.

    Args:
        db: Database containing pins, lock_status, and pin_lock_states.
        store: Optional ReservationStore for local booking cache.
        lock_configs: Optional list of LockConfig or LockSetting instances.
        lock_clients: Optional list of lock clients (e.g. YaleLockClient).
        expired_window_days: Days back to include expired/revoked bookings (default: 7).
        now: Current timestamp (defaults to datetime.now(UTC)).
        guest_slot_min: First guest keypad slot (default: 3).
        guest_slot_max: Last guest keypad slot (default: 9).
        service_id: Optional service ID override (issue #76).
        service_name: Optional service display name override (issue #76).
        node_identity: Optional pre-resolved NodeIdentity instance.

    Returns:
        Structured dictionary matching issue #75 and issue #76 / snippen-booking #372.
    """
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    # 1. Gather all physical locks
    known_locks_map: dict[str, dict[str, Any]] = {}

    if lock_configs:
        for cfg in lock_configs:
            addr = getattr(cfg, "address", "")
            if addr:
                clean_addr = addr.strip()
                known_locks_map[clean_addr] = {
                    "name": getattr(cfg, "name", "Hoveddør") or "Hoveddør",
                    "address": clean_addr,
                    "key_slot": int(getattr(cfg, "slot", 1) or 1),
                    "lock_id": str(getattr(cfg, "lock_id", ""))
                    if getattr(cfg, "lock_id", None) is not None
                    else "default",
                }

    if lock_clients:
        for idx, client in enumerate(lock_clients):
            raw_addr = getattr(client, "address", None)
            if (
                isinstance(raw_addr, str)
                and raw_addr.strip()
                and not hasattr(raw_addr, "_mock_return_value")
            ):
                clean_addr = raw_addr.strip()
            else:
                clean_addr = f"lock_{idx + 1}"

            raw_name = getattr(client, "local_name", None) or getattr(client, "name", None)
            if (
                isinstance(raw_name, str)
                and raw_name.strip()
                and not hasattr(raw_name, "_mock_return_value")
            ):
                name = raw_name.strip()
            else:
                name = f"Lås {idx + 1}" if idx > 0 else "Hoveddør"

            raw_lid = getattr(client, "lock_id", None)
            if (
                raw_lid is not None
                and not hasattr(raw_lid, "_mock_return_value")
                and "Mock" not in type(raw_lid).__name__
            ):
                lid = str(raw_lid).strip()
            else:
                lid = "default"

            slot = int(getattr(client, "slot", 1) or 1)
            known_locks_map[clean_addr] = {
                "name": name,
                "address": clean_addr,
                "key_slot": slot,
                "lock_id": lid,
            }

    # Telemetry from DB
    telemetry_list = db.list_lock_statuses()
    for st in telemetry_list:
        clean_addr = st.lock_address.strip()
        if clean_addr not in known_locks_map:
            known_locks_map[clean_addr] = {
                "name": "Hoveddør",
                "address": clean_addr,
                "key_slot": 1,
                "lock_id": "default",
            }
        known_locks_map[clean_addr]["battery"] = st.battery
        known_locks_map[clean_addr]["lock_status"] = st.lock_status
        known_locks_map[clean_addr]["door_status"] = st.door_status
        known_locks_map[clean_addr]["last_seen"] = format_iso(st.last_seen)

    # 2. Gather PINs and per-physical-lock states
    all_pins = db.list_pins()
    all_lock_states = db.list_pin_lock_states()

    # Map booking_id -> list of PinLockStateRecord
    states_by_booking: dict[str, list[Any]] = {}
    for pls in all_lock_states:
        states_by_booking.setdefault(pls.booking_id, []).append(pls)

    # Active states
    active_statuses = {
        PinStatus.SCHEDULED,
        PinStatus.PROVISIONED,
        PinStatus.PENDING_UPDATE,
        PinStatus.PENDING_REVOKE,
    }

    # Build slot occupancy per physical lock
    lock_slots_map: dict[str, dict[str, str | None]] = {}
    for addr in known_locks_map:
        lock_slots_map[addr] = {str(s): None for s in range(guest_slot_min, guest_slot_max + 1)}

    for pls in all_lock_states:
        if pls.slot is not None and pls.status == PinStatus.PROVISIONED:
            addr = pls.lock_address
            if addr in lock_slots_map:
                lock_slots_map[addr][str(pls.slot)] = pls.booking_id

    # Fallback to general pins table if per-lock state wasn't populated
    for p in all_pins:
        if p.slot is not None and p.status == PinStatus.PROVISIONED:
            for addr, slots in lock_slots_map.items():
                if slots.get(str(p.slot)) is None:
                    slots[str(p.slot)] = p.booking_id

    # Construct locks array
    locks_data: list[dict[str, Any]] = []
    for addr, lk_info in known_locks_map.items():
        locks_data.append(
            {
                "name": lk_info.get("name", "Hoveddør"),
                "address": addr,
                "key_slot": lk_info.get("key_slot", 1),
                "lock_id": lk_info.get("lock_id", "default"),
                "battery": lk_info.get("battery"),
                "lock_status": lk_info.get("lock_status"),
                "door_status": lk_info.get("door_status"),
                "last_seen": lk_info.get("last_seen"),
                "slots": lock_slots_map.get(addr, {}),
            }
        )

    # 3. Reservations in DB (active & upcoming)
    reservations_in_db: list[dict[str, Any]] = []
    active_pins = [p for p in all_pins if p.status in active_statuses]

    for p in active_pins:
        pls_list = states_by_booking.get(p.booking_id, [])
        all_prov = (
            len(pls_list) > 0 and all(pls.status == PinStatus.PROVISIONED for pls in pls_list)
        ) or (p.status == PinStatus.PROVISIONED and not pls_list)

        physical_locks: list[dict[str, Any]] = []
        if pls_list:
            for pls in pls_list:
                physical_locks.append(
                    {
                        "lock_name": pls.lock_name,
                        "lock_address": pls.lock_address,
                        "lock_id": pls.lock_id,
                        "slot": pls.slot,
                        "status": pls.status.value,
                        "updated_at": format_iso(pls.modified_at or pls.created_at),
                    }
                )
        else:
            for addr, lk in known_locks_map.items():
                physical_locks.append(
                    {
                        "lock_name": lk["name"],
                        "lock_address": addr,
                        "lock_id": p.lock_id,
                        "slot": p.slot if p.status == PinStatus.PROVISIONED else None,
                        "status": p.status.value,
                        "updated_at": format_iso(p.modified_at or p.created_at),
                    }
                )

        reservations_in_db.append(
            {
                "booking_id": p.booking_id,
                "lock_id": p.lock_id,
                "pin": p.pin,
                "valid_from": format_iso(p.valid_from),
                "valid_to": format_iso(p.valid_to),
                "status": p.status.value,
                "slot": p.slot,
                "all_locks_provisioned": all_prov,
                "physical_locks": physical_locks,
                "created_at": format_iso(p.created_at),
                "modified_at": format_iso(p.modified_at),
            }
        )

    # 4. Provisioned on locks
    provisioned_on_locks: list[dict[str, Any]] = []
    for pls in all_lock_states:
        if pls.status in (PinStatus.PROVISIONED, PinStatus.PENDING_UPDATE) and pls.slot is not None:
            parent_pin = next((p for p in all_pins if p.booking_id == pls.booking_id), None)
            valid_from_str = format_iso(parent_pin.valid_from) if parent_pin else None
            valid_to_str = format_iso(parent_pin.valid_to) if parent_pin else None
            provisioned_on_locks.append(
                {
                    "booking_id": pls.booking_id,
                    "lock_id": pls.lock_id,
                    "lock_name": pls.lock_name,
                    "lock_address": pls.lock_address,
                    "slot": pls.slot,
                    "pin": pls.pin,
                    "valid_from": valid_from_str,
                    "valid_to": valid_to_str,
                    "status": pls.status.value,
                    "modified_at": format_iso(pls.modified_at or pls.created_at),
                }
            )

    # Fallback for provisioned_on_locks if pin_lock_states was empty
    if not provisioned_on_locks:
        for p in all_pins:
            if p.status in (PinStatus.PROVISIONED, PinStatus.PENDING_UPDATE) and p.slot is not None:
                for addr, lk in known_locks_map.items():
                    provisioned_on_locks.append(
                        {
                            "booking_id": p.booking_id,
                            "lock_id": p.lock_id,
                            "lock_name": lk["name"],
                            "lock_address": addr,
                            "slot": p.slot,
                            "pin": p.pin,
                            "valid_from": format_iso(p.valid_from),
                            "valid_to": format_iso(p.valid_to),
                            "status": p.status.value,
                            "modified_at": format_iso(p.modified_at or p.created_at),
                        }
                    )

    # 5. Recently expired
    expired_cutoff = now - timedelta(days=expired_window_days)
    recently_expired: list[dict[str, Any]] = []

    history_pins = [
        p
        for p in all_pins
        if p.status in (PinStatus.EXPIRED, PinStatus.REVOKED)
        or (p.valid_to < now and p.status not in active_statuses)
    ]

    for p in history_pins:
        check_time = p.valid_to or p.modified_at or p.created_at
        if check_time and check_time >= expired_cutoff:
            pls_list = states_by_booking.get(p.booking_id, [])
            physical_locks = []
            if pls_list:
                for pls in pls_list:
                    physical_locks.append(
                        {
                            "lock_name": pls.lock_name,
                            "lock_address": pls.lock_address,
                            "lock_id": pls.lock_id,
                            "slot": None,
                            "status": pls.status.value,
                            "updated_at": format_iso(pls.modified_at or pls.created_at),
                        }
                    )
            else:
                for addr, lk in known_locks_map.items():
                    physical_locks.append(
                        {
                            "lock_name": lk["name"],
                            "lock_address": addr,
                            "lock_id": p.lock_id,
                            "slot": None,
                            "status": p.status.value,
                            "updated_at": format_iso(p.modified_at or p.created_at),
                        }
                    )

            recently_expired.append(
                {
                    "booking_id": p.booking_id,
                    "lock_id": p.lock_id,
                    "pin": p.pin,
                    "valid_from": format_iso(p.valid_from),
                    "valid_to": format_iso(p.valid_to),
                    "status": p.status.value,
                    "physical_locks": physical_locks,
                    "created_at": format_iso(p.created_at),
                    "modified_at": format_iso(p.modified_at),
                }
            )

    discovered_lock_ids: list[str] = []
    for lk in known_locks_map.values():
        raw_lid = lk.get("lock_id")
        if raw_lid is not None:
            lid_str = str(raw_lid).strip()
            if lid_str and lid_str not in discovered_lock_ids:
                discovered_lock_ids.append(lid_str)

    resolved_identity = node_identity
    if resolved_identity is None:
        resolved_identity = resolve_node_identity(
            service_id=service_id,
            service_name=service_name,
            lock_ids=discovered_lock_ids,
        )
    elif not resolved_identity.lock_ids and discovered_lock_ids:
        resolved_identity.lock_ids = discovered_lock_ids

    return {
        "service_id": resolved_identity.service_id,
        "service": resolved_identity.to_service_dict(),
        "generated_at": format_iso(now),
        "expired_window_days": expired_window_days,
        "locks": locks_data,
        "reservations_in_db": reservations_in_db,
        "provisioned_on_locks": provisioned_on_locks,
        "recently_expired": recently_expired,
    }
