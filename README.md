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

### Extracting Offline Keys

Extract offline keys from a Home Assistant debug log (see [docs/yale_offline_key_extraction.md](docs/yale_offline_key_extraction.md)):

```bash
# Parse log file and display keys
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log

# Automatically populate or update .env credentials
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log --output-env .env
```

### Start Service

Start the doorman access control service:

```bash
# Start service using default configuration
python -m snippen_doorman.main

# Or run with custom settings
python -m snippen_doorman.main --log-level DEBUG --database-path data/doorman.db
```
