# Developer Documentation - Snippen Doorman Service

## Architecture Overview

`snippen-doorman-service` is a Python service designed to manage temporary access codes for Yale Doorman door locks integrated with the Snippen booking platform.

### Directory Layout

```
snippen-doorman-service/
├── .devcontainer/            # Dev Container configuration (Python 3.14)
├── .agents/                  # Agent guidelines (Architecture, Testing, common-agent-instructions submodule)
├── docs/                     # System documentation & architecture guides
│   ├── README.md             # Documentation overview
│   ├── architecture.md       # High-level architecture and design principles
│   └── production_roadmap.md # Production roadmap and implementation plan
├── firmware/                 # Embedded or hardware integration code (optional)
├── scripts/                  # Development & formatting utilities
│   ├── build_release.py      # Release packaging and SHA-256 checksum generation tool
│   ├── format.py             # Whitespace & file formatting tool
│   ├── install_pi.sh         # Automated installer script for Raspberry Pi
│   ├── validate_pr.py        # PR SemVer & changelog validation tool
│   └── verify_door_sync.py   # Manual verification and interactive integration test tool
├── tools/                    # Companion configuration and testing tools
│   ├── decrypt_ble_snoop.py  # Decrypt Yale Doorman BLE sessions from btsnoop logs / bugreports
│   ├── fetch_btsnoop.py      # Automated ADB pull and extraction of Bluetooth HCI snoop logs
│   ├── parse_ha_keys.py      # Extract Yale OfflineKeys from Home Assistant debug logs
│   └── web-config/           # PWA Web Bluetooth WiFi setup client (HTML/CSS/JS)
├── src/
│   └── snippen_doorman/      # Application package
│       ├── __init__.py       # Package version & exports
│       ├── allocator.py      # Keypad slot allocation (descending 9->3, shielding 0-2)
│       ├── booking_client.py # Snippen Booking HTTP REST API client (spec #351)
│       ├── config_manager.py # Persistent configuration manager for .env
│       ├── db.py             # SQLite storage and PinRecord models with audit timestamps
│       ├── gpio_button.py    # Physical GPIO button handler for setup mode trigger
│       ├── main.py           # Entry point & CLI runner (service, web, rtc, pin, schedule)
│       ├── mock_server.py    # Embedded mock HTTP server simulating WordPress door API
│       ├── poller.py         # Polling reconciliation engine for Snippen Booking
│       ├── provisioner.py    # JIT PIN provisioning engine and scheduler daemon
│       ├── sync.py           # Full sync engine connecting poller, storage, and provisioner
│       ├── wifi_manager.py   # Linux NetworkManager integration for scanning & connecting WiFi
│       ├── web/              # Embedded HTTP web server & responsive administrative dashboard
│       │   ├── __init__.py   # Exports DoormanWebServer
│       │   ├── html.py       # Embedded responsive HTML/CSS/JS dashboard UI
│       │   └── server.py     # HTTP server implementation with REST endpoints
│       ├── state/            # Pluggable state storage backends
│       │   ├── base.py       # ReservationStore protocol
│       │   ├── json_store.py # Lightweight JSON file store (atomic writes)
│       │   ├── memory_store.py # In-memory store for unit tests
│       │   ├── models.py     # ReservationRecord, ReservationStatus, and content hashing
│       │   └── sqlite_store.py # Persistent SQLite store with audit timestamps
│       └── ble/              # Bluetooth Low Energy modules
│           ├── discovery.py  # BLE scanner & Yale device identification
│           ├── lock_config.py # Multi-lock configuration parser
│           ├── pin.py        # PIN/RTC protocol encoding, packet builders & error parsing
│           ├── wifi_peripheral.py # BLE GATT setup peripheral & advertisement controller
│           └── client.py     # yalexs-ble wrapper for lock operations & PIN management
├── systemd/                  # systemd service unit templates
│   ├── snippen-doorman.service # Production service definition for Raspberry Pi
│   └── snippen-doorman-dbus.conf # D-Bus permissions for unprivileged BlueZ access
├── tests/
│   ├── conftest.py           # Pytest fixtures
│   ├── test_allocator.py     # SlotAllocator tests
│   ├── test_booking_client.py # Snippen Booking HTTP client tests
│   ├── test_client.py        # Lock client tests
│   ├── test_config_manager.py # Persistent configuration manager tests
│   ├── test_db.py            # SQLite database and PinRecord tests
│   ├── test_decrypt_ble_snoop.py # BLE packet decryption tests
│   ├── test_discovery.py     # BLE discovery tests
│   ├── test_gpio_button.py   # GPIO button monitor tests
│   ├── test_integration_booking.py # Mock-based end-to-end integration tests
│   ├── test_lock_config.py   # Lock configuration parser tests
│   ├── test_main.py          # CLI runner and subcommand tests
│   ├── test_parse_ha_keys.py # Home Assistant key parser tests
│   ├── test_pin.py           # PIN protocol and encoding tests
│   ├── test_poller.py        # Poller reconciliation and diff tests
│   ├── test_provisioner.py   # JIT provisioning engine tests
│   ├── test_storage.py       # Pluggable storage backend tests
│   ├── test_sync.py          # Full sync engine tests
│   ├── test_verify_door_sync.py # Tests for interactive verification script
│   ├── test_web_config_contract.py # Contract tests for web-config PWA and server
│   ├── test_web_server.py    # Administrative web dashboard tests
│   ├── test_wifi_manager.py  # Linux NetworkManager tests
│   └── test_wifi_peripheral.py # BLE WiFi setup peripheral tests
├── .dockerignore             # Docker build context exclusions
├── Dockerfile                # Production container image definition (Python 3.14-slim)
├── pyproject.toml            # Python packaging and dependency config
├── README.md                 # User documentation
├── DEV_README.md             # Developer documentation
└── CHANGELOG.md              # Project history
```

