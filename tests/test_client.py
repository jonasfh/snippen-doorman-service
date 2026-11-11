"""Unit tests for YaleLockClient module."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from yalexs_ble import DoorStatus, LockStatus
from yalexs_ble.const import OperationError
from yalexs_ble.session import AuthError, KeycodeError, OperationFailedError

from snippen_doorman.ble.client import MockLockClient, YaleLockClient, create_lock_client
from snippen_doorman.ble.pin import YalePinError


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
    """Test successful PIN provisioning delegating to PushLock.set_keycode."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        class FakePushLock:
            def __init__(self) -> None:
                self.calls: list[tuple[int, str, object, object]] = []

            async def set_keycode(
                self,
                slot: int,
                pin: str,
                start_time: object = None,
                end_time: object = None,
            ) -> None:
                self.calls.append((slot, pin, start_time, end_time))

        fake_push = FakePushLock()
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=fake_push))

        # Permanent PIN
        result = await client.add_pin(pin="123456", slot=3, name="Guest")
        assert result.pin == "123456"
        assert result.slot == 3
        assert result.name == "Guest"
        assert fake_push.calls[0] == (3, "123456", None, None)

        # Scheduled temporary PIN
        dt_from = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        dt_to = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
        result_sched = await client.add_pin(
            pin="654321", slot=4, valid_from=dt_from, valid_to=dt_to
        )
        assert result_sched.valid_from == dt_from
        assert result_sched.valid_to == dt_to
        assert fake_push.calls[1] == (4, "654321", dt_from, dt_to)

    asyncio.run(_run())


def test_add_pin_temporary_fallback_without_schedule_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test fallback to raw schedule commands when PushLock.set_keycode lacks start_time."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        class LegacyPushLock:
            async def set_keycode(self, slot: int, pin: str) -> None:
                raise AssertionError("Should not be called for temporary PIN")

            async def clear_keycode(self, slot: int) -> None:
                sent_commands.append((f"add_pin_preclear_slot_{slot}", 0x28))

        sent_commands = []

        async def _mock_execute_raw(cmd, name, opcode, timeout=15.0):
            sent_commands.append((name, opcode))
            resp = bytearray(18)
            resp[0] = 0xBB
            resp[1] = opcode
            resp[15] = 0x00
            return bytes(resp)

        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=LegacyPushLock()))
        monkeypatch.setattr(client, "_execute_raw_command", _mock_execute_raw)

        dt_from = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        dt_to = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
        result = await client.add_pin(pin="123456", slot=3, valid_from=dt_from, valid_to=dt_to)
        assert result.pin == "123456"
        assert sent_commands == [
            ("add_pin_preclear_slot_3", 0x28),
            ("add_pin_set", 0x27),
            ("add_pin_schedule", 0x2B),
            ("add_pin_commit", 0x2C),
        ]

    asyncio.run(_run())


def test_add_pin_slot_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test KeycodeError from PushLock is translated to YalePinError with numeric code."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.set_keycode = AsyncMock(
            side_effect=KeycodeError("commit_keycode", OperationError.KEYCODE_SLOT_IN_USE)
        )
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=mock_push))

        with pytest.raises(YalePinError, match="KEYCODE_SLOT_IN_USE") as excinfo:
            await client.add_pin(pin="123456", slot=3)
        assert excinfo.value.code == 69

    asyncio.run(_run())


def test_delete_pin_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful PIN deletion via PushLock.clear_keycode."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.clear_keycode = AsyncMock()
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=mock_push))

        ok = await client.delete_pin(slot=3)
        assert ok is True
        mock_push.clear_keycode.assert_awaited_once_with(3)

    asyncio.run(_run())


def test_list_pins_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test querying slots 1..max_slots-1 via PushLock.get_keycode."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        queried_slots: list[int] = []

        async def _mock_get_keycode(slot_idx: int) -> str | None:
            queried_slots.append(slot_idx)
            return "654321" if slot_idx == 3 else None

        mock_push = MagicMock()
        mock_push.get_keycode = _mock_get_keycode
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=mock_push))

        pins = await client.list_pins(max_slots=5)
        assert queried_slots == [1, 2, 3, 4]
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


