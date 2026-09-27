# System Architecture - Snippen Doorman Service

## Overview

The Snippen Doorman Service manages temporary access codes for Yale Doorman door locks, providing secure integration with the Snippen booking platform.

## System Topology

```
[ Snippen Booking (WordPress) ] <=== HTTPS ===> [ Snippen Doorman Service ] <=== API ===> [ Yale Doorman Access Module ]
```

- **Snippen Booking Platform**: Manages guest bookings and triggers access code generation
- **Snippen Doorman Service**: Central service managing temporary codes and door lock control
- **Yale Doorman Access Module**: Hardware interface for managing temporary codes on Yale locks

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

## Data Model

### Temporary Codes
- `code`: Unique temporary access code
- `guest_name`: Name of the guest
- `booking_id`: Reference to Snippen booking
- `expires_at`: Code expiration timestamp
- `revoked_at`: Revocation timestamp (if applicable)
- `created_at`: When the code was created
- `modified_at`: Last modification timestamp

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
