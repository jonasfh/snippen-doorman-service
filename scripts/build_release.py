#!/usr/bin/env python3
"""Release packaging and checksum generation utility for Snippen Doorman Service."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


def calculate_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hexadecimal digest of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def resolve_version(repo_root: Path | None = None) -> str:
    """Resolve project version from src/snippen_doorman/__init__.py."""
    base = repo_root or Path(__file__).resolve().parent.parent
    init_file = base / "src" / "snippen_doorman" / "__init__.py"
    if init_file.exists():
        match = re.search(
            r'__version__\s*=\s*["\']([^"\']+)["\']', init_file.read_text(encoding="utf-8")
        )
        if match:
            return match.group(1).strip()
    return "0.0.0"


def clean_build_artifacts(repo_root: Path, output_dir: Path) -> None:
    """Remove temporary build and distribution directories."""
    for path in [output_dir, repo_root / "build"]:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)

    for egg_info in (repo_root / "src").glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)


def build_release_packages(
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    clean: bool = True,
    verify: bool = True,
) -> dict[str, Path]:
    """Build sdist and wheel packages and generate SHA256SUMS.

    Args:
        repo_root: Repository root path (default: parent of scripts/).
        output_dir: Destination directory for artifacts (default: repo_root / 'dist').
        clean: Whether to clean previous build artifacts first.
        verify: Whether to verify sha256 checksums of built artifacts.

    Returns:
        Mapping of artifact type ('wheel', 'sdist', 'checksums') to Path.
    """
    root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
    out = (output_dir or root / "dist").resolve()

    if clean:
        clean_build_artifacts(root, out)

    out.mkdir(parents=True, exist_ok=True)
    version = resolve_version(root)

    cmd = [
        sys.executable,
        "-m",
        "build",
        "--outdir",
        str(out),
        str(root),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Package build failed with code {result.returncode}:\n{result.stderr or result.stdout}"
        )

    artifacts: dict[str, Path] = {}
    wheels = list(out.glob(f"*{version}*.whl"))
    sdists = list(out.glob(f"*{version}*.tar.gz"))

    if not wheels:
        raise FileNotFoundError(f"Expected wheel artifact not found in {out}")
    if not sdists:
        raise FileNotFoundError(f"Expected sdist artifact not found in {out}")

    artifacts["wheel"] = wheels[0]
    artifacts["sdist"] = sdists[0]

    # Generate SHA256SUMS file
    checksums_file = out / "SHA256SUMS"
    checksum_lines: list[str] = []

    for path in sorted([artifacts["wheel"], artifacts["sdist"]]):
        digest = calculate_sha256(path)
        checksum_lines.append(f"{digest}  {path.name}")

    checksums_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    artifacts["checksums"] = checksums_file

    if verify:
        verify_checksums(checksums_file)

    return artifacts


def verify_checksums(checksums_file: Path) -> bool:
    """Verify that all files in SHA256SUMS match their calculated hash."""
    parent = checksums_file.parent
    lines = checksums_file.read_text(encoding="utf-8").strip().splitlines()

    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Malformed checksum line: {line}")
        expected_hash, filename = parts[0], parts[1].strip()
        target_file = parent / filename
        if not target_file.exists():
            raise FileNotFoundError(f"Referenced file not found: {target_file}")
        actual_hash = calculate_sha256(target_file)
        if actual_hash.lower() != expected_hash.lower():
            raise ValueError(
                f"Checksum mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            )

    return True


def main() -> None:
    """CLI entrypoint for build_release.py."""
    parser = argparse.ArgumentParser(
        description="Build release packages and SHA-256 checksums for Snippen Doorman."
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("dist"),
        help="Target directory for release artifacts (default: dist/)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean build/ and dist/ prior to building.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip checksum verification.",
    )

    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent

    version = resolve_version(root)
    print(f"Building release artifacts for snippen-doorman-service v{version}...")

    artifacts = build_release_packages(
        repo_root=root,
        output_dir=args.output_dir,
        clean=not args.no_clean,
        verify=not args.no_verify,
    )

    print("\nSuccessfully built artifacts:")
    for kind, path in artifacts.items():
        size = path.stat().st_size
        print(f"  [{kind:9s}] {path.name:45s} ({size:,} bytes)")

    print(f"\nChecksums saved to: {artifacts['checksums']}")


if __name__ == "__main__":
    main()
