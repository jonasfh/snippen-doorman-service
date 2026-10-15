"""Mock HTTP server simulating WordPress Snippen Booking REST API."""

from __future__ import annotations

import json
import logging
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Self

logger = logging.getLogger(__name__)


class MockBookingApiServer:
    """Mock HTTP server simulating WordPress Snippen Booking API (spec #351).

    Supports:
    - GET /wp-json/snippen/v1/door/bookings
    - PATCH /wp-json/snippen/v1/door/bookings/{id}/code
    """

    def __init__(self, token: str = "test-integration-token", port: int = 0) -> None:
        """Initialize mock server.

        Args:
            token: Required API token (Authorization: Bearer <token> or X-API-Key: <token>).
            port: Port to bind to (0 for automatic ephemeral port).
        """
        self.token = token
        self.requested_port = port
        self.bookings: list[dict[str, Any]] = []
        self.patch_calls: list[dict[str, Any]] = []
        self.status_code: int = 200
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int = 0

    @property
    def base_url(self) -> str:
        """Return base URL for the door REST API."""
        return f"http://127.0.0.1:{self.port}/wp-json/snippen/v1/door"

    def add_booking(self, booking: dict[str, Any]) -> None:
        """Add or replace a booking in mock storage."""
        b_id = str(booking.get("id"))
        self.bookings = [b for b in self.bookings if str(b.get("id")) != b_id]
        self.bookings.append(dict(booking))

    def remove_booking(self, booking_id: str | int) -> bool:
        """Remove a booking by ID. Returns True if removed, False if not found."""
        b_id = str(booking_id)
        prev_len = len(self.bookings)
        self.bookings = [b for b in self.bookings if str(b.get("id")) != b_id]
        return len(self.bookings) < prev_len

    def get_booking(self, booking_id: str | int) -> dict[str, Any] | None:
        """Retrieve booking by ID."""
        b_id = str(booking_id)
        for b in self.bookings:
            if str(b.get("id")) == b_id:
                return b
        return None

    def clear_bookings(self) -> None:
        """Clear all bookings."""
        self.bookings.clear()

    def start(self) -> None:
        """Start the HTTP server on a background daemon thread."""
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress console logging

            def _check_auth(self) -> bool:
                auth = self.headers.get("Authorization", "")
                api_key = self.headers.get("X-API-Key", "")
                expected = f"Bearer {parent.token}"
                return auth == expected or api_key == parent.token

            def do_GET(self) -> None:
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

            def do_PATCH(self) -> None:
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

        self.server = HTTPServer(("127.0.0.1", self.requested_port), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.debug("MockBookingApiServer started on port %d", self.port)

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.debug("MockBookingApiServer stopped")

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.stop()