For high-level system architecture, communication flows, and boundaries, see [docs/architecture.md](docs/architecture.md), [docs/yale_ble_protocol.md](docs/yale_ble_protocol.md), and [docs/yale_offline_key_extraction.md](docs/yale_offline_key_extraction.md).

## Multi-Door & Entrance Architecture (Spec #47)

In `snippen-booking`, multiple physical locks/entrances can be registered (e.g. Hoveddel, Kjeller). The integration follows these conventions:

- **Remote Lock Discovery (`GET /wp-json/snippen/v1/door/locks`)**:
  Returns all registered locks:
  ```json
  [
    { "id": 1, "name": "Hoveddør", "handles_objects": ["Hoveddel"] },
    { "id": 2, "name": "Kjellerinngang", "handles_objects": ["Kjeller"] }
  ]
  ```
- **Targeted Bookings Polling (`GET /wp-json/snippen/v1/door/bookings?lock_id=<id>`)**:
  When multiple locks exist, `snippen-booking` requires `lock_id` and filters bookings only for reservations that grant access through that specific door.
- **Reservation Isolation**:
  `ReservationRecord` in local SQLite storage tracks `lock_id`. Polling lock A preserves active records belonging to lock B.
- **BLE Provisioning Targeting**:
  `PinProvisioner` directs PIN provisioning and revocation to the matching `YaleLockClient` (by matching `lock_id`, name, or address).
- **Web UI & REST Helper (`GET /api/remote-locks`)**:
  The embedded web dashboard queries remote locks directly from WordPress, allowing the administrator to inspect available entrance IDs and assign them with one click.

## Development Setup

1. **Prerequisites**: Python 3.14+, `pip`, and Linux with BlueZ for Bluetooth operations.
2. **Environment & Dependencies**:
   - In **Dev Container**, the virtual environment is automatically set up at `/home/vscode/.venv` (outside the workspace root) to prevent collisions with host OS environments.
   - For local CLI development outside container:
     ```bash
     python -m venv ~/.venv
     source ~/.venv/bin/activate
     pip install -e ".[dev]"
     ```
