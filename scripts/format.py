#!/usr/bin/env python3
"""Project-wide formatting script.

Removes trailing whitespaces, ensures a single trailing newline at EOF,
removes duplicate trailing newlines across all text files, and runs ruff formatting.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IGNORED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
    "snippen_doorman_service.egg-info",
}

BINARY_EXTENSIONS = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".bin",
    ".tar",
    ".gz",
    ".zip",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}


def format_text_file(file_path: Path) -> bool:
    """Format a single text file. Returns True if modified."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False

    lines = content.splitlines()
    stripped_lines = [line.rstrip() for line in lines]

    # Remove duplicate/empty lines from the end of the file
    while stripped_lines and stripped_lines[-1] == "":
        stripped_lines.pop()

    # Ensure exactly one newline at end of non-empty files
    new_content = "\n".join(stripped_lines) + "\n" if stripped_lines else ""

    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def format_all_files(repo_root: Path) -> list[str]:
    """Scan and format all text files in repo."""
    modified: list[str] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in BINARY_EXTENSIONS:
                continue
            if format_text_file(file_path):
                modified.append(str(file_path.relative_to(repo_root)))
    return modified


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Run ruff formatting and import sorting on python files first
    import shutil

    python_bin = sys.executable
    venv_bin_dir = Path(python_bin).parent
    ruff_bin = venv_bin_dir / "ruff"
    if not ruff_bin.exists():
        candidate_paths = [
            Path("/home/vscode/.venv/bin/ruff"),
            Path(shutil.which("ruff") or ""),
            Path("ruff"),
        ]
        for candidate in candidate_paths:
            if candidate and candidate.exists():
                ruff_bin = candidate
                break

    try:
        # Sort imports
        subprocess.run(
            [str(ruff_bin), "check", "--select", "I", "--fix", str(repo_root)],
            check=True,
            capture_output=True,
        )
        # Format code (using py312 target to ensure backward compatibility for parenthesized exceptions)
        subprocess.run(
            [str(ruff_bin), "format", "--target-version", "py312", str(repo_root)],
            check=True,
            capture_output=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # 2. Format all text files (strips trailing whitespaces and enforces exactly one EOF newline)
    modified_text_files = format_all_files(repo_root)
    if modified_text_files:
        print(f"Cleaned whitespaces/newlines in {len(modified_text_files)} files:")
        for mf in sorted(modified_text_files):
            print(f"  - {mf}")
    else:
        print("All text files cleanly formatted.")


if __name__ == "__main__":
    main()
