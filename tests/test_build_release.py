"""Tests for release packaging and checksum calculation utility."""

import hashlib
from pathlib import Path

import pytest

from scripts.build_release import (
    calculate_sha256,
    clean_build_artifacts,
    resolve_version,
    verify_checksums,
)


def test_calculate_sha256(tmp_path: Path) -> None:
    """Test SHA-256 calculation against known data."""
    test_file = tmp_path / "sample.txt"
    content = b"Snippen Doorman Test Content"
    test_file.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert calculate_sha256(test_file) == expected


def test_resolve_version() -> None:
    """Test resolving project version from src/snippen_doorman/__init__.py."""
    version = resolve_version()
    assert version != "0.0.0"
    assert len(version.split(".")) >= 3


def test_verify_checksums_valid(tmp_path: Path) -> None:
    """Test verify_checksums returns True on matching files."""
    f1 = tmp_path / "pkg.whl"
    f2 = tmp_path / "pkg.tar.gz"
    f1.write_bytes(b"wheel content")
    f2.write_bytes(b"sdist content")

    h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
    h2 = hashlib.sha256(f2.read_bytes()).hexdigest()

    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text(f"{h1}  pkg.whl\n{h2}  pkg.tar.gz\n", encoding="utf-8")

    assert verify_checksums(checksum_file) is True


def test_verify_checksums_mismatch(tmp_path: Path) -> None:
    """Test verify_checksums raises ValueError on checksum mismatch."""
    f1 = tmp_path / "pkg.whl"
    f1.write_bytes(b"original content")

    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text("0123456789abcdef  pkg.whl\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify_checksums(checksum_file)


def test_verify_checksums_missing_file(tmp_path: Path) -> None:
    """Test verify_checksums raises FileNotFoundError if referenced file is absent."""
    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text("0123456789abcdef  nonexistent.whl\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        verify_checksums(checksum_file)


def test_clean_build_artifacts(tmp_path: Path) -> None:
    """Test clean_build_artifacts deletes dist, build, and egg-info."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    egg_info = repo / "src" / "pkg.egg-info"
    egg_info.mkdir()
    build_dir = repo / "build"
    build_dir.mkdir()
    dist_dir = repo / "dist"
    dist_dir.mkdir()

    clean_build_artifacts(repo, dist_dir)
    assert not egg_info.exists()
    assert not build_dir.exists()
    assert not dist_dir.exists()
