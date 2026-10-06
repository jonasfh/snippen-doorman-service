"""Tests for Home Assistant log parser tool (tools/parse_ha_keys.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is on sys.path so we can import from tools
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.parse_ha_keys import (
    is_valid_hex_key,
    main,
    parse_log_content,
    update_env_file,
)


def test_is_valid_hex_key():
    """Verify hex key validation logic."""
    assert is_valid_hex_key("0123456789abcdef0123456789abcdef") is True
    assert is_valid_hex_key("0123456789ABCDEF0123456789ABCDEF") is True
    # Too short
    assert is_valid_hex_key("0123456789abcdef") is False
    # Too long
    assert is_valid_hex_key("0123456789abcdef0123456789abcdef01") is False
    # Non-hex characters
    assert is_valid_hex_key("0123456789abcdef0123456789xyz123") is False


def test_parse_log_content_json_loaded_key():
    """Verify extracting loaded offline key from JSON debug log."""
    sample_log = """
    2026-10-06 12:30:00.123 DEBUG (MainThread) [yalexs.api_async] Returned lock details:
    {
      "LockName": "Snippen Grendehus",
      "macAddress": "AA:BB:CC:DD:EE:FF",
      "serialNumber": "L26A123456",
      "OfflineKeys": {
        "loaded": [
          {
            "key": "0123456789abcdef0123456789abcdef",
            "slot": 1
          }
        ],
        "created": []
      }
    }
    """
    keys = parse_log_content(sample_log)
    assert len(keys) == 1
    k = keys[0]
    assert k.key == "0123456789abcdef0123456789abcdef"
    assert k.slot == 1
    assert k.name == "Snippen Grendehus"
    assert k.address == "AA:BB:CC:DD:EE:FF"
    assert k.serial == "L26A123456"
    assert k.source_type == "loaded"


def test_parse_log_content_python_dict_repr():
    """Verify extracting key from Python dict string representation (single quotes)."""
    sample_log = """
    DEBUG:yalexs:Lock info: {'LockName': 'Dør', 'macAddress': '11:22:33:44:55:66',
    'OfflineKeys': {'loaded': [{'key': 'aabbccddeeff00112233445566778899', 'slot': 2}]}}
    """
    keys = parse_log_content(sample_log)
    assert len(keys) == 1
    assert keys[0].key == "aabbccddeeff00112233445566778899"
    assert keys[0].slot == 2
    assert keys[0].address == "11:22:33:44:55:66"


def test_parse_log_content_slot_before_key():
    """Verify parsing where slot key precedes key property."""
    sample_log = """
    "OfflineKeys": {"loaded": [{"slot": 1, "key": "1234567890abcdef1234567890abcdef"}]}
    """
    keys = parse_log_content(sample_log)
    assert len(keys) == 1
    assert keys[0].key == "1234567890abcdef1234567890abcdef"
    assert keys[0].slot == 1


def test_parse_log_content_both_loaded_and_created():
    """Verify multiple keys are extracted without duplication."""
    sample_log = """
    "OfflineKeys": {
      "loaded": [{"key": "11111111111111111111111111111111", "slot": 1}],
      "created": [{"key": "22222222222222222222222222222222", "slot": 2}]
    }
    """
    keys = parse_log_content(sample_log)
    assert len(keys) == 2
    key_strings = {k.key for k in keys}
    assert "11111111111111111111111111111111" in key_strings
    assert "22222222222222222222222222222222" in key_strings


def test_parse_log_content_empty_or_unrelated():
    """Verify that unrelated log content returns an empty list."""
    sample_log = "2026-10-06 INFO Normal log message without any lock details."
    keys = parse_log_content(sample_log)
    assert keys == []


def test_update_env_file_new_and_existing(tmp_path: Path):
    """Verify creating and updating .env file."""
    env_file = tmp_path / ".env"

    # 1. Create fresh
    update_env_file(
        env_file,
        key="0123456789abcdef0123456789abcdef",
        slot=1,
        address="AA:BB:CC:DD:EE:FF",
    )
    content = env_file.read_text(encoding="utf-8")
    assert 'SNIPPEN_DOORMAN_BLE_KEY="0123456789abcdef0123456789abcdef"' in content
    assert "SNIPPEN_DOORMAN_BLE_SLOT=1" in content
    assert 'SNIPPEN_DOORMAN_BLE_ADDRESS="AA:BB:CC:DD:EE:FF"' in content

    # 2. Update existing file while preserving unrelated lines
    env_file.write_text(
        '# Some comment\nEXISTING_VAR=foo\nSNIPPEN_DOORMAN_BLE_KEY="old_key"\n',
        encoding="utf-8",
    )
    update_env_file(
        env_file,
        key="fedcba9876543210fedcba9876543210",
        slot=2,
    )
    updated_content = env_file.read_text(encoding="utf-8")
    assert "# Some comment" in updated_content
    assert "EXISTING_VAR=foo" in updated_content
    assert 'SNIPPEN_DOORMAN_BLE_KEY="fedcba9876543210fedcba9876543210"' in updated_content
    assert "SNIPPEN_DOORMAN_BLE_SLOT=2" in updated_content


def test_main_cli_with_file_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify CLI --log-file and --json flag."""
    log_file = tmp_path / "test_ha.log"
    log_file.write_text(
        '{"OfflineKeys": {"loaded": [{"key": "0123456789abcdef0123456789abcdef", "slot": 1}]}}',
        encoding="utf-8",
    )

    test_args = ["parse_ha_keys.py", "--log-file", str(log_file), "--json"]
    with patch.object(sys, "argv", test_args):
        ret = main()
        assert ret == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["key"] == "0123456789abcdef0123456789abcdef"
    assert data[0]["slot"] == 1


def test_main_cli_missing_file(tmp_path: Path):
    """Verify CLI returns 1 on non-existent file."""
    test_args = ["parse_ha_keys.py", "--log-file", str(tmp_path / "nonexistent.log")]
    with patch.object(sys, "argv", test_args):
        ret = main()
        assert ret == 1


def test_main_cli_no_keys_found(tmp_path: Path):
    """Verify CLI returns 1 when no keys are found."""
    log_file = tmp_path / "empty.log"
    log_file.write_text("just normal logs here", encoding="utf-8")
    test_args = ["parse_ha_keys.py", "--log-file", str(log_file)]
    with patch.object(sys, "argv", test_args):
        ret = main()
        assert ret == 1
