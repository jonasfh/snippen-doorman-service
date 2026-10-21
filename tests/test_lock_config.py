"""Unit tests for lock configuration and multi-lock parsing."""

import pytest

from snippen_doorman.ble.lock_config import LockConfig, parse_lock_configs


def test_lock_config_validation():
    valid = LockConfig(
        name="ytterdor",
        address="AA:BB:CC:DD:EE:01",
        key="0123456789abcdef0123456789abcdef",
        slot=1,
    )
    assert valid.name == "ytterdor"
    assert valid.address == "AA:BB:CC:DD:EE:01"
    assert valid.key == "0123456789abcdef0123456789abcdef"

    with pytest.raises(ValueError, match="cannot be empty"):
        LockConfig(name="invalid", address="", key="0123456789abcdef0123456789abcdef")

    with pytest.raises(ValueError, match="Invalid offline key"):
        LockConfig(name="invalid", address="AA:BB:CC:DD:EE:01", key="short_key")

    with pytest.raises(ValueError, match="Invalid key slot"):
        LockConfig(
            name="invalid",
            address="AA:BB:CC:DD:EE:01",
            key="0123456789abcdef0123456789abcdef",
            slot=0,
        )


def test_parse_single_lock_fallback():
    configs = parse_lock_configs(
        default_address="AA:BB:CC:DD:EE:FF",
        default_key="0123456789abcdef0123456789abcdef",
        default_slot=1,
    )
    assert len(configs) == 1
    assert configs[0].name == "default"
    assert configs[0].address == "AA:BB:CC:DD:EE:FF"
    assert configs[0].slot == 1


def test_parse_multi_lock_json_list():
    json_str = (
        "["
        '{"name": "ytterdor", "address": "AA:BB:CC:DD:EE:01", "key": "0123456789abcdef0123456789abcdef", "slot": 1},'
        '{"name": "fellesrom", "address": "AA:BB:CC:DD:EE:02", "key": "fedcba9876543210fedcba9876543210", "slot": 2}'
        "]"
    )
    configs = parse_lock_configs(locks_val=json_str)
    assert len(configs) == 2
    assert configs[0].name == "ytterdor"
    assert configs[0].address == "AA:BB:CC:DD:EE:01"
    assert configs[1].name == "fellesrom"
    assert configs[1].address == "AA:BB:CC:DD:EE:02"
    assert configs[1].slot == 2


def test_parse_multi_lock_comma_string():
    raw_str = (
        "ytterdor=AA:BB:CC:DD:EE:01:0123456789abcdef0123456789abcdef:1:1,"
        "fellesrom=AA:BB:CC:DD:EE:02:fedcba9876543210fedcba9876543210:2:2"
    )
    configs = parse_lock_configs(locks_val=raw_str)
    assert len(configs) == 2
    assert configs[0].name == "ytterdor"
    assert configs[0].address == "AA:BB:CC:DD:EE:01"
    assert configs[0].lock_id == 1
    assert configs[1].name == "fellesrom"
    assert configs[1].address == "AA:BB:CC:DD:EE:02"
    assert configs[1].slot == 2
    assert configs[1].lock_id == 2


def test_parse_lock_config_with_lock_id_json():
    json_str = (
        "["
        '{"name": "ytterdor", "address": "AA:BB:CC:DD:EE:01", "key": "0123456789abcdef0123456789abcdef", "slot": 1, "lock_id": 5}'
        "]"
    )
    configs = parse_lock_configs(locks_val=json_str)
    assert len(configs) == 1
    assert configs[0].lock_id == 5


def test_parse_single_lock_fallback_with_lock_id():
    configs = parse_lock_configs(
        default_address="AA:BB:CC:DD:EE:FF",
        default_key="0123456789abcdef0123456789abcdef",
        default_slot=1,
        default_lock_id=3,
    )
    assert len(configs) == 1
    assert configs[0].lock_id == 3
