"""Unit tests for scripts/validate_pr.py Conventional Commits integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_pr import check_conventional_commits

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_check_conventional_commits_pr_title_valid() -> None:
    """Valid Conventional Commit PR title passes validation."""
    assert (
        check_conventional_commits(
            REPO_ROOT,
            pr_title="feat(ci): add conventional commits validation (#89)",
        )
        is True
    )


def test_check_conventional_commits_pr_title_invalid() -> None:
    """Invalid PR title raises ValueError with clear explanation."""
    with pytest.raises(ValueError, match="Conventional Commits check failed"):
        check_conventional_commits(
            REPO_ROOT,
            pr_title="(#89) Legacy non-conventional title",
        )


def test_check_conventional_commits_noop_without_base_or_title() -> None:
    """Skipping both base_ref and pr_title succeeds as a no-op."""
    assert check_conventional_commits(REPO_ROOT) is True


def test_check_conventional_commits_missing_submodule_skips_gracefully(tmp_path: Path) -> None:
    """Gracefully skips if submodule validator is absent in an uninitialized checkout."""
    assert (
        check_conventional_commits(
            tmp_path,
            base_ref="origin/main",
            pr_title="invalid title",
        )
        is True
    )
