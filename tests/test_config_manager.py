"""Unit tests for ConfigManager and configuration validation."""

from __future__ import annotations

from snippen_doorman.config_manager import ConfigManager, mask_secret


def test_mask_secret() -> None:
    assert mask_secret("") == ""
    assert mask_secret("1234") == "••••"
    assert mask_secret("438b544da1ffd82510a973d5ff9853bb") == "438b••••••••53bb"


def test_load_and_update_config(tmp_path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        'SNIPPEN_DOORMAN_API_URL="https://example.com/api"\n'
        'SNIPPEN_DOORMAN_BLE_ADDRESS="98:1B:B5:0B:BB:35"\n'
        'SNIPPEN_DOORMAN_BLE_KEY="438b544da1ffd82510a973d5ff9853bb"\n'
        "SNIPPEN_DOORMAN_BLE_SLOT=2\n"
    )

    mgr = ConfigManager(env_file)
    cfg = mgr.load_config()

    assert cfg.api_url == "https://example.com/api"
    assert len(cfg.locks) == 1
    assert cfg.locks[0].address == "98:1B:B5:0B:BB:35"
    assert cfg.locks[0].slot == 2

    safe = mgr.to_safe_dict(cfg)
    assert safe["api_url"] == "https://example.com/api"
    assert "•" in safe["locks"][0]["key_masked"]

    # Test updating valid config
    ok, errors = mgr.update_config(
        {
            "lead_time_minutes": 45,
            "grace_period_minutes": 20,
            "sync_interval_seconds": 30.0,
        }
    )
    assert ok is True
    assert errors == []

    updated = mgr.load_config()
    assert updated.lead_time_minutes == 45
    assert updated.grace_period_minutes == 20
    assert updated.sync_interval_seconds == 30.0


def test_validation_errors(tmp_path) -> None:
    env_file = tmp_path / "invalid.env"
    mgr = ConfigManager(env_file)

    ok, errors = mgr.update_config(
        {
            "api_url": "invalid-url",
            "lead_time_minutes": -5,
            "locks": [
                {
                    "name": "Door",
                    "address": "not-a-mac",
                    "key": "123",
                    "slot": 1,
                    "lock_id": -1,
                }
            ],
        }
    )

    assert ok is False
    assert any("http://" in e for e in errors)
    assert any("heltall" in e for e in errors)
    assert any("MAC" in e for e in errors)
    assert any("positivt heltall" in e for e in errors)


def test_load_and_update_locks_with_lock_id(tmp_path) -> None:
    env_file = tmp_path / "locks.env"
    env_file.write_text(
        'SNIPPEN_DOORMAN_LOCKS="Hovedinngang=98:1B:B5:0B:BB:35:438b544da1ffd82510a973d5ff9853bb:2:1,Badstue=AA:BB:CC:DD:EE:02:0123456789abcdef0123456789abcdef:1:2"\n'
    )
    mgr = ConfigManager(env_file)
    cfg = mgr.load_config()
    assert len(cfg.locks) == 2
    assert cfg.locks[0].lock_id == 1
    assert cfg.locks[1].lock_id == 2

    # Update lock settings
    ok, _errors = mgr.update_config(
        {
            "locks": [
                {
                    "name": "Hovedinngang",
                    "address": "98:1B:B5:0B:BB:35",
                    "key": "438b544da1ffd82510a973d5ff9853bb",
                    "slot": 2,
                    "lock_id": 10,
                }
            ]
        }
    )
    assert ok is True
    updated = mgr.load_config()
    assert len(updated.locks) == 1
    assert updated.locks[0].lock_id == 10
