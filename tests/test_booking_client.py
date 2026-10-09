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
