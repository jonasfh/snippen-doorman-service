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


def test_ensure_started_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _ensure_started correctly starts PushLock and waits for initial update."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push._running = False
        mock_push._ble_device = None
        mock_push._first_update_future = MagicMock()
        mock_push.start = AsyncMock(return_value=MagicMock())
        mock_push.wait_for_first_update = AsyncMock()
        mock_push.set_ble_device = MagicMock()
        mock_push.lock_status = LockStatus.LOCKED
        mock_push.door_status = DoorStatus.CLOSED
        mock_push.battery = 88
        mock_push.is_connected = True

        mock_device = MagicMock()
        mock_get_device = AsyncMock(return_value=mock_device)

        monkeypatch.setattr("snippen_doorman.ble.client.get_device", mock_get_device)
        monkeypatch.setattr(client, "_get_or_create_push_lock", lambda: mock_push)

        state = await client.get_status(timeout=2.0)
        mock_push.set_ble_device.assert_called_once_with(mock_device)
        mock_push.start.assert_awaited_once()
        mock_push.wait_for_first_update.assert_awaited_once_with(timeout=2.0)
        assert state.lock_status == "LOCKED"

    asyncio.run(_run())


def test_battery_state_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that BatteryState dataclass/object is converted to percentage int."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        class FakeBatteryState:
            def __init__(self, voltage: float, percentage: int):
                self.voltage = voltage
                self.percentage = percentage

        mock_push = MagicMock()
        mock_push.lock_status = LockStatus.LOCKED
        mock_push.door_status = DoorStatus.CLOSED
        mock_push.battery = FakeBatteryState(voltage=6.4, percentage=95)
        mock_push.is_connected = True

        monkeypatch.setattr(client, "_get_or_create_push_lock", lambda: mock_push)

        state = await client.get_status(timeout=1.0)
        assert state.battery == 95

    asyncio.run(_run())


def test_disconnect_and_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that disconnect and async context manager invoke cleanup."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        cancel_fn = MagicMock()
        mock_push = MagicMock()
        mock_push._execute_forced_disconnect = AsyncMock()
        client._push_lock = mock_push
        client._cancel_cb = cancel_fn

        await client.disconnect()
        cancel_fn.assert_called_once()
        mock_push._execute_forced_disconnect.assert_awaited_once_with("client disconnect")

        # Test context manager
        mock_push.reset_mock()
        cancel_fn.reset_mock()
        client._cancel_cb = cancel_fn
        monkeypatch.setattr(client, "_ensure_started", AsyncMock())

        async with client:
            pass

        cancel_fn.assert_called_once()
        mock_push._execute_forced_disconnect.assert_awaited_once_with("client disconnect")

    asyncio.run(_run())


def test_add_pin_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful PIN provisioning through 3-step sequence."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        sent_commands = []

        async def _mock_execute_raw(cmd, name, opcode, timeout=15.0):
            sent_commands.append((name, opcode))
            # Return valid 0xBB success frame
            resp = bytearray(18)
            resp[0] = 0xBB
            resp[1] = opcode
            resp[15] = 0x00
            return bytes(resp)

        monkeypatch.setattr(client, "_execute_raw_command", _mock_execute_raw)

        result = await client.add_pin(pin="123456", slot=3, name="Guest")
        assert result.pin == "123456"
        assert result.slot == 3
        assert result.name == "Guest"
        assert len(sent_commands) == 3
        assert sent_commands[0] == ("add_pin_set", 0x27)
        assert sent_commands[1] == ("add_pin_schedule", 0x2B)
        assert sent_commands[2] == ("add_pin_commit", 0x2C)

    asyncio.run(_run())


def test_add_pin_slot_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error handling when the requested slot is in use."""

    async def _run():
        from snippen_doorman.ble.pin import YalePinError

        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        async def _mock_execute_raw(cmd, name, opcode, timeout=15.0):
            resp = bytearray(18)
            resp[0] = 0xBB
            resp[1] = opcode
            if opcode == 0x2C:  # Commit fails with KEYCODE_SLOT_IN_USE (69)
                resp[15] = 69
            else:
                resp[15] = 0x00
            return bytes(resp)

        monkeypatch.setattr(client, "_execute_raw_command", _mock_execute_raw)

        with pytest.raises(YalePinError, match="KEYCODE_SLOT_IN_USE"):
            await client.add_pin(pin="123456", slot=3)

    asyncio.run(_run())


def test_delete_pin_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful PIN deletion."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        sent_commands = []

        async def _mock_execute_raw(cmd, name, opcode, timeout=15.0):
            sent_commands.append((name, opcode))
            resp = bytearray(18)
            resp[0] = 0xBB
            resp[1] = opcode
            resp[15] = 0x00
            return bytes(resp)

        monkeypatch.setattr(client, "_execute_raw_command", _mock_execute_raw)

        ok = await client.delete_pin(slot=3)
        assert ok is True
        assert len(sent_commands) == 1
        assert sent_commands[0] == ("delete_pin", 0x28)

    asyncio.run(_run())


def test_list_pins_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test querying slots to list configured PIN codes."""

    async def _run():
        from snippen_doorman.ble.pin import encode_packed_bcd_pin

        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        async def _mock_execute_raw(cmd, name, opcode, timeout=15.0):
            slot_queried = cmd[4]
            resp = bytearray(18)
            resp[0] = 0xBB
            resp[1] = opcode
            resp[4] = slot_queried
            if slot_queried == 3:
                # Slot 3 has a programmed PIN: "654321"
                resp[6:13] = encode_packed_bcd_pin("654321")
                resp[15] = 0x00
            else:
                # Other slots empty: all 0xFF
                resp[6:13] = bytes([0xFF] * 7)
                resp[15] = 0x00
            return bytes(resp)

        monkeypatch.setattr(client, "_execute_raw_command", _mock_execute_raw)

        pins = await client.list_pins(max_slots=5)
        assert len(pins) == 1
        assert pins[0].slot == 3
        assert pins[0].pin == "654321"

    asyncio.run(_run())


def test_pin_argument_validation() -> None:
    """Test argument validation for add_pin and delete_pin."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        with pytest.raises(ValueError, match="between 4 and 6"):
            await client.add_pin(pin="12", slot=1)

        with pytest.raises(ValueError, match="Slot"):
            await client.add_pin(pin="1234", slot=0)

        with pytest.raises(ValueError, match="Slot"):
            await client.delete_pin(slot=0)

    asyncio.run(_run())
