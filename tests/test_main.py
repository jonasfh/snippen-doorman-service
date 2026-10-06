"""Basic unit tests for the Snippen Doorman Service CLI."""

from snippen_doorman.main import build_parser, main_cli


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


def test_main_cli_default_run() -> None:
    """Test main_cli run without subcommands (default service startup)."""
    # Should not raise exception
    main_cli([])
