# AGENTS.md

## Purpose
Guide AI agents working in this repository.

## Key Rules & Guidelines

- **Python Standards & Best Practices**: Use Python 3.14+. Project source code resides in `src/snippen_doorman/` (or `snippen_doorman/`). In Dev Containers, the virtual environment is maintained at `/home/vscode/.venv` (outside `/workspaces/snippen-doorman-service`) to prevent host/container `.venv` collisions.
- **Testing & Quality Control**:
  - Always write `pytest` unit/integration tests for new functionality and update existing tests when modifying functionality.
  - Run linting (`ruff check .` / `flake8`) and tests (`pytest`) before completing a task. Resolving all linting errors and warnings is mandatory.
  - Run pytest/ruff via `/home/vscode/.venv/bin/pytest` or `/home/vscode/.venv/bin/ruff check .` (or system/container tools).
- **Database Rules**: Always include `created_at` and `modified_at` timestamps on database models and custom database tables.
- **GitHub Issue Workflow**: All development MUST follow an associated GitHub Issue or direct Code Scanning / Dependabot alert IDs. Create branches like `gh-issue/<id>`, `dep-<ids>-fix-dependabot-issues`, or `sec-<ids>-fix-code-scanning-issues`, create PRs, and format commit messages accordingly (`(#<id>) Description` or `(sec-<ids>) Description` / `(dep-<ids>) Description`). Commits within the submodule referencing an issue in this repository must use the full reference `(jonasfh/snippen-doorman-service#<id>) Description`.
- **Formatting & Whitespace Hygiene**: Routinely run the repository formatter (`python scripts/format.py`) after creating or editing files and always before committing. All project files (Python, Markdown, JSON, YAML, TOML, etc.) must have:
  - Trailing whitespaces stripped.
  - A single newline (`\n`) at the end of the file.
  - Duplicate/excess trailing newlines removed.
- **PR Merging Strategy**: When merging PRs, ALWAYS use **Rebase and merge** (`gh pr merge <id> --rebase --delete-branch`) by default. If rebasing issues or conflicts arise, create a standard merge commit (`gh pr merge <id> --merge --delete-branch`). Do NOT use squash and merge (`--squash`) unless explicitly instructed or required for a specific reason.
- **Documentation**: Always update documentation (`README.md`, `DEV_README.md`, `docs/`, and architecture documents) whenever implementing new features, endpoints, data models, or database schemas. Keeping documentation in sync with the codebase is mandatory.

## Self-Improvement & Environment Adaptation
- **Continuous Agent Guideline Updates**: Whenever an agent experiences friction, environment errors (e.g., sandbox network access for `gh` CLI commands requiring `BypassSandbox: true`, missing CLI tools, unusual log locations, or git ref locks), the agent MUST update `AGENTS.md` and `.agents/` (or `.agents/common-agent-instructions/`) modular guidelines with the discovered workaround or instructions so subsequent agent sessions execute cleanly without repeating trial-and-error.
- **Dev Container Virtual Environment**: To avoid host OS workspace `.venv` files breaking container execution, Dev Container virtualenvs are located outside the workspace at `/home/vscode/.venv` (configured in `.devcontainer/devcontainer.json` via `python.defaultInterpreterPath`).

## Modular Sub-guidelines

### Common (Technology-Agnostic) Submodule Guidelines
- 🔄 **[Workflow Guidelines](file:///.agents/common-agent-instructions/WORKFLOW.md)**: GitHub issue-driven workflow, branching, commit conventions, PR merge rules, SemVer, and CHANGELOG maintenance.
- 📝 **[Documentation Standards & Diagrams](file:///.agents/common-agent-instructions/DOCUMENTATION.md)**: Documentation synchronization, README/DEV_README maintenance, and Mermaid syntax rules.
- 🧪 **[Quality & Testing Principles](file:///.agents/common-agent-instructions/TESTING.md)**: Automated test requirements, zero-linting policy, and formatting hygiene.
- 📐 **[Common Architecture](file:///.agents/common-agent-instructions/ARCHITECTURE.md)**: Modularity, decoupling, and universal database timestamp rules.

### Project-Specific Guidelines
- 🐍 **[Project Architecture & Tech Stack](file:///.agents/ARCHITECTURE.md)**: Python tech stack, directory structure, module layout, and async I/O.
- 🧪 **[Python Testing & Quality Commands](file:///.agents/TESTING.md)**: Running `pytest`, `ruff`, formatting (`scripts/format.py`), and PR validation (`scripts/validate_pr.py`).

## Versioning & Changelog
- **Version Bump**: Update version in `pyproject.toml` or `src/snippen_doorman/__init__.py` on functional changes.
- **CHANGELOG.md**: Add an entry under `## [X.Y.Z] - YYYY-MM-DD` for every version bump.
