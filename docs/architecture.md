# System Architecture - Snippen Doorman Service

## Overview

The Snippen Doorman Service manages temporary access codes for Yale Doorman door locks, providing secure integration with the Snippen booking platform.

## System Topology

```
[ Snippen Booking (WordPress) ] <=== HTTPS ===> [ Snippen Doorman Service ] <=== BLE (yalexs-ble) ===> [ Yale Doorman Classic + Access Module ]
```

- **Snippen Booking Platform**: Manages guest bookings and triggers access code generation
- **Snippen Doorman Service**: Central service managing temporary codes, slot allocation, and door lock control
- **Yale Doorman Access Module**: Hardware interface on Yale Doorman Classic communicating over Bluetooth Low Energy (see [yale_ble_protocol.md](yale_ble_protocol.md))

## Design Principles

### Modularity
- Decouple business logic from integration details
- Abstract door lock API behind a provider interface
- Support multiple door lock types (Yale, etc.)

### Security
- Temporary codes are time-limited and revocable
- Complete audit trail of all access events
- Secure communication with door lock module

### Reliability
- Persistent storage of all codes and events
- Synchronization with Snippen booking platform
- Graceful handling of communication failures

## Slot Allocation Strategy

Yale Doorman Classic (V2N) hardware supports 10 keypad slots (`0` through `9`). To guarantee zero conflict with administrative and service credentials configured in the Yale Home app:
- **Slots 0–2 (Yale Home Admin)**: Shielded and never allocated by Snippen Doorman.
- **Slots 9 down to 3 (Snippen Guest Pool)**: Dynamically allocated in descending order (`9`, `8`, `7`, ..., `3`).
- **Recycling & Saturation**: When bookings expire or are revoked, slots are immediately freed and reused. If all 7 guest slots are simultaneously active, `NoSlotsAvailableError` is handled gracefully.

## JIT Provisioning Engine

Access codes can be generated days or weeks in advance for tenants, but are only programmed physically into the lock hardware Just-In-Time (JIT):
1. **Pre-generation**: Reservation stored with status `SCHEDULED` (`slot = None`).
2. **Activation Window**: When `now >= valid_from - lead_time` (default 60 minutes), the provisioner allocates a slot (9..3) and issues `KeyCode_Set` / `KeyCode_Commit` over BLE. Status transitions to `PROVISIONED`.
3. **Grace Period & Deprovisioning**: When `now > valid_to + grace_period` (default 15 minutes), the provisioner issues `KeyCode_Clear` over BLE and frees the slot. Status transitions to `EXPIRED`.
4. **Revocation**: If a reservation is cancelled, `revoke_pin` clears the slot from the lock and sets status to `REVOKED`.

## Data Model

### PIN Reservations Table (`pins`)
- `id`: Integer primary key (autoincrement)
- `booking_id`: Unique external reservation reference
- `slot`: Keypad slot index (3–9 when provisioned, NULL when scheduled/expired/revoked)
- `pin`: 4 to 6 digit numeric credential
- `status`: Lifecycle state (`SCHEDULED`, `PROVISIONED`, `REVOKED`, `EXPIRED`)
- `valid_from`: Start of reservation validity (UTC ISO-8601)
- `valid_to`: End of reservation validity (UTC ISO-8601)
- `created_at`: Creation timestamp (UTC ISO-8601)
- `modified_at`: Last modification timestamp (UTC ISO-8601)

### Access Events
- `code`: Which code was used
- `event_type`: Entry / Exit / Failed
- `timestamp`: When the event occurred
- `door_id`: Which door the event occurred on

## Integration Points

### Snippen Booking API
- Receive booking notifications
- Update access code status
- Report access events

### Yale Doorman Module
- Create temporary codes on lock
- Revoke codes
- Query access events
- Monitor lock status