def test_set_rtc_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful RTC clock synchronization via PushLock.set_rtc."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.set_rtc = AsyncMock(side_effect=lambda ts: ts)
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=mock_push))

        # 1. Default timestamp
        ts = await client.set_rtc()
        assert ts > 1_700_000_000

        # 2. Explicit timestamp
        dt = datetime(2026, 10, 9, 15, 0, 0, tzinfo=UTC)
        ts2 = await client.set_rtc(timestamp=dt)
        assert ts2 == int(dt.timestamp())
        assert mock_push.set_rtc.await_count == 2

    asyncio.run(_run())


def test_set_rtc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test OperationFailedError from PushLock.set_rtc is mapped to YalePinError."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        mock_push = MagicMock()
        mock_push.set_rtc = AsyncMock(
            side_effect=OperationFailedError("set_rtc", OperationError.KEYCODE_INVALID_ACCESS)
        )
        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=mock_push))

        with pytest.raises(YalePinError, match="KEYCODE_INVALID_ACCESS") as excinfo:
            await client.set_rtc()
        assert excinfo.value.code == OperationError.KEYCODE_INVALID_ACCESS.value

    asyncio.run(_run())


def test_add_pin_with_sync_rtc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test add_pin with sync_rtc=True executes RTC synchronization first."""

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:FF",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )

        call_order: list[str] = []

        class FakePushLock:
            async def set_rtc(self, ts: int) -> int:
                call_order.append("set_rtc")
                return ts

            async def set_keycode(
                self,
                slot: int,
                pin: str,
                start_time: object = None,
                end_time: object = None,
            ) -> None:
                call_order.append("set_keycode")

        monkeypatch.setattr(client, "_ensure_started", AsyncMock(return_value=FakePushLock()))

        result = await client.add_pin(pin="123456", slot=3, sync_rtc=True)
        assert result.pin == "123456"
        assert result.slot == 3
        assert call_order == ["set_rtc", "set_keycode"]

    asyncio.run(_run())


def test_mock_lock_client_operations() -> None:
    """Test MockLockClient adds, lists, and deletes pins in simulation mode."""

    async def _run():
        client = MockLockClient(address="00:11:22:33:44:55", lock_id=1)
        assert client.address == "00:11:22:33:44:55"
        assert client.lock_id == "1"
        assert client.is_running is True

        st = await client.get_status()
        assert st.lock_status == "locked"
        assert st.door_status == "closed"
        assert st.battery == 95

        await client.unlock()
        assert client.state.lock_status == "unlocked"

        await client.lock()
        assert client.state.lock_status == "locked"

        now = datetime.now(UTC)
        ts = await client.set_rtc(now)
        assert ts > 0

        pin_res = await client.add_pin(pin="654321", slot=3, valid_from=now)
        assert pin_res.pin == "654321"
        assert pin_res.slot == 3

        listed = await client.list_pins()
        assert len(listed) == 1
        assert listed[0].pin == "654321"

        deleted = await client.delete_pin(slot=3)
        assert deleted is True
        assert len(await client.list_pins()) == 0

        await client.disconnect()
        assert client.disconnected is True

    asyncio.run(_run())


def test_create_lock_client_mock_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test create_lock_client selects MockLockClient when requested or environment triggers it."""
    # Explicit mock
    c1 = create_lock_client(
        address="AA:BB:CC:DD:EE:01",
        key="0123456789abcdef0123456789abcdef",
        mock=True,
    )
    assert isinstance(c1, MockLockClient)

    # Via env var
    monkeypatch.setenv("SNIPPEN_DOORMAN_MOCK_BLE", "1")
    c2 = create_lock_client(
        address="AA:BB:CC:DD:EE:02",
        key="0123456789abcdef0123456789abcdef",
    )
    assert isinstance(c2, MockLockClient)


