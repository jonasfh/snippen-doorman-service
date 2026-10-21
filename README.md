# Snippen Doorman Service (`snippen-doorman-service`)

A Python service for managing temporary access codes and administrative control of Yale Doorman door locks with integrated access module.

---

## Purpose

`snippen-doorman-service` provides a secure, centralized system for:

- **Temporary Code Management**: Generate, schedule, and revoke time-limited access codes for guests
- **Door Lock Integration**: Direct communication with Yale Doorman locks via the access module
- **Access Logging**: Complete audit trail of all access events and code usage
- **Synchronization**: Real-time sync with the Snippen booking platform for automated guest access

---

## Documentation

- 📚 **[Documentation Overview](docs/README.md)**: Index of all documentation resources.
- 🚀 **[Production Roadmap](docs/production_roadmap.md)**: Veikart og implementeringsplan for produksjonssetting på Raspberry Pi.
- 📐 **[System Architecture & Design](docs/architecture.md)**: High-level architectural design, system boundaries, and design principles.
- 📡 **[Yale Doorman BLE Protocol](docs/yale_ble_protocol.md)**: BLE discovery, authentication, session establishment, and status inspection findings.
- 🔑 **[Yale Offline Key Extraction](docs/yale_offline_key_extraction.md)**: Extracting offline BLE keys and setting up dedicated admin account.
- 🛠️ **[Developer Guide](DEV_README.md)**: Setup instructions, Dev Container configuration, testing, and linting.
- 🤖 **[Agent Guidelines](AGENTS.md)**: Project workflows and conventions for automated agents.

---

## Configuration

The doorman service can be configured via CLI flags or environment variables:

| Setting | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| Service Name | `SNIPPEN_DOORMAN_SERVICE_NAME` | `snippen-doorman-service` | Name of the service instance |
| Log Level | `SNIPPEN_DOORMAN_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| Database Path | `SNIPPEN_DOORMAN_DATABASE_PATH` | `data/doorman.db` | Path to SQLite database file (or `:memory:`) |
| Door Lock Module URL | `SNIPPEN_DOORMAN_MODULE_URL` | *(None)* | URL to the Yale Doorman access module |
| Door Lock Module Token | `SNIPPEN_DOORMAN_MODULE_TOKEN` | *(None)* | Authentication token for the access module |
| Snippen API URL | `SNIPPEN_DOORMAN_API_URL` | *(None)* | Snippen WordPress REST API base URL |
| Snippen API Token | `SNIPPEN_DOORMAN_API_TOKEN` | *(None)* | Shared Bearer/API token for Snippen authentication |
| Sync Interval | `SNIPPEN_DOORMAN_SYNC_INTERVAL` | `5.0` | Synchronization interval in seconds |
| Sync Timeout | `SNIPPEN_DOORMAN_SYNC_TIMEOUT` | `10.0` | HTTP request timeout in seconds |
| Sync Enabled | `SNIPPEN_DOORMAN_SYNC_ENABLED` | `true` | Enable/disable automatic Snippen synchronization |
| Remote Lock ID | `SNIPPEN_DOORMAN_LOCK_ID` | *(None)* | Primary lock ID in WordPress Booking API (spec #47) |
| Multi-Lock Config | `SNIPPEN_DOORMAN_LOCKS` | *(None)* | Multi-door configuration string or JSON array with lock IDs |

---

## Quick Start (Development)

### BLE Discovery and Lock Operations

Discover Yale Doorman locks and access modules in range:

```bash
# Scan for Yale BLE devices (10 seconds)
snippen-doorman discover --timeout 10
```

Read lock status or operate the lock:

```bash
# Query lock, door, and battery status
snippen-doorman status --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1

# Send lock / unlock command
snippen-doorman lock   --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1
snippen-doorman unlock --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1
```

### Local PIN Code Management over BLE

Manage keypad access codes directly over Bluetooth LE without cloud or Wi-Fi bridge:

```bash
# Add a permanent PIN code to keypad slot 3 (address and key read from .env if present)
snippen-doorman pin add --pin "123456" --slot 3

# Add a temporary PIN code with ISO validity period
snippen-doorman pin add --pin "654321" --slot 4 --from "2026-10-08T15:00:00" --to "2026-10-08T18:00:00" --name "Guest"

# Delete a PIN code from keypad slot 3
snippen-doorman pin delete --slot 3

# List configured PIN codes on the lock
snippen-doorman pin list --max-slots 10
```

### Hardware RTC Clock Synchronization

Synchronize the internal Real-Time Clock (RTC) on the Yale Access Module directly over BLE (`CMD_SET_RTC` opcode `0x10`):

```bash
# Synchronize internal lock clock to host system time (UTC)
snippen-doorman rtc sync

