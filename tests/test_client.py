"""Unit tests for YaleLockClient module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from yalexs_ble import DoorStatus, LockStatus
from yalexs_ble.session import AuthError

from snippen_doorman.ble.client import YaleLockClient


def test_client_validation() -> None:
    """Test parameter validation on client creation."""
    # Valid parameters
    client = YaleLockClient(
        address="AA:BB:CC:DD:EE:FF",
        key="0123456789abcdef0123456789abcdef",
        slot=1,
    )
    assert client.address == "AA:BB:CC:DD:EE:FF"
    assert client.key == "0123456789abcdef0123456789abcdef"
    assert client.slot == 1

    # Empty address
    with pytest.raises(ValueError, match="BLE address"):
        YaleLockClient(address="", key="0123456789abcdef0123456789abcdef")

    # Invalid key length
    with pytest.raises(ValueError, match="Offline key"):
        YaleLockClient(address="AA:BB:CC:DD:EE:FF", key="invalid_key")

    # Invalid slot
    with pytest.raises(ValueError, match="Slot"):
        YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=0,
        )


def test_initial_state() -> None:
    """Test initial uninitialized state before connection."""
    client = YaleLockClient(
        address="AA:BB:CC:DD:EE:FF",
        key="0123456789abcdef0123456789abcdef",
        slot=1,
    )
    state = client.state
    assert state.lock_status == "UNKNOWN"
    assert state.door_status == "UNKNOWN"
    assert state.battery is None
    assert state.is_connected is False


def test_get_status_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_status with mocked PushLock."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.update = AsyncMock()
        mock_push.lock_status = LockStatus.LOCKED
        mock_push.door_status = DoorStatus.CLOSED
        mock_push.battery = 90
        mock_push.is_connected = True

        monkeypatch.setattr(client, "_get_or_create_push_lock", lambda: mock_push)

        state = await client.get_status(timeout=1.0)
        assert state.lock_status == "LOCKED"
        assert state.door_status == "CLOSED"
        assert state.battery == 90
        assert state.is_connected is True
        mock_push.update.assert_awaited_once()

    asyncio.run(_run())


def test_lock_and_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test lock and unlock operations with mocked PushLock."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.lock = AsyncMock()
        mock_push.unlock = AsyncMock()
        mock_push.lock_status = LockStatus.LOCKED
        mock_push.door_status = DoorStatus.CLOSED
        mock_push.battery = 85
        mock_push.is_connected = True

        monkeypatch.setattr(client, "_get_or_create_push_lock", lambda: mock_push)

        state = await client.lock(timeout=1.0)
        mock_push.lock.assert_awaited_once()
        assert state.lock_status == "LOCKED"

        mock_push.lock_status = LockStatus.UNLOCKED
        state = await client.unlock(timeout=1.0)
        mock_push.unlock.assert_awaited_once()
        assert state.lock_status == "UNLOCKED"

    asyncio.run(_run())


def test_auth_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AuthError from yalexs_ble is handled cleanly."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.lock = AsyncMock(side_effect=AuthError("Invalid key"))

        monkeypatch.setattr(client, "_get_or_create_push_lock", lambda: mock_push)

        with pytest.raises(AuthError, match="Authentication failed"):
            await client.lock(timeout=1.0)

    asyncio.run(_run())
