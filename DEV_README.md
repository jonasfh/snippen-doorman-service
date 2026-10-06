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
│   └── architecture.md       # High-level architecture and design principles
├── firmware/                 # Embedded or hardware integration code (optional)
├── scripts/                  # Development & formatting utilities
│   ├── format.py             # Whitespace & file formatting tool
│   └── validate_pr.py        # PR SemVer & changelog validation tool
├── tools/                    # Companion configuration and testing tools
│   └── parse_ha_keys.py      # Extract Yale OfflineKeys from Home Assistant debug logs
├── src/
│   └── snippen_doorman/      # Application package
│       ├── __init__.py       # Package version & exports
│       ├── main.py           # Entry point & CLI runner
│       └── ble/              # Bluetooth Low Energy modules
│           ├── discovery.py  # BLE scanner & Yale device identification
│           └── client.py     # yalexs-ble wrapper for status and lock operations
├── tests/
│   ├── conftest.py           # Pytest fixtures
│   ├── test_client.py        # Lock client tests
│   ├── test_discovery.py     # BLE discovery tests
│   ├── test_main.py          # CLI runner tests
│   └── test_parse_ha_keys.py # Home Assistant key parser tests
├── .dockerignore             # Docker build context exclusions
├── Dockerfile                # Production container image definition (Python 3.14-slim)
├── pyproject.toml            # Python packaging and dependency config
├── README.md                 # User documentation
├── DEV_README.md             # Developer documentation
└── CHANGELOG.md              # Project history
```

For high-level system architecture, communication flows, and boundaries, see [docs/architecture.md](docs/architecture.md), [docs/yale_ble_protocol.md](docs/yale_ble_protocol.md), and [docs/yale_offline_key_extraction.md](docs/yale_offline_key_extraction.md).

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
