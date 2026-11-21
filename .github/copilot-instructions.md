# GitHub Copilot Instructions

Follow all project rules, architectural conventions, and multi-agent role contracts defined in:
- [AGENTS.md](file:///../AGENTS.md)
- [WORKFLOW.md](file:///../.agents/common-agent-instructions/WORKFLOW.md)
- [ROLES.md](file:///../.agents/common-agent-instructions/ROLES.md)

## Quick Reminders
- Always work on a `gh-issue/<id>` branch and use Conventional Commits (`<type>[scope]: <description> (#<id>)`).
- Automatically triage task complexity (Level 1 Fast Path vs. Level 2/3 delegation) per `ROLES.md`.
- Run `python scripts/format.py`, `ruff check .`, and `pytest` before completing Python changes.

<!-- mermaid-ai-skills:start -->
## Mermaid Diagrams

When the user asks to create, edit, or visualize a diagram, follow the
instructions in `.github/instructions/mermaid.instructions.md`.
<!-- mermaid-ai-skills:end -->

## Formatting & Whitespace Hygiene

- All text, code, and markdown files must have trailing whitespaces removed.
- Files must end with a single newline (no duplicate newlines at file end).
- Run `python scripts/format.py` to format all project files.
