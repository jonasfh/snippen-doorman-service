# Architecture & Coding Standards

## Tech Stack & Environment
- **Python**: 3.14+ (Dev Container virtualenv located at `/home/vscode/.venv` outside workspace)
- **Framework / Service**: Python Async Access Control Service
- **Dependency & Package Management**: `pyproject.toml` (pip / uv / poetry)
- **Module Structure**: `src/snippen_doorman/`

## Directory Structure

```
snippen-doorman-service/
├── .devcontainer/                    # Dev Container configuration for Python 3.14
├── .agents/                          # Project-specific agent instructions
│   ├── ARCHITECTURE.md               # Python architecture & directory layout
│   ├── TESTING.md                    # Python pytest/ruff commands
│   └── common-agent-instructions/    # Submodule: common technology-agnostic instructions
├── docs/                             # System documentation & architecture guides
│   ├── README.md                     # Documentation overview
│   └── architecture.md               # High-level architecture & design
├── firmware/                         # MicroPython or embedded code (optional)
├── scripts/                          # Development & formatting utilities
│   ├── format.py                     # Whitespace & file formatting tool
│   └── validate_pr.py                # PR SemVer & changelog validation tool
├── src/
│   └── snippen_doorman/              # Python application package
│       ├── __init__.py               # Version declaration
│       └── main.py                   # Service entry point
├── tests/                            # pytest test suite
│   ├── conftest.py                   # pytest fixtures
│   └── test_main.py                  # Unit tests
├── tools/                            # Companion tools and utilities
├── pyproject.toml                    # Dependencies and tools configuration
├── README.md                         # User documentation
├── DEV_README.md                     # Developer documentation
├── CHANGELOG.md                      # Project history
├── Dockerfile                        # Production container image (Python 3.14-slim)
└── AGENTS.md                         # Agent guidelines and conventions
```

## Python-Specific Architectural Rules
- **Modular & Testable**: Keep application logic modular, decoupled from framework-specific handlers where practical.
- **Database Tables**: Always include `created_at` and `modified_at` timestamp columns on database models (see [Common Architecture Standards](file:///.agents/common-agent-instructions/ARCHITECTURE.md)).
- **Type Annotations**: Use Python type hints (`typing`) across all new classes and functions.
- **Async & I/O**: Use async/await for network integrations where applicable.
