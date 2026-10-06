# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
