# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
