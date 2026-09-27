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
├── src/
│   └── snippen_doorman/      # Application package
│       ├── __init__.py       # Package version & exports
│       ├── main.py           # Entry point & CLI runner
│       └── (additional modules as needed)
├── tests/
│   ├── conftest.py           # Pytest fixtures
│   └── test_main.py          # Unit tests
├── .dockerignore             # Docker build context exclusions
├── Dockerfile                # Production container image definition (Python 3.14-slim)
├── pyproject.toml            # Python packaging and dependency config
├── README.md                 # User documentation
├── DEV_README.md             # Developer documentation
└── CHANGELOG.md              # Project history
```

For high-level system architecture, communication flows, and boundaries, see [docs/architecture.md](docs/architecture.md).

## Development Setup

1. **Prerequisites**: Python 3.14+ and `pip`.
2. **Environment & Dependencies**:
   - In **Dev Container**, the virtual environment is automatically set up at `/home/vscode/.venv` (outside the workspace root) to prevent collisions with host OS environments.
   - For local CLI development outside container:
     ```bash
     python -m venv ~/.venv
     source ~/.venv/bin/activate
     pip install -e ".[dev]"
     ```
3. **Testing, Linting, Formatting, and PR Validation**:
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
