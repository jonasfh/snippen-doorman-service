# AGENTS.md

## Purpose
Guide AI agents working in `snippen-doorman-service`. Keep this root file as a concise router; load detailed procedures from `.agents/` sub-guidelines and `skills/` on demand.

## Always-On Rules
- **Host-First Execution (`./dev`)**: When running on the host (outside Dev Containers), execute all Python/pytest/ruff commands through `./dev` (`./dev test`, `./dev lint`, `./dev lint:fix`, `./dev shell`), which runs inside the ephemeral `doorman-tools` container defined in `../snippen-testing/compose.tools.yml`.
- **Python & Environment**: Use Python 3.14+ under `src/snippen_doorman/`. In Dev Containers, use `/home/vscode/.venv` (outside `/workspaces/snippen-doorman-service` to prevent collisions).
- **Database Rules**: Always include `created_at` and `modified_at` timestamps on database models and custom database tables.
- **Formatting & Quality**: Routinely run `python scripts/format.py` (strips trailing whitespace, enforces single EOF newline) and resolve all `ruff check .` (or `flake8`) and `pytest` failures before completion (via `/home/vscode/.venv/bin/` in Dev Containers).
- **GitHub Issue Workflow**: Follow `gh-issue/<id>` branching, Conventional Commits (`<type>[scope]: <description> (#<id>)`), **Rebase and merge** (`gh pr merge <id> --rebase --delete-branch`), and stop after `gh pr create`.
- **Documentation & Versioning**: Keep `README.md`, `DEV_README.md`, `docs/`, and architecture docs in sync; bump version in `pyproject.toml` or `src/snippen_doorman/__init__.py` and add a `CHANGELOG.md` entry under `## [X.Y.Z] - YYYY-MM-DD` on functional changes.
- **Environment Adaptation**: Use `git status --ignore-submodules` for fast status checks; update `AGENTS.md` and `.agents/` whenever new environment workarounds are discovered.

## Multi-Agent & Complexity Triage
- **Automatic Triage**: The primary agent automatically selects Level 1 (Single Agent Fast Path), Level 2 (Coordinator + `Researcher`/`Verifier` subagents), or Level 3 (Multi-Agent Team) per [ROLES.md](file:///.agents/common-agent-instructions/ROLES.md) and [PLAYBOOK.md](file:///.agents/common-agent-instructions/PLAYBOOK.md).
- **Approval Gate**: On Level 2/3 tasks, Coordinator runs `/plan` and stops **once** for user approval before launching parallel implementation workers.
- **Isolation**: Parallel `Implementer` workers must use isolated workspaces (`workspace: "share"` / `git worktree`); readers and `Verifier` share `inherit`.

## Modular Sub-guidelines

### Common Guidelines
- 🔄 **[Workflow Guidelines](file:///.agents/common-agent-instructions/WORKFLOW.md)**: Issue-driven flow, Fast Path vs. Multi-Agent Path, submodule updates, and PR rules.
- 🤝 **[Multi-Agent Roles](file:///.agents/common-agent-instructions/ROLES.md)**: Complexity triage, role contracts, hand-offs, and Antigravity/Copilot portability.
- 📖 **[Developer Playbook](file:///.agents/common-agent-instructions/PLAYBOOK.md)**: Practical developer manual for `/plan`, `/teamwork`, `/grill-me`, and Copilot.
- 📝 **[Documentation Standards](file:///.agents/common-agent-instructions/DOCUMENTATION.md)**: Documentation sync and Mermaid rules.
- 🧪 **[Quality & Testing Principles](file:///.agents/common-agent-instructions/TESTING.md)**: Automated tests, zero-lint policy, and formatting hygiene.
- 📐 **[Common Architecture](file:///.agents/common-agent-instructions/ARCHITECTURE.md)**: Modularity, decoupling, and universal DB timestamps.

### Python Guidelines
- 🛠️ **[Python Environment & Tooling](file:///.agents/python-agent-instructions/PYTHON_ENVIRONMENT_AND_TOOLING.md)**: Virtual environment management (`uv`, `poetry`, `venv`), `pyproject.toml`, and `ruff`.
- 🏷️ **[Python Typing & Style](file:///.agents/python-agent-instructions/PYTHON_TYPING_AND_STYLE.md)**: Strict type hints (PEP 484/585/604), Pydantic v2 & dataclasses, zero unbounded `Any`.
- 🧪 **[Python Testing & QA](file:///.agents/python-agent-instructions/PYTHON_TESTING.md)**: `pytest`, `pytest-asyncio`, test isolation, and `mypy`/`pyright`.
- 📐 **[Python Architecture](file:///.agents/python-agent-instructions/PYTHON_ARCHITECTURE.md)**: `asyncio`, `src/` layout, modularity, and explicit interfaces.
- 📝 **[Python Documentation](file:///.agents/python-agent-instructions/PYTHON_DOCUMENTATION.md)**: Google-style docstrings (PEP 257) and sync rules.

### Project-Specific Guidelines
- 🐍 **[Project Architecture](file:///.agents/ARCHITECTURE.md)**: Tech stack, directory structure, module layout, and async I/O.
- 🧪 **[Project Testing & QA](file:///.agents/TESTING.md)**: Running `pytest`, `ruff`, `scripts/format.py`, and `scripts/validate_pr.py`.
