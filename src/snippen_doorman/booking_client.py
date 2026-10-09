"""HTTP client communicating with the Snippen Booking REST API (spec #351)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from snippen_doorman import __version__
from snippen_doorman.state.models import parse_utc_iso

logger = logging.getLogger(__name__)


class BookingClientError(Exception):
    """Base exception for Snippen Booking API client errors."""


class BookingAuthError(BookingClientError):
    """Authentication or authorization failure (HTTP 401 / 403)."""


class BookingNetworkError(BookingClientError):
    """Network connection, DNS, or timeout failure."""


class BookingApiError(BookingClientError):
    """API server response error (non-2xx)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RemoteBooking:
    """Represents a reservation fetched from the Snippen Booking platform."""

    id: str
    start_time: datetime
    end_time: datetime
    door_code: str | None = None

    def __post_init__(self) -> None:
        self.id = str(self.id)
        if self.start_time.tzinfo is None:
            self.start_time = self.start_time.replace(tzinfo=UTC)
        else:
            self.start_time = self.start_time.astimezone(UTC)
        if self.end_time.tzinfo is None:
            self.end_time = self.end_time.replace(tzinfo=UTC)
        else:
            self.end_time = self.end_time.astimezone(UTC)
        if self.door_code is not None:
            self.door_code = str(self.door_code).strip()


class SnippenBookingClient:
    """HTTP client communicating with the Snippen Booking WordPress REST API."""

    def __init__(
        self,
        api_url: str = "https://vestreholmensameie.no/wp-json/snippen/v1/door",
        api_token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        """Initialize client with base API URL and optional authentication token.

        Args:
            api_url: WordPress REST API base URL.
            api_token: Bearer / API token.
            timeout_seconds: Network request timeout in seconds.
        """
        raw_url = api_url.rstrip("/")
        if not raw_url.endswith("/door"):
            if raw_url.endswith("/snippen/v1"):
                raw_url = f"{raw_url}/door"
            elif raw_url.endswith("/wp-json"):
                raw_url = f"{raw_url}/snippen/v1/door"
        self.base_url = raw_url
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    def _get_url(self, path: str) -> str:
        """Construct full URL for a subpath."""
        subpath = path.lstrip("/")
        return f"{self.base_url}/{subpath}"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request against the booking API with auth headers and error handling."""
        url = self._get_url(path)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"snippen-doorman-service/{__version__}",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
            headers["X-API-Key"] = self.api_token

        data_bytes: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            data=data_bytes,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = resp.status
                raw_body = resp.read().decode("utf-8")
                if not raw_body.strip():
                    return {}
                try:
                    return json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Failed to decode JSON from %s (status %d): %s", url, status_code, exc
                    )
                    raise BookingApiError(
                        f"Invalid JSON response from server: {raw_body[:100]}",
                        status_code=status_code,
                    ) from exc
        except urllib.error.HTTPError as exc:
            raw_err = ""
            try:
                raw_err = exc.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                raw_err = ""
            if exc.code in (401, 403):
                raise BookingAuthError(
                    f"Authentication failed ({exc.code}): {exc.reason} - {raw_err}",
                ) from exc
            raise BookingApiError(
                f"HTTP {exc.code} {exc.reason}: {raw_err}",
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BookingNetworkError(
                f"Network communication failed for {url}: {exc}",
            ) from exc

    def fetch_bookings(self) -> list[RemoteBooking]:
        """Fetch current and upcoming reservations from Snippen Booking platform.

        Endpoint: GET /wp-json/snippen/v1/door/bookings

        Returns:
            List of RemoteBooking instances.
        """
        response = self._request("GET", "bookings")
        bookings_data = (
            response.get("bookings", response) if isinstance(response, dict) else response
        )
        if not isinstance(bookings_data, list):
            logger.warning("Unexpected response format from bookings endpoint: %r", response)
            return []

        results: list[RemoteBooking] = []
        for item in bookings_data:
            if not isinstance(item, dict):
                continue
            booking_id = item.get("id")
            start_str = item.get("start_time")
            end_str = item.get("end_time")
            if booking_id is None or not start_str or not end_str:
                logger.warning("Skipping malformed booking item: %r", item)
                continue
            start_dt = parse_utc_iso(start_str)
            end_dt = parse_utc_iso(end_str)
            if start_dt is None or end_dt is None:
                logger.warning("Skipping booking with unparseable timestamps: %r", item)
                continue
            door_code = item.get("door_code")
            results.append(
                RemoteBooking(
                    id=str(booking_id),
                    start_time=start_dt,
                    end_time=end_dt,
                    door_code=str(door_code) if door_code is not None else None,
                )
            )
        return results

    def update_booking_code(self, booking_id: int | str, door_code: str | None) -> bool:
        """Update or clear assigned door code for a booking.

        Endpoint: PATCH /wp-json/snippen/v1/door/bookings/{id}/code

        Args:
            booking_id: The booking identifier.
            door_code: 4-6 digit numeric code or None to clear.

        Returns:
            True if the update was accepted by the server.
        """
        payload = {"door_code": door_code}
        path = f"bookings/{booking_id}/code"
        res = self._request("PATCH", path, payload=payload)
        if isinstance(res, dict) and res.get("success") is True:
            return True
        return True