def test_yale_lock_client_delegates_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test YaleLockClient with mock=True or env var delegates seamlessly to MockLockClient."""
    monkeypatch.setenv("SNIPPEN_DOORMAN_MOCK_BLE", "true")

    async def _run():
        client = YaleLockClient(
            address="AA:BB:CC:DD:EE:03",
            key="0123456789abcdef0123456789abcdef",
            slot=1,
        )
        assert client._mock_client is not None
        assert client.state.lock_status == "UNKNOWN"

        added = await client.add_pin(pin="112233", slot=5)
        assert added.pin == "112233"
        assert added.slot == 5
        assert client.state.lock_status == "locked"

        pins = await client.list_pins()
        assert len(pins) == 1
        assert pins[0].pin == "112233"

        assert await client.delete_pin(slot=5) is True
        assert len(await client.list_pins()) == 0

        await client.disconnect()
        assert client._mock_client.disconnected is True

    asyncio.run(_run())


def test_ble_rediscovery_when_device_disappears(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that YaleLockClient re-discovers device via BleakScanner when device disappeared from BlueZ."""

    async def _run():
        client = YaleLockClient(
            address="98:1B:B5:0B:BB:35",
            key="0123456789abcdef0123456789abcdef",
            slot=4,
        )

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=bytes([0xAA, 0x27, 0x00]))

        mock_connected = MagicMock()
        mock_connected.session = mock_session

        call_count = 0

        async def _mock_ensure_connected():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                from yalexs_ble.session import YaleXSBLEError

                raise YaleXSBLEError(
                    "device 'dev_98_1B_B5_0B_BB_35' not found: The device disappeared"
                )
            return mock_connected

        mock_push = MagicMock()
        mock_push._running = True
        mock_push._ble_device = MagicMock()
        mock_push._first_update_future = None
        mock_push.wait_for_first_update = AsyncMock()
        mock_push._ensure_connected = _mock_ensure_connected
        mock_push._execute_forced_disconnect = AsyncMock()

        scanned_devices = []

        async def _mock_find_device(address, timeout=5.0):
            fresh_device = MagicMock()
            fresh_device.address = address
            scanned_devices.append(fresh_device)
            return fresh_device

        from bleak import BleakScanner

        monkeypatch.setattr(BleakScanner, "find_device_by_address", _mock_find_device)

        client._push_lock = mock_push

        cmd = bytearray([0x27, 0x00, 0x00, 0x00])
        resp = await client._execute_raw_command(cmd, "test_cmd", 0x27)
        assert resp == bytes([0xAA, 0x27, 0x00])
        # Verify it retried after re-scanning
        assert call_count == 2
        assert len(scanned_devices) == 1
        assert scanned_devices[0].address == "98:1B:B5:0B:BB:35"

    asyncio.run(_run())


def test_ble_rediscovery_on_push_lock_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that PushLock methods (e.g. delete_pin) re-discover device on BlueZ cache miss."""

    async def _run():
        client = YaleLockClient(
            address="98:1B:B5:0B:BB:35",
            key="0123456789abcdef0123456789abcdef",
            slot=4,
        )

        call_count = 0

        async def _mock_clear_keycode(slot: int) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                from yalexs_ble.session import YaleXSBLEError

                raise YaleXSBLEError(
                    "device 'dev_98_1B_B5_0B_BB_35' not found: The device disappeared"
                )

        mock_push = MagicMock()
        mock_push._running = True
        mock_push._ble_device = MagicMock()
        mock_push._first_update_future = None
        mock_push.wait_for_first_update = AsyncMock()
        mock_push.clear_keycode = _mock_clear_keycode
        mock_push._execute_forced_disconnect = AsyncMock()

        scanned_devices = []

        async def _mock_find_device(address, timeout=5.0):
            fresh_device = MagicMock()
            fresh_device.address = address
            scanned_devices.append(fresh_device)
            return fresh_device

        from bleak import BleakScanner

        monkeypatch.setattr(BleakScanner, "find_device_by_address", _mock_find_device)
        client._push_lock = mock_push

        assert await client.delete_pin(slot=3) is True
        assert call_count == 2
        assert len(scanned_devices) == 1
        mock_push.set_ble_device.assert_called_once_with(scanned_devices[0])

    asyncio.run(_run())
