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


def test_rtc_subcommands_parser() -> None:
    """Test argument parser for rtc sync command."""
    parser = build_parser()

    # 1. rtc sync with defaults
    sync_args = parser.parse_args(
        [
            "rtc",
            "sync",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
            "--key-slot",
            "1",
        ]
    )
    assert sync_args.subcommand == "rtc"
    assert sync_args.rtc_subcommand == "sync"
    assert sync_args.address == "AA:BB:CC:DD:EE:FF"
    assert sync_args.key == "0123456789abcdef0123456789abcdef"
    assert sync_args.key_slot == 1
    assert sync_args.rtc_time is None

    # 2. rtc sync with explicit ISO time
    sync_time_args = parser.parse_args(
        [
            "rtc",
            "sync",
            "--address",
            "AA:BB:CC:DD:EE:FF",
            "--key",
            "0123456789abcdef0123456789abcdef",
            "--time",
            "2026-10-09T14:30:00",
        ]
    )
    assert sync_time_args.rtc_time == "2026-10-09T14:30:00"


def test_run_rtc_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Test run_rtc_command execution."""
    import asyncio
    from unittest.mock import AsyncMock

    from snippen_doorman.main import run_rtc_command

    mock_client = AsyncMock()
    mock_client.set_rtc = AsyncMock(return_value=1791439200)
    mock_client.disconnect = AsyncMock()

    monkeypatch.setattr("snippen_doorman.main.YaleLockClient", lambda **kwargs: mock_client)

    # 1. Successful rtc sync
    asyncio.run(
        run_rtc_command(
            action="sync",
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
            timestamp=datetime(2026, 10, 9, 14, 0, 0, tzinfo=UTC),
        )
    )
    mock_client.set_rtc.assert_awaited_once()
    mock_client.disconnect.assert_awaited_once()

    captured = capsys.readouterr()
    assert "Lock RTC clock synchronized successfully" in captured.out
    assert "1791439200" in captured.out

    # 2. Unknown action raises ValueError
    with pytest.raises(ValueError, match="Unknown RTC action"):
        asyncio.run(
            run_rtc_command(
                action="invalid",
                address="AA:BB:CC:DD:EE:FF",
                key="0123456789abcdef0123456789abcdef",
                slot=1,
            )
        )


def test_service_parser() -> None:
    """Test argument parser for service run and sync-once."""
    parser = build_parser()

    # service run
    run_args = parser.parse_args(
        [
            "service",
            "run",
            "--api-url",
            "https://example.com/wp-json/snippen/v1/door",
            "--api-token",
            "secret123",
            "--interval",
            "30.0",
            "--storage",
            "json",
            "--json-path",
            "test_state.json",
            "--no-auto-pin",
        ]
    )
    assert run_args.subcommand == "service"
    assert run_args.service_subcommand == "run"
    assert run_args.api_url == "https://example.com/wp-json/snippen/v1/door"
    assert run_args.api_token == "secret123"
    assert run_args.interval == 30.0
    assert run_args.storage == "json"
    assert run_args.json_path == "test_state.json"
    assert run_args.auto_pin is False

    # service sync-once
    sync_args = parser.parse_args(
        [
            "service",
            "sync-once",
            "--storage",
            "sqlite",
        ]
    )
    assert sync_args.subcommand == "service"
    assert sync_args.service_subcommand == "sync-once"
    assert sync_args.storage == "sqlite"


def test_run_service_command(capsys: pytest.CaptureFixture) -> None:
    """Test run_service_command execution for sync-once and error handling."""
    import asyncio
    from unittest.mock import patch

    from snippen_doorman.main import run_service_command
    from snippen_doorman.poller import PollTickResult

    mock_result = PollTickResult(
        added=["101"],
        updated=[],
        removed=[],
        unchanged=["102"],
        errors=[],
    )

    with patch("snippen_doorman.main.BookingPoller") as mock_poller_cls:
        instance = mock_poller_cls.return_value
        instance.poll_once.return_value = mock_result

        asyncio.run(
            run_service_command(
                action="sync-once",
                api_url="https://example.com",
                api_token="token",
                interval_seconds=60.0,
                timeout_seconds=10.0,
                storage_type="memory",
                database_path=":memory:",
                json_path="",
                auto_generate_pin=True,
            )
        )

        captured = capsys.readouterr()
        assert "Synchronization Summary" in captured.out
        assert "Added:     1 (101)" in captured.out
        assert "Unchanged: 1" in captured.out

    with pytest.raises(ValueError, match="Unknown service action"):
        asyncio.run(
            run_service_command(
                action="invalid_action",
                api_url="https://example.com",
                api_token=None,
                interval_seconds=60.0,
                timeout_seconds=10.0,
                storage_type="memory",
                database_path=":memory:",
                json_path="",
            )
        )


def test_main_cli_service_sync_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Test main_cli execution of service sync-once."""
    from unittest.mock import patch

    from snippen_doorman.poller import PollTickResult

    mock_result = PollTickResult(added=["200"], updated=[], removed=[], unchanged=[], errors=[])

    with patch("snippen_doorman.main.BookingPoller") as mock_poller_cls:
        instance = mock_poller_cls.return_value
        instance.poll_once.return_value = mock_result

        main_cli(["service", "sync-once", "--storage", "memory"])

        captured = capsys.readouterr()
        assert "Synchronization Summary" in captured.out
        assert "Added:     1 (200)" in captured.out
