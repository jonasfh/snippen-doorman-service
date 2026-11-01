# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.17.1] - 2026-11-01

### Fixed
- Switched self-signed TLS certificate generation in `src/snippen_doorman/web/tls.py` to RSA-2048 leaf server certificates (`BasicConstraints(ca=False)`, 397-day validity, and compatible `KeyUsage` flags) and added automatic startup regeneration of older/incompatible certificates, resolving Chrome (`ERR_SSL_KEY_USAGE_INCOMPATIBLE`) and Safari self-signed certificate rejection (#68).
- Updated `scripts/install_pi.sh` to install `--upgrade` directly from the source repository when no wheel path is passed, avoiding stale wheels in `dist/` (#68).

## [0.17.0] - 2026-10-31

### Added
- Automatic self-signed X.509 certificate and ECDSA private key generation (`src/snippen_doorman/web/tls.py`) with Subject Alternative Names (SAN) for `localhost`, `snippen-doorman-service.local`, host hostname, and local IPv4 addresses (#68).
- Built-in HTTPS/TLS support in `DoormanWebServer` (`ssl.SSLContext` with minimum `TLSv1.2`), protecting HTTP Basic Authentication credentials, API tokens, and Yale BLE keys in transit as well as enabling Chrome Web Bluetooth Secure Context on local network IPs (#68).
- CLI options (`--tls` / `--no-tls`, `--tls-cert`, `--tls-key`) and environment variables (`SNIPPEN_DOORMAN_WEB_TLS`, `SNIPPEN_DOORMAN_TLS_CERT`, `SNIPPEN_DOORMAN_TLS_KEY`) for `service run` and `web` subcommands (#68).
- TLS connection indicator badge in the Web Dashboard Gateway Status panel and dynamic service version display (#68).

## [0.16.1] - 2026-10-29

### Added
- Automated NTP time synchronization on Raspberry Pi: `install_pi.sh` now installs `systemd-timesyncd` and `fake-hwclock` and configures Norwegian NTP servers (`no.pool.ntp.org`), preventing clock drift and time reversal on standalone Pi deployments (#64).
- Systemd dependency on `time-sync.target` and `systemd-timesyncd.service` in `snippen-doorman.service` ensuring access control services and JIT timers only start after the host clock is verified (#64).
- Daily RTC heartbeat in `DoormanSyncEngine`: periodically connects to configured Yale Doorman locks every 24 hours (`SNIPPEN_DOORMAN_HEARTBEAT_INTERVAL_HOURS=24.0`) to synchronize the internal hardware RTC clock and capture battery telemetry during periods without active bookings (#64).
- Heartbeat interval configuration in `ConfigManager` and `default.env`, alongside comprehensive unit tests verifying 24-hour cycle triggers, error isolation, and timer resets on PIN activations (#64).

## [0.16.0] - 2026-10-29

### Added
- Architectural specification and design blueprint for multi-node deployments and independent rental units (`docs/multi_node_architecture.md`) solving physical BLE range limits and guaranteeing strict credential isolation across separate venues (#57).
- Embedded microcontroller (ESP32 BLE Bridge) gateway blueprints and firmware structure (`firmware/esp32/README.md`) for low-power, instant-boot standalone nodes (#57).
- Scoped multi-node polling integration with WordPress Booking API (`GET /wp-json/snippen/v1/door/bookings?lock_id=<id>`) and central fleet status monitoring specifications (#57).
- Updated system architecture overview and top-level documentation referencing multi-node deployment strategies (#57).

## [0.15.3] - 2026-10-29

### Added
- HTTP Basic Authentication protection for the administrative Web Dashboard (`/` and `/api/*`) with constant-time password verification via `hmac.compare_digest` (#58).
- Admin password configuration support in `ConfigManager`, `.env`, and the web dashboard's «API & Innstillinger» tab (#58).
- Unauthenticated access carve-out for standalone `/web-config/*` PWA tools to preserve direct mobile Bluetooth Wi-Fi onboarding without credential friction (#58).
- Comprehensive unit tests covering authentication challenges, valid/invalid credentials, password updates via API, and unauthenticated static asset access (#58).

## [0.15.2] - 2026-10-29

### Fixed
- Fixed JavaScript syntax error in `src/snippen_doorman/web/html.py` caused by an orphaned duplicate code block, restoring interactivity and tab switching across all dashboard views (#59).
- Enhanced `showTab` navigation handler in `html.py` to robustly activate tabs without relying on global `window.event` (#59).
- Added dynamic door removal support (`removeLockRow`) in the web dashboard's «🔐 Dørlåser» tab (#59).
- Added BLE setup status reflection in `loadStatus()` so the «📡 BLE WiFi Oppsett» tab dynamically indicates active peripheral advertising (#59).

### Added
- Discrete multi-lock persistence in `ConfigManager.update_config()`: updating door configurations through the dashboard now updates and writes `DOORMAN_LOCK_<N>_*` variables and purges stale door tags (#59).
- Comprehensive dashboard structure and discrete multi-lock configuration tests in `tests/test_web_server.py` (#59).

## [0.15.1] - 2026-10-29

### Added
- Dedicated unit test in `tests/test_sync.py` verifying that when multiple physical locks share the same `lock_id`, polling is deduplicated and `add_pin` is dispatched to all matching physical locks (#56).

### Changed
- Deduplicated target lock polling in `DoormanSyncEngine` (`sync.py`) so multiple physical locks sharing the same WordPress resource / lock ID are only queried once per synchronization cycle (#56).
- Updated `default.env` and `README.md` documenting shared lock ID configuration across multiple physical doors (e.g. Festsalen and Peisestua sharing `lock_id=1`) (#56).

## [0.15.0] - 2026-10-25

### Added
- Discrete per-lock environment variables support in `lock_config.py` and `config_manager.py` (`DOORMAN_LOCK_<N>_NAME`, `_ADDRESS`, `_KEY`, `_SLOT`, `_LOCK_ID`), providing a human-readable and systemd `EnvironmentFile` friendly alternative to comma-separated multi-lock strings (#50).
- Option to disable device name filtering and accept all BLE devices in `tools/web-config` PWA for easier initial hardware discovery (#50).
- SQLite Write-Ahead Logging (WAL) mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`) in `Database` and `SqliteReservationStore` for power-failure resilience and concurrent read-access (#52).
- Automatic startup database integrity check with safe corrupt file backup recovery (#52).
- Explicit data directory creation with `0750` permissions in `scripts/install_pi.sh` (#52).
- Stateful network resilience in `DoormanSyncEngine`: when Wi-Fi or the booking API is unreachable, the daemon logs a warning once and operates in offline mode using the local SQLite database to provision scheduled PINs when due, automatically resuming online synchronization when connectivity is restored (#53).
- Multi-door BLE fault isolation ensuring communication failures on one lock do not prevent or delay provisioning to other configured locks (#53).

### Changed
- Updated `default.env` to document discrete per-lock environment variable configuration (#50).
- Updated `snippen-doorman.service` dependencies from `network-online.target` to `network.target` to ensure fast boot and immediate local offline operation without stalling for network availability (#53).

## [0.14.0] - 2026-10-21

### Added
- Multi-door and multi-entrance REST API support matching updated `snippen-booking` specification (#47).
- `RemoteLock` dataclass and `fetch_locks()` method in `SnippenBookingClient` querying `GET /wp-json/snippen/v1/door/locks` (#47).
- Support for `lock_id` query parameter in `SnippenBookingClient.fetch_bookings(lock_id=...)` (#47).
- Multi-door configuration with `lock_id` mapping in `LockConfig`, `LockSetting`, `parse_lock_configs`, and `ConfigManager` via `SNIPPEN_DOORMAN_LOCK_ID` and `SNIPPEN_DOORMAN_LOCKS` (`name=MAC:KEY:SLOT:LOCK_ID` or JSON format) (#47).
- Automatic database schema migration in `SqliteReservationStore` adding `lock_id` column to `reservations` table with audit timestamps (#47).
- Scoped reservation polling and reconciliation in `BookingPoller` ensuring reservations for one entrance are not pruned when polling another entrance (#47).
- Door-specific PIN provisioning and revocation routing in `PinProvisioner` targeting the matching `YaleLockClient` (#47).
- Multi-lock polling loop in `DoormanSyncEngine` iterating through configured lock IDs with battery-saving change detection (#47).
- CLI `--lock-id` option in `snippen-doorman service run` and `snippen-doorman service sync-once` (#47).
- Backend endpoint `GET /api/remote-locks` on `DoormanWebServer` for discovering registered locks from WordPress (#47).
- Extended `/api/status` endpoint to expose telemetry for all configured locks (#47).
- Web Dashboard enhancements in `html.py`:
  - "Hent låser fra WordPress Booking API" helper card to query available doors and auto-assign IDs (#47).
  - Lås-ID input field per door row (#47).
  - Multi-door overview display card in status tab (#47).

## [0.13.0] - 2026-10-15

### Added
- Quick action button "🔒 Lås dør (Test)" in the web dashboard alongside the unlock action, with new `POST /api/test/lock` backend endpoint.
- In-memory lock telemetry cache in `DoormanWebServer` for zero-latency UI updates upon status or lock/unlock actions.
- Norwegian display mappings for lock and door statuses (`Ulåst` / `Låst` and `Lukket` / `Åpen`).
- Raspberry Pi setup documentation update detailing user permissions (`bluetooth` group), rfkill unblock, and service restarts.

### Fixed
- Fixed thread-safety in `Database` by enabling `check_same_thread=False` with mutual exclusion lock across HTTP request threads.
- Fixed database initialization in standalone `snippen-doorman web` so database tables are created automatically on launch.
- Fixed telemetry updates during test unlock/lock actions so live battery and lock state are recorded to the database.

## [0.12.0] - 2026-10-15

### Added
- Local administrative Web Dashboard (`snippen_doorman.web.DoormanWebServer`) on port 8080 accessible at `http://snippen-doorman-service.local:8080` with modern responsive dark-mode UI (#44, #36).
- Embedded REST API endpoints on web server:
  - `GET /api/status`: System telemetry (hostname, local IP, active WiFi SSID, uptime, recent events ring buffer, primary lock status and battery, and BLE setup window remaining seconds).
  - `GET /api/config` and `POST /api/config`: View and update configuration with safe masking of secret keys and input validation.
  - `POST /api/test/unlock`: Quick test action to send unlock command over BLE to verify lock mechanism.
  - `POST /api/test/status`: Test action to query live battery and lock/door status over BLE and update database.
  - `POST /api/test/api`: Test action to query Booking API endpoint and report number of active reservations.
  - `POST /api/sync`: Manual sync trigger executing a single synchronization cycle against the booking platform.
  - `GET /api/wifi/networks`: Scan nearby 2.4/5GHz WiFi networks via NetworkManager (`nmcli`).
  - `POST /api/wifi/connect`: Connect to WiFi SSID with WPA passkey via NetworkManager.
  - `POST /api/ble-setup`: Activate 10-minute BLE setup window.
- Physical GPIO button handler (`snippen_doorman.gpio_button.GpioButtonHandler`) monitoring physical pushbutton on GPIO 26 with falling edge debounce, activating BLE setup mode on press (#44).
- BLE WiFi setup peripheral controller (`snippen_doorman.ble.wifi_peripheral.BleWifiPeripheral`) implementing GATT service and characteristics matching `snippen-sms-service` standard, with automatic 10-minute timeout and `bluetoothctl` advertisement control (#36).
- Web Bluetooth Configuration PWA (`tools/web-config`) in vanilla HTML/CSS/JS with service worker and manifest, supporting WiFi scanning, connection testing, simulator mode for hardware-independent development, and direct hand-off link to the local Web Dashboard (#36).
- Static asset serving for `/web-config` directly from `DoormanWebServer` (#36).
- Integration of Web Dashboard, GPIO button, and BLE peripheral into `snippen-doorman service run` (with `--web` / `--no-web` flags) and standalone CLI subcommand `snippen-doorman web` (#44).
- Unit and contract tests for configuration manager, web server, WiFi manager, GPIO button handler, and Web Config PWA contract (#44, #36).

## [0.11.0] - 2026-10-15

### Added
- Interactive integration test and verification script (`scripts/verify_door_sync.py`) for end-to-end hardware-in-the-loop validation of Yale Doorman synchronization over BLE (#42).
- Embedded mock booking server module (`snippen_doorman.mock_server.MockBookingApiServer`) simulating WordPress Snippen Booking REST API with `GET /bookings` and `PATCH /bookings/:id/code` endpoints (#42).
- Interactive verification flow with live status feedback: provisions active reservations immediately into guest keypad slots (9..3), pauses for physical door code entry, supports opportunistic telemetry/battery queries (`'r'`), and automatically deprovisions slots and clears PINs upon confirmation (#42).
- Fail-safe cleanup and `--dry-run` simulation support in `verify_door_sync.py` enabling both offline automated CI execution and hardware safety if aborted mid-test (#42).
- Unit and automated lifecycle integration tests in `tests/test_verify_door_sync.py` (#42).
- Updated `DEV_README.md` with manual testing and physical verification instructions (#42).

## [0.10.0] - 2026-10-14

### Added
- Release packaging utility (`scripts/build_release.py`) to build versioned Python wheels, source distributions, and generate `SHA256SUMS` checksum manifests (#37).
- Automated Raspberry Pi OS installer (`scripts/install_pi.sh`) setting up system dependencies (`bluez`, `rfkill`, `python3-venv`), service user/group `doorman`, virtualenv in `/opt/snippen-doorman-service/.venv`, environment file with restrictive permissions (`0640`), D-Bus permissions, and systemd service activation (#37, #7).
- D-Bus policy definition (`systemd/snippen-doorman-dbus.conf`) granting unprivileged service user `doorman` access to BlueZ GATT/adapter APIs over system D-Bus (#7).
- Systemd hardening and Bluetooth recovery in `systemd/snippen-doorman.service`, including automatic restart (`Restart=on-failure`), sandboxing (`ProtectSystem=full`, `PrivateTmp=true`, `NoNewPrivileges=true`), and pre-start rfkill unblock (`ExecStartPre=-/usr/sbin/rfkill unblock bluetooth`) (#7).
- Production deployment and troubleshooting guide for Raspberry Pi OS in `docs/raspberry_pi_setup.md` (#7).
- Multi-door offline key documentation in `docs/yale_offline_key_extraction.md` explaining 1 offline key per door, simultaneous Home Assistant key extraction, and `DOORMAN_LOCKS` configuration.
- Comprehensive unit tests for `build_release.py` in `tests/test_build_release.py`.

## [0.9.0] - 2026-10-14

### Added
- Core synchronization engine (`DoormanSyncEngine`) coordinating booking polling (`BookingPoller`), state storage (`ReservationStore`), and keypad slot provisioning (`PinProvisioner`) into an end-to-end background daemon (#29, #30).
- Sleep and battery preservation logic for Yale Doorman: unchanged reservations trigger zero BLE communication, leaving battery-powered locks in deep sleep mode (#29).
- Time-controlled JIT activation window (`--lead-time`, default 60 min) ensuring PINs are only programmed onto the lock when entering the active access window (#29).
- Dynamic change detection and in-place lock code updating (`PENDING_UPDATE`) when booking PIN or validity timeframe is modified in WordPress (#29, #30).
- Rescheduling detection: bookings moved outside the active access window to the future are automatically deprovisioned from the lock, returning the keypad slot to the pool (#29, #30).
- Immediate revocation and deprovisioning (`PENDING_REVOKE`) when bookings are cancelled or removed from the remote platform (#29, #30).
- Resilient BLE error handling: temporary lock unavailability or timeouts do not lose desired state; transactions retry on subsequent polling cycles (#30).
- Opportunistic telemetry recording: lock battery percentage and door/lock status are automatically captured and persisted in SQLite `lock_status` table upon connection (#30).
- Opportunistic RTC clock synchronization: internal Real-Time Clock on Yale Doorman locks is synchronized (`sync_rtc=True`) during PIN programming with zero extra BLE connection overhead (#30).
- Multi-lock management (`LockConfig`, `parse_lock_configs`, `--locks`, `SNIPPEN_DOORMAN_LOCKS`): simultaneously administers multiple locks (e.g. 2 doors on Snippen) from a single service instance (#30).
- Updated CLI commands `snippen-doorman service run` and `snippen-doorman service sync-once` supporting multi-lock configurations, lead time, grace period, and detailed execution summaries.

## [0.8.1] - 2026-10-12

### Fixed
- Fixed `sqlite3.ProgrammingError` in `SqliteReservationStore` when accessed across worker threads in `BookingPoller` background loop (`asyncio.to_thread`) by configuring `check_same_thread=False` and protecting database calls with `threading.Lock` (#34).
- Added cross-thread unit test in `tests/test_storage.py`.
- Fixed candidate path handling in `scripts/format.py` when `ruff` is not present in PATH.

## [0.8.0] - 2026-10-09

### Added
- Snippen Booking REST API client (`SnippenBookingClient`) communicating with WordPress endpoint (spec `snippen-booking#351`) using Bearer token authentication and custom error hierarchy
- Pluggable reservation state storage abstraction (`ReservationStore`) with implementations for SQLite (`SqliteReservationStore`), atomic JSON file (`JsonFileReservationStore`), and in-memory (`InMemoryReservationStore`)
- Automatic audit timestamps (`created_at`, `modified_at`, `last_seen_at`) and deterministic SHA-256 content hashing (`compute_content_hash`) for change detection
- Privacy-by-Design reservation model (`ReservationRecord`) tracking only booking ID, validity window, PIN, and status without storing tenant personal identifiable information (PII)
- Periodic polling and reconciliation engine (`BookingPoller`) detecting new, updated, unchanged, and removed/cancelled reservations with automatic PIN generation and PATCH reporting
- CLI command `snippen-doorman service run` and `snippen-doorman service sync-once` with signal handling (`SIGINT`, `SIGTERM`)
- Systemd service template (`systemd/snippen-doorman.service`) for running daemon on Raspberry Pi
- Mock-based end-to-end integration tests (`tests/test_integration_booking.py`) verifying the entire synchronization lifecycle across SQLite and JSON backends

## [0.7.0] - 2026-10-09

### Added
- Hardware RTC clock synchronization protocol support (`CMD_SET_RTC`, opcode `0x10`) for Yale Doorman / Yale Access Module
- Helper function `build_set_rtc_packet` in `snippen_doorman.ble.pin` building 18-byte August frames with UTC epoch timestamps and valid two's complement checksums
- Method `set_rtc` and optional `sync_rtc` parameter on `add_pin` in `YaleLockClient` (`snippen_doorman.ble.client`)
- CLI subcommand `snippen-doorman rtc sync [--time <ISO>]` for syncing lock clock to host system time or explicit ISO timestamp
- Opcode definitions and frame detail parsing for `0x10` (`CMD_SET_RTC`) and `0x30` (`CMD_SET_TIMEZONE`) in `tools/decrypt_ble_snoop.py`
- Comprehensive unit tests covering packet generation, client execution, error handling, and CLI command

## [0.6.0] - 2026-10-08

### Added
- Local keypad slot allocator (`SlotAllocator`) allocating guest slots in descending order (slots 9 down to 3) to protect admin slots 0-2 reserved for Yale Home
- Persistent SQLite PIN management database (`Database`) and data model (`PinRecord`, `PinStatus`) tracking reservations, slots, and `created_at` / `modified_at` audit timestamps
- Time-controlled Just-In-Time (JIT) provisioning engine (`PinProvisioner`) programming PINs onto the lock within a lead-time window and deprovisioning after expiration plus grace period
- Background scheduler loop (`run_provisioning_scheduler`) for periodic reconciliation and slot recycling
- CLI subcommands for `schedule add`, `schedule list`, `schedule revoke`, `schedule sync`, and `schedule run`
- Comprehensive test suite for slot allocation, persistent state hydration, and JIT provisioning reconciliation

## [0.5.1] - 2026-10-08

### Fixed
- Fixed checksum calculation bug where `Session._write_checksum` in `yalexs_ble` overwrote pre-computed command checksums with `0x00`, resulting in command rejection by lock firmware
- Added automatic pre-clearing (`KeyCode_Clear` `0x28`) before `KeyCode_Set` to ensure lock slot memory hygiene, matching official Yale Home behavior
- Added support for 0-indexed keypad slots (`slot 0` and higher) matching August hardware conventions

### Verified
- Physical end-to-end keypad unlock and code deletion verified and confirmed against physical Yale Doorman hardware
- Documented physical keypad behavior, 3-minute tamper lockout handling, and BLE emergency lockout override in `docs/yale_ble_protocol.md` and `docs/yale_ble_pin_protocol.md`

## [0.5.0] - 2026-10-08

### Added
- Native local PIN code management methods on `YaleLockClient` (`add_pin`, `delete_pin`, `list_pins`) communicating directly with Yale Access Module over BLE without cloud dependency
- BLE PIN protocol helper module `snippen_doorman.ble.pin` implementing packed BCD encoding/decoding, August 18-byte command packets, and response validation
- CLI subcommands for `pin add`, `pin delete`, and `pin list` with support for optional validity schedules (`--from`, `--to`) and friendly names
- Automatic `.env` credential fallback for `--address`, `--key`, and `--key-slot` across all CLI commands
- Comprehensive unit test suite in `tests/test_pin.py` and extended `tests/test_client.py` and `tests/test_main.py`

## [0.4.0] - 2026-10-08


### Added
- Bluetooth HCI snoop capture and GATT session decryption tool `tools/decrypt_ble_snoop.py` for parsing btsnoop logs and bugreport archives, deriving session keys from offline keys, and decrypting command and response frames
- Automated ADB snoop log pull and extraction utility `tools/fetch_btsnoop.py`
- Test suite `tests/test_decrypt_ble_snoop.py` covering BCD PIN encoding/decoding, handshake key derivation, and continuous AES-CBC command decryption
- Live traffic verification against real BLE traffic capturing PIN creation and deletion across Always, Temporary, and Recurring schedules

## [0.3.2] - 2026-10-07

### Fixed
- Fixed `PushLock` lifecycle management in `YaleLockClient` by ensuring `start()` and `wait_for_first_update()` are invoked before status queries and lock operations
- Fixed battery reporting to extract percentage from `BatteryState`
- Added clean `disconnect()` call on CLI completion and async context manager support

## [0.3.1] - 2026-10-06

### Changed
- Configured Dev Container (`.devcontainer/devcontainer.json`) with `--net=host`, BlueZ package, and D-Bus system socket mount for native BLE operations
- Added `diag.json` to `.gitignore`

## [0.3.0] - 2026-10-06

### Added
- Complete guide for extracting Yale offline keys and setting up dedicated admin account (`post@vestreholmensameie.no`) in `docs/yale_offline_key_extraction.md`
- Companion CLI tool `tools/parse_ha_keys.py` for parsing and extracting `OfflineKeys` from Home Assistant debug logs into `.env`
- Unit tests for `parse_ha_keys` parser and `.env` updater in `tests/test_parse_ha_keys.py`
- Documentation and quick start updates across `README.md`, `DEV_README.md`, and `docs/README.md`

## [0.2.0] - 2026-10-06

### Added
- BLE discovery module (`snippen_doorman.ble.discovery`) for scanning and detecting Yale Doorman locks and access modules
- BLE client wrapper (`snippen_doorman.ble.client`) for status querying and lock/unlock operations using `yalexs-ble`
- CLI subcommands for `discover`, `status`, `lock`, and `unlock`
- Comprehensive BLE protocol documentation in `docs/yale_ble_protocol.md`
- Unit tests for discovery, lock client, and CLI commands
- Dependencies `yalexs-ble` and `bleak`

## [0.1.0] - 2026-09-27

### Added
- Initial project setup with Python 3.14+ development environment
- Directory structure and tooling (Dev Container, pytest, ruff)
- Yale Doorman access module integration framework
- Temporary code management system
- Basic CLI interface for code generation and management
- SQLite database schema for codes and access logs
- Snippen booking platform synchronization skeleton
