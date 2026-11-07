"""Unit tests for SnippenBookingClient."""

import io
import json
import urllib.error
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from snippen_doorman.booking_client import (
    BookingApiError,
    BookingAuthError,
    BookingNetworkError,
    SnippenBookingClient,
)


@pytest.fixture
def client():
    return SnippenBookingClient(
        api_url="https://example.com/wp-json/snippen/v1/door",
        api_token="test-secret-token",
        timeout_seconds=5.0,
    )


def test_url_normalization():
    c1 = SnippenBookingClient("https://example.com/wp-json")
    assert c1.base_url == "https://example.com/wp-json/snippen/v1/door"

    c2 = SnippenBookingClient("https://example.com/wp-json/snippen/v1")
    assert c2.base_url == "https://example.com/wp-json/snippen/v1/door"

    c3 = SnippenBookingClient("https://example.com/wp-json/snippen/v1/door/")
    assert c3.base_url == "https://example.com/wp-json/snippen/v1/door"


def test_fetch_bookings_success(client):
    mock_payload = {
        "bookings": [
            {
                "id": 105,
                "start_time": "2026-10-09T14:00:00Z",
                "end_time": "2026-10-09T18:00:00Z",
                "door_code": None,
            },
            {
                "id": "106",
                "start_time": "2026-10-09T19:00:00Z",
                "end_time": "2026-10-09T22:00:00Z",
                "door_code": "583921",
            },
        ]
    }
    raw_bytes = json.dumps(mock_payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        bookings = client.fetch_bookings()
        assert len(bookings) == 2
        assert bookings[0].id == "105"
        assert bookings[0].door_code is None
        assert bookings[0].start_time == datetime(2026, 10, 9, 14, 0, 0, tzinfo=UTC)
        assert bookings[1].id == "106"
        assert bookings[1].door_code == "583921"

        # Verify request headers
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test-secret-token"
        assert req.get_header("X-api-key") == "test-secret-token"


def test_fetch_bookings_skips_malformed_items(client):
    mock_payload = {
        "bookings": [
            {"id": None, "start_time": "invalid"},
            {"id": 200, "start_time": "invalid_date", "end_time": "2026-10-09T18:00:00Z"},
            {
                "id": 201,
                "start_time": "2026-10-09T14:00:00Z",
                "end_time": "2026-10-09T16:00:00Z",
                "door_code": "1234",
            },
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        bookings = client.fetch_bookings()
        assert len(bookings) == 1
        assert bookings[0].id == "201"
        assert bookings[0].door_code == "1234"


def test_update_booking_code(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"success": True, "id": 105}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        success = client.update_booking_code(105, "482910")
        assert success is True

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_method() == "PATCH"
        assert req.full_url == "https://example.com/wp-json/snippen/v1/door/bookings/105/code"
        assert json.loads(req.data.decode("utf-8")) == {"door_code": "482910"}


def test_auth_error_raised(client):
    http_error = urllib.error.HTTPError(
        url="https://example.com/wp-json/snippen/v1/door/bookings",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=io.BytesIO(b'{"error": "rest_unauthorized"}'),
    )
    with (
        patch("urllib.request.urlopen", side_effect=http_error),
        pytest.raises(BookingAuthError, match="Authentication failed"),
    ):
        client.fetch_bookings()


def test_api_server_error_raised(client):
    http_error = urllib.error.HTTPError(
        url="https://example.com/wp-json/snippen/v1/door/bookings",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=io.BytesIO(b"server crashed"),
    )
    with (
        patch("urllib.request.urlopen", side_effect=http_error),
        pytest.raises(BookingApiError, match="HTTP 500"),
    ):
        client.fetch_bookings()


def test_network_error_raised(client):
    url_err = urllib.error.URLError(reason="Connection refused")
    with (
        patch("urllib.request.urlopen", side_effect=url_err),
        pytest.raises(BookingNetworkError, match="Network communication failed"),
    ):
        client.fetch_bookings()


def test_fetch_locks_success(client):
    mock_payload = {
        "locks": [
            {
                "id": 1,
                "name": "Hovedinngang",
                "handles_objects": [
                    {"id": 1, "name": "Peisestuen"},
                    {"id": 2, "name": "Festsalen"},
                ],
            },
            {
                "id": 2,
                "name": "Badstuedør",
                "handles_objects": [{"id": 3, "name": "Badstue"}],
            },
        ]
    }
    raw_bytes = json.dumps(mock_payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        locks = client.fetch_locks()
        assert len(locks) == 2
        assert locks[0].id == 1
        assert locks[0].name == "Hovedinngang"
        assert len(locks[0].handles_objects) == 2
        assert locks[1].id == 2
        assert locks[1].name == "Badstuedør"

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "https://example.com/wp-json/snippen/v1/door/locks"


def test_fetch_locks_handles_empty_or_malformed(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"locks": [{"invalid": "lock"}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        locks = client.fetch_locks()
        assert locks == []


def test_fetch_bookings_with_lock_id(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"bookings": []}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        client.fetch_bookings(lock_id=2)
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "https://example.com/wp-json/snippen/v1/door/bookings?lock_id=2"


def test_fetch_bookings_with_include_expired_days_and_metadata(client):
    mock_payload = {
        "server_time": "2026-11-07T13:15:00Z",
        "bookings": [
            {
                "id": 101,
                "booking_ids": [101, 102],
                "booking_objects": [{"id": 1, "name": "Peisestuen"}],
                "lock_ids": [1],
                "start_time": "2026-11-07T15:00:00Z",
                "end_time": "2026-11-09T11:00:00Z",
                "door_code": "  123456  ",
                "door_code_updated_at": "2026-11-07T12:30:00Z",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        bookings = client.fetch_bookings(lock_id="1", include_expired_days=7)
        req = mock_urlopen.call_args[0][0]
        assert "lock_id=1" in req.full_url
        assert "include_expired_days=7" in req.full_url
        assert len(bookings) == 1
        b = bookings[0]
        assert b.id == "101"
        assert b.door_code == "123456"
        assert b.booking_ids == ["101", "102"]
        assert b.booking_objects == [{"id": 1, "name": "Peisestuen"}]
        assert b.lock_ids == ["1"]
        assert b.door_code_updated_at == datetime(2026, 11, 7, 12, 30, 0, tzinfo=UTC)


def test_push_door_status(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(
        {"success": True, "received_at": "2026-11-07T13:15:11Z"}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    payload = {"generated_at": "2026-11-07T13:15:10Z", "locks": []}
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = client.push_door_status(payload)
        assert res["success"] is True
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.full_url == "https://example.com/wp-json/snippen/v1/door/status"
        assert json.loads(req.data.decode("utf-8")) == payload
