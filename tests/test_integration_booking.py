"""End-to-end integration tests using mock Snippen Booking HTTP API (spec #351)."""

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from snippen_doorman.booking_client import SnippenBookingClient
from snippen_doorman.poller import BookingPoller
from snippen_doorman.state import (
    JsonFileReservationStore,
    ReservationStatus,
    SqliteReservationStore,
)


class MockBookingApiServer:
    """Mock HTTP server simulating WordPress Snippen Booking API (spec #351)."""

    def __init__(self, token: str = "valid-secret-token") -> None:
        self.token = token
        self.bookings: list[dict] = []
        self.patch_calls: list[dict] = []
        self.status_code = 200
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress console logging

            def _check_auth(self) -> bool:
                auth = self.headers.get("Authorization", "")
                api_key = self.headers.get("X-API-Key", "")
                expected = f"Bearer {parent.token}"
                return auth == expected or api_key == parent.token

            def do_GET(self):
                if parent.status_code != 200:
                    self.send_response(parent.status_code)
                    self.end_headers()
                    self.wfile.write(b"Server error")
                    return

                if not self._check_auth():
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "rest_unauthorized"}).encode("utf-8"))
                    return

                if self.path.startswith("/wp-json/snippen/v1/door/bookings"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    resp = {"bookings": parent.bookings}
                    self.wfile.write(json.dumps(resp).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_PATCH(self):
                if parent.status_code != 200:
                    self.send_response(parent.status_code)
                    self.end_headers()
                    return

                if not self._check_auth():
                    self.send_response(401)
                    self.end_headers()
                    return

                # Path format: /wp-json/snippen/v1/door/bookings/{id}/code
                if "/code" in self.path:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length).decode("utf-8")
                    data = json.loads(body)
                    parts = self.path.strip("/").split("/")
                    booking_id = parts[-2]
                    parent.patch_calls.append({"id": booking_id, "data": data})

                    # Update in-memory booking list if item exists
                    for b in parent.bookings:
                        if str(b.get("id")) == str(booking_id):
                            b["door_code"] = data.get("door_code")

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(
                        json.dumps({"success": True, "id": booking_id}).encode("utf-8")
                    )
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)


@pytest.fixture
def mock_server():
    server = MockBookingApiServer(token="secret-token-123")
    server.start()
    yield server
    server.stop()


@pytest.mark.parametrize("store_type", ["sqlite", "json"])
def test_full_integration_lifecycle(mock_server, tmp_path, store_type):
    """Verify complete sync lifecycle: new, auto-PIN, unchanged, modified, deleted, restart, errors."""
    api_url = f"http://127.0.0.1:{mock_server.port}/wp-json/snippen/v1/door"
    client = SnippenBookingClient(api_url=api_url, api_token="secret-token-123")

    now = datetime(2026, 10, 9, 14, 0, 0, tzinfo=UTC)

    # 1. Setup mock bookings in WordPress
    start_1 = (now + timedelta(hours=1)).isoformat()
    end_1 = (now + timedelta(hours=4)).isoformat()
    start_2 = (now + timedelta(hours=5)).isoformat()
    end_2 = (now + timedelta(hours=8)).isoformat()

    mock_server.bookings = [
        {"id": 105, "start_time": start_1, "end_time": end_1, "door_code": None},
        {"id": 106, "start_time": start_2, "end_time": end_2, "door_code": "987654"},
    ]

    # Create persistent storage instance
    if store_type == "sqlite":
        store_path = tmp_path / "lifecycle.db"
        store = SqliteReservationStore(store_path)
    else:
        store_path = tmp_path / "lifecycle.json"
        store = JsonFileReservationStore(store_path)

    poller = BookingPoller(
        client=client,
        store=store,
        auto_generate_pin=True,
        pin_generator=lambda: "112233",
    )

    # --- Step 1: Initial Poll ---
    res1 = poller.poll_once(now=now)
    assert sorted(res1.added) == ["105", "106"]
    assert res1.errors == []

    # Verify PATCH called for booking 105 (had door_code: null)
    assert len(mock_server.patch_calls) == 1
    assert mock_server.patch_calls[0] == {"id": "105", "data": {"door_code": "112233"}}

    # Verify state in store
    rec_105 = store.get_reservation("105")
    assert rec_105 is not None
    assert rec_105.pin == "112233"
    assert rec_105.status == ReservationStatus.ACTIVE

    rec_106 = store.get_reservation("106")
    assert rec_106 is not None
    assert rec_106.pin == "987654"
    assert rec_106.status == ReservationStatus.ACTIVE

    # --- Step 2: Second Poll (No changes) ---
    res2 = poller.poll_once(now=now + timedelta(minutes=5))
    assert res2.added == []
    assert res2.updated == []
    assert res2.removed == []
    assert sorted(res2.unchanged) == ["105", "106"]

    # --- Step 3: Booking Modified in WordPress (time changed) ---
    new_end_1 = (now + timedelta(hours=6)).isoformat()
    mock_server.bookings[0]["end_time"] = new_end_1

    res3 = poller.poll_once(now=now + timedelta(minutes=10))
    assert res3.updated == ["105"]
    assert res3.unchanged == ["106"]

    rec_105_updated = store.get_reservation("105")
    assert rec_105_updated.status == ReservationStatus.UPDATED
    assert rec_105_updated.valid_to == datetime.fromisoformat(new_end_1)

    # --- Step 4: Booking 106 Cancelled/Deleted in WordPress ---
    mock_server.bookings.pop(1)  # Only 105 remains

    res4 = poller.poll_once(now=now + timedelta(minutes=15))
    assert res4.removed == ["106"]
    assert res4.unchanged == ["105"]

    rec_106_del = store.get_reservation("106")
    assert rec_106_del.status == ReservationStatus.REMOVED

    # --- Step 5: Server Outage / Network Failure ---
    mock_server.status_code = 500
    res5 = poller.poll_once(now=now + timedelta(minutes=20))
    assert len(res5.errors) == 1
    # Verify local state is completely intact
    assert store.get_reservation("105").status == ReservationStatus.UPDATED
    assert store.get_reservation("106").status == ReservationStatus.REMOVED

    mock_server.status_code = 200

    # --- Step 6: Service Restart Tolerance ---
    store.close()

    # Re-open fresh store and poller pointing to same database/json file
    if store_type == "sqlite":
        restarted_store = SqliteReservationStore(store_path)
    else:
        restarted_store = JsonFileReservationStore(store_path)

    restarted_poller = BookingPoller(client=client, store=restarted_store)
    res6 = restarted_poller.poll_once(now=now + timedelta(minutes=25))

    # Should detect 105 as unchanged without errors or re-adding
    assert res6.added == []
    assert res6.updated == []
    assert res6.removed == []
    assert res6.unchanged == ["105"]
    assert res6.errors == []

    restarted_store.close()