3. **Bluetooth & BlueZ Setup**:
   - BLE-kommunikasjon krever en aktiv Bluetooth-adapter og BlueZ på Linux-hosten (`bluetoothctl`, `hciconfig hci0 up`).
   - Dev Containeren er prekonfigurert med `--net=host` og bind-mount av hostens D-Bus system socket (`/var/run/dbus/system_bus_socket`) i `.devcontainer/devcontainer.json` for direkte tilgang til BLE-maskinvaren.
4. **Testing, Linting, Formatting, and PR Validation**:
   ```bash
   # Run test suite
   pytest

   # Run lint checks
   ruff check .

   # Format files & cleanup whitespace / newlines
   python scripts/format.py

   # Validate PR version bump and changelog
   python scripts/validate_pr.py --base origin/main
   ```

5. **Release Packaging & Raspberry Pi Deployment**:
   ```bash
   # Build pure-Python wheel and source distribution with SHA-256 checksums
   python scripts/build_release.py

   # Automated installation on target Raspberry Pi OS (see docs/raspberry_pi_setup.md)
   sudo bash scripts/install_pi.sh dist/snippen_doorman_service-*.whl
   ```

6. **Manuell testing og fysisk verifikasjon mot Yale Doorman over BLE**:
   For å teste synkronisering og fysisk opplåsing med en ekte Yale Doorman for hånden:
   ```bash
   # Kjører verifikasjon med parametere fra .env (SNIPPEN_DOORMAN_BLE_ADDRESS, etc.)
   python scripts/verify_door_sync.py

   # Eller med eksplisitt PIN-kode (f.eks. 123456)
   python scripts/verify_door_sync.py --pin 123456

   # For å teste logikken offline uten fysisk lås:
   python scripts/verify_door_sync.py --dry-run
   ```

   Flyten i skriptet:
   1. Starter en innebygd mock booking-server med en aktiv reservasjon (eller kobler til ekstern via `--api-url`).
   2. Kjører `DoormanSyncEngine`: poller bookingen, genererer/oppdaterer PIN, og provisjonerer koden i et ledig gjestespor på låsen (9..3) over BLE.
   3. Skriver ut PIN og gjestespor i terminalen og pauser.
   4. Du taster koden på låsens fysiske tastatur og verifiserer at døren låser opp.
   5. Trykk `[ENTER]` (eller tast `'r'` for å hente batterinivå og status over BLE).
   6. Skriptet simulerer at reservasjonen er ferdig/slettet, fjerner koden fra låsen over BLE og frigjør sporet.

7. **Lokalt Web-dashboard (`http://snippen-doorman-service.local:8080`)**:
   For daglig administrasjon og test av dørlåser, nøkler og synkroniseringsstatus på lokalnettet:
   ```bash
   # Kjøre som del av bakgrunnstjenesten (standard)
   snippen-doorman service run

   # Kjøre dedikert web-dashboard
   snippen-doorman web --port 8080
   ```
   Dashboardet tilbyr:
   - Live telemetri (vertsnavn, lokal IP, WiFi SSID, oppetid og siste hendelser).
   - Dørlåsstatus (batteriprosent, låsetilstand, testknapp for opplåsing og manuell synkronisering).
   - Konfigurasjonsredigering for dører, offline-kryptonøkler og Booking API URL/token.

8. **BLE WiFi-oppsett og PWA (`tools/web-config`)**:
   Dersom Raspberry Pi settes opp hodeløst uten skjerm eller nettverkskabel:
   1. Aktiver BLE-oppsett (10 minutter ved oppstart, via fysisk knapp på GPIO 26, eller fra Web UI).
   2. Åpne Web Bluetooth-klienten (`http://<pi-ip>:8080/web-config` eller frittstående PWA).
   3. Trykk *"Koble til Doorman Gateway"* og skann tilgjengelige WiFi-nettverk over BLE.
   4. Velg nettverk, skriv inn WPA-passord og fullfør oppsettet. Gatewayen kobler til WiFi og gir en direkte lenke til web-dashboardet.
