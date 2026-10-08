"""Basic unit tests for the Snippen Doorman Service CLI."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from snippen_doorman.main import (
    build_parser,
    load_env_file,
    main_cli,
    parse_iso_datetime,
)


def test_build_parser() -> None:
    """Test argument parser structure and subcommands."""
    parser = build_parser()
    args = parser.parse_args(["discover", "--timeout", "5"])
    assert args.subcommand == "discover"
    assert args.timeout == 5.0

    args = parser.parse_args(
        [
            "status",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
            "--slot",
            "2",
        ]
    )
    assert args.subcommand == "status"
    assert args.address == "AA:BB:CC:DD:EE:FF"
    assert args.key == "0123456789abcdef0123456789abcdef"
    assert args.slot == 2


def test_pin_subcommands_parser() -> None:
    """Test argument parser for pin add, delete, and list."""
    parser = build_parser()

    # pin add
    add_args = parser.parse_args(
        [
            "pin",
            "add",
            "--pin",
            "123456",
            "--slot",
            "3",
            "--from",
            "2026-10-08T12:00:00",
            "--to",
            "2026-10-08T18:00:00",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
            "--key-slot",
            "2",
        ]
    )
    assert add_args.subcommand == "pin"
    assert add_args.pin_subcommand == "add"
    assert add_args.pin == "123456"
    assert add_args.slot == 3
    assert add_args.valid_from == "2026-10-08T12:00:00"
    assert add_args.valid_to == "2026-10-08T18:00:00"
    assert add_args.address == "AA:BB:CC:DD:EE:FF"
    assert add_args.key == "0123456789abcdef0123456789abcdef"
    assert add_args.key_slot == 2

    # pin delete
    del_args = parser.parse_args(
        [
            "pin",
            "delete",
            "--slot",
            "3",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
        ]
    )
    assert del_args.subcommand == "pin"
    assert del_args.pin_subcommand == "delete"
    assert del_args.slot == 3

    # pin list
    list_args = parser.parse_args(
        [
            "pin",
            "list",
            "--max-slots",
            "15",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
        ]
    )
    assert list_args.subcommand == "pin"
    assert list_args.pin_subcommand == "list"
    assert list_args.max_slots == 15


def test_parse_iso_datetime() -> None:
    """Test parsing ISO format datetimes."""
    assert parse_iso_datetime(None) is None
    dt = parse_iso_datetime("2026-10-08T14:30:00+00:00")
    assert dt == datetime(2026, 10, 8, 14, 30, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="Invalid ISO datetime format"):
        parse_iso_datetime("invalid-date")


def test_load_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading environment variables from .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text('TEST_SNIPPEN_VAR="hello_world"\nOTHER_VAR=123\n')

    monkeypatch.delenv("TEST_SNIPPEN_VAR", raising=False)
    monkeypatch.delenv("OTHER_VAR", raising=False)

    load_env_file(env_file)

    import os

    assert os.getenv("TEST_SNIPPEN_VAR") == "hello_world"
    assert os.getenv("OTHER_VAR") == "123"


def test_main_cli_default_run() -> None:
    """Test main_cli run without subcommands (default service startup)."""
    # Should not raise exception
    main_cli([])


def test_schedule_subcommands_parser() -> None:
    """Test argument parser for schedule add, list, revoke, sync, and run."""
    parser = build_parser()

    # schedule add
    add_args = parser.parse_args(
        [
            "schedule",
            "add",
            "--booking-id",
            "res_999",
            "--pin",
            "123456",
            "--from",
            "2026-10-08T12:00:00",
            "--to",
            "2026-10-08T16:00:00",
        ]
    )
    assert add_args.subcommand == "schedule"
    assert add_args.schedule_subcommand == "add"
    assert add_args.booking_id == "res_999"
    assert add_args.pin == "123456"
    assert add_args.valid_from == "2026-10-08T12:00:00"
    assert add_args.valid_to == "2026-10-08T16:00:00"

    # schedule list
    list_args = parser.parse_args(["schedule", "list", "--status", "SCHEDULED"])
    assert list_args.subcommand == "schedule"
    assert list_args.schedule_subcommand == "list"
    assert list_args.status == "SCHEDULED"

    # schedule revoke
    rev_args = parser.parse_args(["schedule", "revoke", "--booking-id", "res_999"])
    assert rev_args.subcommand == "schedule"
    assert rev_args.schedule_subcommand == "revoke"
    assert rev_args.booking_id == "res_999"

    # schedule sync
    sync_args = parser.parse_args(["schedule", "sync", "--lead-time", "90"])
    assert sync_args.subcommand == "schedule"
    assert sync_args.schedule_subcommand == "sync"
    assert sync_args.lead_time == 90


def test_schedule_cli_execution_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test end-to-end execution of schedule add, list, sync, and revoke via main_cli."""
    db_file = str(tmp_path / "test_cli.db")

    # 1. schedule add
    main_cli(
        [
            "--database-path",
            db_file,
            "schedule",
            "add",
            "--booking-id",
            "cli_book_1",
            "--pin",
            "654321",
            "--from",
            "2026-10-08T12:00:00+00:00",
            "--to",
            "2026-10-08T14:00:00+00:00",
        ]
    )
    captured = capsys.readouterr()
    assert "PIN reservation scheduled for booking 'cli_book_1'" in captured.out

    # 2. schedule list
    main_cli(["--database-path", db_file, "schedule", "list"])
    captured = capsys.readouterr()
    assert "cli_book_1" in captured.out
    assert "SCHEDULED" in captured.out

    # 3. schedule sync (offline without lock)
    main_cli(["--database-path", db_file, "schedule", "sync"])
    captured = capsys.readouterr()
    assert "Reconciliation completed" in captured.out

    # 4. schedule revoke
    main_cli(["--database-path", db_file, "schedule", "revoke", "--booking-id", "cli_book_1"])
    captured = capsys.readouterr()
    assert "Booking 'cli_book_1' successfully revoked" in captured.out