# Synchronize internal lock clock to a specific timestamp
snippen-doorman rtc sync --time "2026-10-09T14:30:00"
```

### Slot Allocation & JIT PIN Provisioning

To avoid conflicts with administrative credentials in the official Yale Home app (which populates slots 0 to 2), `snippen-doorman-service` shields slots 0–2 and allocates guest slots strictly in descending order (slots 9 down to 3). Temporary codes are scheduled in SQLite and provisioned Just-In-Time (JIT) over BLE prior to booking start:

```bash
# Pre-schedule a booking PIN (persisted in SQLite, ready for JIT lock programming)
snippen-doorman schedule add --booking-id "res_123" --pin "123456" --from "2026-10-08T14:00:00" --to "2026-10-08T18:00:00"

# List scheduled, provisioned, expired, or revoked PIN reservations
snippen-doorman schedule list

# Run a reconciliation cycle (allocates slots and programs codes entering window, cleans up expired)
snippen-doorman schedule sync

# Revoke a booking immediately (removes from lock if currently provisioned and frees slot)
snippen-doorman schedule revoke --booking-id "res_123"

# Run the JIT provisioning scheduler daemon
snippen-doorman schedule run --interval 60
```

### Extracting Offline Keys

Extract offline keys from a Home Assistant debug log (see [docs/yale_offline_key_extraction.md](docs/yale_offline_key_extraction.md)):

```bash
# Parse log file and display keys
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log

# Automatically populate or update .env credentials
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log --output-env .env
```

### Start Service & End-to-End Synchronization

`snippen-doorman service run` runs the full end-to-end synchronization engine (`DoormanSyncEngine`) combining:
1. `BookingPoller`: Polling `snippen-booking` REST API, generating 6-digit PIN codes if none exist, and reporting PINs back via PATCH.
2. `DoormanSyncEngine`: Change detection and battery-saving sleep logic (#29). Unchanged reservations produce zero BLE communication.
3. `PinProvisioner` & `SlotAllocator`: Just-In-Time (JIT) slot management (guest slots 9 down to 3) within configurable lead time (`--lead-time`, default 60m).
4. `YaleLockClient`: Encrypted Bluetooth LE communication programming PIN codes and opportunistically synchronizing lock RTC clocks (`sync_rtc=True`) and capturing battery telemetry (#30).
5. **Multi-lock & Multi-entrance support**: Manage single or multiple doors simultaneously mapped to entrance IDs in `snippen-booking` (`GET /door/locks` and `GET /door/bookings?lock_id=<id>`). Pass `--lock-id` or configure doors via `--locks` or `SNIPPEN_DOORMAN_LOCKS`.

```bash
# Run service daemon with configured locks and default SQLite storage
snippen-doorman service run

# Target specific lock ID(s) from WordPress Booking API
snippen-doorman service run --lock-id 1 --lock-id 2

# Run with multiple locks simultaneously with mapped lock IDs
snippen-doorman service run --locks "ytterdor=AA:BB:CC:DD:EE:01:KEY1:1:1,kjeller=AA:BB:CC:DD:EE:02:KEY2:1:2"

# Run a single synchronization tick and print detailed summary (polling + lock provisioning + telemetry)
snippen-doorman service sync-once

# Dry-run / offline mode without physical BLE lock
snippen-doorman service sync-once --storage memory
```

### Systemd Service & Raspberry Pi Deployment

For automated deployment on a dedicated Raspberry Pi running Raspberry Pi OS:

```bash
# 1. Build release distribution packages with checksums
python scripts/build_release.py

# 2. Run automated installer (creates doorman user, installs venv, systemd unit, and D-Bus policies)
sudo bash scripts/install_pi.sh dist/snippen_doorman_service-*.whl

# 3. Configure credentials
sudo nano /etc/snippen-doorman/snippen-doorman.env

# 4. Start service and inspect logs
sudo systemctl start snippen-doorman
journalctl -u snippen-doorman -f
```

See [docs/raspberry_pi_setup.md](docs/raspberry_pi_setup.md) for the comprehensive production deployment and Bluetooth troubleshooting guide.

### Administrative Web Dashboard & BLE Setup

`snippen-doorman-service` includes an embedded HTTP web dashboard on port `8080`:

```bash
# Start standalone web dashboard
snippen-doorman web --port 8080

# Or run with the main service (enabled by default)
snippen-doorman service run --web
```

Access the dashboard at `http://snippen-doorman-service.local:8080` (or `http://<pi-ip>:8080`) to:
- Monitor live gateway telemetry, battery health, and door/lock states.
- Test unlock and inspect live synchronization logs.
- Configure Yale Doorman locks, offline keys, and WordPress Booking API credentials.
- Provision WiFi over Bluetooth Low Energy via the companion PWA at `http://<pi-ip>:8080/web-config`.
- Activate BLE setup mode on Raspberry Pi via physical GPIO button (GPIO 26) or UI button.
