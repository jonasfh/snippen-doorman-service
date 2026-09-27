# Python Testing & Quality Assurance Guidelines

Refer to [Common Quality Principles](file:///.agents/common-agent-instructions/TESTING.md) for overall testing and quality policies.

## Test & Lint Commands

Use `pytest` and `ruff` (or Docker container) to run linting and tests:

```bash
# Run tests directly
pytest

# Run fast / specific unit tests
pytest tests/test_main.py

# Linting and style checks (Ruff)
ruff check .
ruff format --check .

# Project-wide formatting (Python, Markdown, JSON, YAML, TOML)
python scripts/format.py

# PR validation (SemVer and CHANGELOG check)
python scripts/validate_pr.py
```

## Mandatory Python Rules
- **Create tests**: Create unit or integration tests in `tests/` for all new functionality.
- **Update tests**: Update existing tests when modifying functionality.
- **Linting check**: Always run `ruff check .` (or flake8) and resolve all errors and warnings before completing a task.
- **Formatting check**: Always run `python scripts/format.py` (or `ruff format`) before committing to remove trailing whitespace, add single newline at file end, and remove duplicate newlines from file end across all files (including Markdown).

## Writing Tests
- Locate tests in `tests/`.
- File names follow `test_*.py` format.
- Test function names start with `test_*`.
- Use `pytest` fixtures in `tests/conftest.py` for shared setups.
