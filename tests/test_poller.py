"""Unit tests for BookingPoller reconciliation logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from snippen_doorman.booking_client import BookingNetworkError, RemoteBooking
from snippen_doorman.poller import BookingPoller, generate_secure_pin
from snippen_doorman.state import InMemoryReservationStore, ReservationRecord, ReservationStatus


@pytest.fixture
def store():
    return InMemoryReservationStore()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.fetch_bookings.return_value = []
    client.update_booking_code.return_value = True
    return client


def test_generate_secure_pin():
    pin = generate_secure_pin(6)
    assert len(pin) == 6
    assert pin.isdigit()


def test_poll_adds_new_reservations_with_auto_pin(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    mock_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="101",
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=5),
            door_code=None,
        )
    ]

    poller = BookingPoller(
        client=mock_client,
        store=store,
        auto_generate_pin=True,
        pin_generator=lambda: "445566",
    )

    result = poller.poll_once(now=now)
    assert result.added == ["101"]
    assert result.updated == []
    assert result.removed == []
    assert result.unchanged == []
    assert result.errors == []

    # Verify PATCH code was sent
    mock_client.update_booking_code.assert_called_once_with("101", "445566")

    # Verify state in store
    rec = store.get_reservation("101")
    assert rec is not None
    assert rec.pin == "445566"
    assert rec.status == ReservationStatus.ACTIVE
    assert rec.last_seen_at == now


def test_poll_adds_new_reservation_with_existing_pin(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    mock_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="102",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=3),
            door_code="789012",
        )
    ]

    poller = BookingPoller(client=mock_client, store=store, auto_generate_pin=True)
    result = poller.poll_once(now=now)

    assert result.added == ["102"]
    mock_client.update_booking_code.assert_not_called()

    rec = store.get_reservation("102")
    assert rec is not None
    assert rec.pin == "789012"
    assert rec.status == ReservationStatus.ACTIVE


def test_poll_detects_updated_reservation(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    # Pre-populate store
    rec = ReservationRecord(
        booking_id="103",
        valid_from=now + timedelta(hours=1),
        valid_to=now + timedelta(hours=3),
        pin="112233",
        status=ReservationStatus.ACTIVE,
    )
    store.save_reservation(rec)

    # Remote has changed end_time
    new_end = now + timedelta(hours=5)
    mock_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="103",
            start_time=rec.valid_from,
            end_time=new_end,
            door_code="112233",
        )
    ]

    poller = BookingPoller(client=mock_client, store=store)
    result = poller.poll_once(now=now)

    assert result.added == []
    assert result.updated == ["103"]
    assert result.unchanged == []

    updated = store.get_reservation("103")
    assert updated is not None
    assert updated.valid_to == new_end
    assert updated.status == ReservationStatus.UPDATED


def test_poll_detects_unchanged_reservation(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    rec = ReservationRecord(
        booking_id="104",
        valid_from=now + timedelta(hours=1),
        valid_to=now + timedelta(hours=3),
        pin="556677",
        status=ReservationStatus.ACTIVE,
    )
    store.save_reservation(rec)

    mock_client.fetch_bookings.return_value = [
        RemoteBooking(
            id="104",
            start_time=rec.valid_from,
            end_time=rec.valid_to,
            door_code="556677",
        )
    ]

    poller = BookingPoller(client=mock_client, store=store)
    result = poller.poll_once(now=now)

    assert result.added == []
    assert result.updated == []
    assert result.unchanged == ["104"]

    fetched = store.get_reservation("104")
    assert fetched.last_seen_at == now


def test_poll_marks_missing_reservations_as_removed(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    rec = ReservationRecord(
        booking_id="105",
        valid_from=now + timedelta(hours=1),
        valid_to=now + timedelta(hours=3),
        pin="998877",
        status=ReservationStatus.ACTIVE,
    )
    store.save_reservation(rec)

    # Remote poll returns empty list (booking cancelled or deleted)
    mock_client.fetch_bookings.return_value = []

    poller = BookingPoller(client=mock_client, store=store)
    result = poller.poll_once(now=now)

    assert result.removed == ["105"]
    assert store.get_reservation("105").status == ReservationStatus.REMOVED


def test_poll_preserves_state_on_network_failure(store, mock_client):
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
    rec = ReservationRecord(
        booking_id="106",
        valid_from=now + timedelta(hours=1),
        valid_to=now + timedelta(hours=3),
        pin="123456",
        status=ReservationStatus.ACTIVE,
    )
    store.save_reservation(rec)

    mock_client.fetch_bookings.side_effect = BookingNetworkError("Connection timed out")

    poller = BookingPoller(client=mock_client, store=store)
    result = poller.poll_once(now=now)

    assert len(result.errors) == 1
    assert "Connection timed out" in result.errors[0]
    assert result.added == []
    assert result.updated == []
    assert result.removed == []

    # Verify state is completely preserved
    persisted = store.get_reservation("106")
    assert persisted is not None
    assert persisted.status == ReservationStatus.ACTIVE
    assert persisted.pin == "123456"
