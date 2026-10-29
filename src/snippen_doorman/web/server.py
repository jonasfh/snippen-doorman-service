"""Embedded HTTP web server providing an administrative dashboard and REST API."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import mimetypes
import socket
import threading
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from snippen_doorman.ble.client import YaleLockClient
from snippen_doorman.ble.wifi_peripheral import BleWifiPeripheral
from snippen_doorman.booking_client import SnippenBookingClient
from snippen_doorman.config_manager import ConfigManager
from snippen_doorman.db import Database
from snippen_doorman.gpio_button import GpioButtonHandler
from snippen_doorman.sync import DoormanSyncEngine
from snippen_doorman.web.html import DASHBOARD_HTML
from snippen_doorman.wifi_manager import WifiManager

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Determine the primary local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class DoormanWebServer:
    """Manages the background HTTP dashboard server for Snippen Doorman."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        config_manager: ConfigManager | None = None,
        sync_engine: DoormanSyncEngine | None = None,
        db: Database | None = None,
        gpio_handler: GpioButtonHandler | None = None,
        wifi_manager: WifiManager | None = None,
        ble_peripheral: BleWifiPeripheral | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
        auth_enabled: bool = True,
    ) -> None:
        """Initialize web server.

        Args:
            host: Bind host interface (default: '0.0.0.0').
            port: Bind TCP port (default: 8080).
            config_manager: Configuration persistence manager.
            sync_engine: Optional running sync engine instance.
            db: Optional Database instance for querying telemetry.
            gpio_handler: Optional GPIO button monitor.
            wifi_manager: NetworkManager WiFi manager instance.
            ble_peripheral: BLE WiFi peripheral setup controller.
            event_loop: Asyncio event loop used for executing BLE operations.
            auth_enabled: Whether HTTP Basic Authentication is enforced (default: True).
        """
        self.host = host
        self.port = port
        self.config_manager = config_manager or ConfigManager()
        self.sync_engine = sync_engine
        self.db = db or Database()
        self.gpio_handler = gpio_handler
        self.wifi_manager = wifi_manager or WifiManager()
        self.ble_peripheral = ble_peripheral
        self.event_loop = event_loop
        self.auth_enabled = auth_enabled
        self.start_time = datetime.now(UTC)

        self._lock_status_cache: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, str]] = deque(maxlen=40)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

        self.record_event("Web dashboard initialisert.")

    def record_event(self, msg: str) -> None:
        """Add an event line to the in-memory ring buffer."""
        now_str = datetime.now(UTC).strftime("%H:%M:%S")
        self._events.appendleft({"time": now_str, "msg": msg})
        logger.info("[EVENT] %s", msg)

    def get_events(self) -> list[dict[str, str]]:
        """Return a list of recent events."""
        return list(self._events)

    def run_coroutine(self, coro: Any, timeout: float = 25.0) -> Any:
        """Execute an async coroutine either via the provided event loop or a new loop."""
        if self.event_loop and self.event_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self.event_loop)
            return future.result(timeout=timeout)
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))

    def start(self) -> None:
        """Start the HTTP server on a daemon thread."""
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("%s - " + format, self.address_string(), *args)

            def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
                body = json.dumps(data).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, status_code: int, html_str: str) -> None:
                body = html_str.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _is_authenticated(self) -> bool:
                if not parent.auth_enabled:
                    return True
                cfg = parent.config_manager.load_config()
                expected_password = cfg.admin_password
                if not expected_password:
                    return True

                auth_header = self.headers.get("Authorization", "")
                if not auth_header.startswith("Basic "):
                    return False

                encoded = auth_header[6:].strip()
                try:
                    decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                except (ValueError, binascii.Error):
                    return False

                if ":" not in decoded:
                    return False

                _username, password = decoded.split(":", 1)
                return hmac.compare_digest(password, expected_password)

            def _send_auth_required(self) -> None:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Snippen Doorman Admin"')
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                body = json.dumps(
                    {"error": "Unauthorized", "message": "Admin-passord påkrevd"}
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.end_headers()

            def do_GET(self) -> None:
                if self.path == "/web-config" or self.path == "/web-config/":
                    self.path = "/web-config/index.html"

                if self.path.startswith("/web-config/"):
                    subpath = self.path[len("/web-config/") :].split("?")[0]
                    repo_root = Path(__file__).resolve().parents[3]
                    candidates = [
                        repo_root / "tools" / "web-config",
                        Path("/opt/snippen-doorman-service/tools/web-config"),
                        Path.cwd() / "tools" / "web-config",
                    ]
                    base_dir = next(
                        (c.resolve() for c in candidates if c.is_dir()),
                        (repo_root / "tools" / "web-config").resolve(),
                    )
                    target_file = (base_dir / subpath).resolve()
                    try:
                        target_file.relative_to(base_dir)
                    except ValueError:
                        self._send_json(403, {"error": "Forbidden"})
                        return

                    if target_file.is_file():
                        mime_type, _ = mimetypes.guess_type(str(target_file))
                        content_type = mime_type or "application/octet-stream"
                        content = target_file.read_bytes()
                        self.send_response(200)
                        if any(t in content_type for t in ("text", "javascript", "json")):
                            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                        else:
                            self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(content)))
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    else:
                        self._send_json(404, {"error": "File not found"})
                        return

                if not self._is_authenticated():
                    self._send_auth_required()
                    return

                if self.path in ("/", "/index.html"):
                    self._send_html(200, DASHBOARD_HTML)
                    return

                if self.path == "/api/status":
                    cfg = parent.config_manager.load_config()
                    uptime_delta = datetime.now(UTC) - parent.start_time
                    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    uptime_str = f"{hours}t {minutes}m {seconds}s"

                    primary_lock_info: dict[str, Any] = {}
                    if cfg.locks:
                        lk = cfg.locks[0]
                        primary_lock_info = {
                            "name": lk.name,
                            "address": lk.address,
                            "slot": lk.slot,
                        }
                        if parent.db:
                            status_rec = parent.db.get_lock_status(lk.address)
                            if status_rec:
                                primary_lock_info["battery"] = status_rec.battery
                                primary_lock_info["lock_status"] = status_rec.lock_status
                                primary_lock_info["door_status"] = status_rec.door_status
                                primary_lock_info["last_seen"] = (
                                    status_rec.last_seen.strftime("%H:%M:%S")
                                    if status_rec.last_seen
                                    else None
                                )
                        cached = parent._lock_status_cache.get(lk.address)
                        if cached:
                            for k, v in cached.items():
                                if v is not None:
                                    primary_lock_info[k] = v
                    all_locks_info: list[dict[str, Any]] = []
                    for lk in cfg.locks:
                        lk_dict: dict[str, Any] = {
                            "name": lk.name,
                            "address": lk.address,
                            "slot": lk.slot,
                            "lock_id": lk.lock_id,
                            "battery": None,
                            "lock_status": None,
                            "door_status": None,
                        }
                        if parent.db:
                            st = parent.db.get_lock_status(lk.address)
                            if st:
                                lk_dict["battery"] = st.battery
                                lk_dict["lock_status"] = st.lock_status
                                lk_dict["door_status"] = st.door_status
                        cached_lk = parent._lock_status_cache.get(lk.address)
                        if cached_lk:
                            for k, v in cached_lk.items():
                                if v is not None:
                                    lk_dict[k] = v
                        all_locks_info.append(lk_dict)

                    wifi_status = parent.wifi_manager.get_status()
                    ble_active = parent.ble_peripheral.is_active if parent.ble_peripheral else False
                    ble_remaining = (
                        parent.ble_peripheral.remaining_seconds if parent.ble_peripheral else 0
                    )
                    data = {
                        "hostname": socket.gethostname(),
                        "ip": wifi_status.get("ip") or get_local_ip(),
                        "wifi_ssid": wifi_status.get("ssid"),
                        "uptime": uptime_str,
                        "events": parent.get_events(),
                        "primary_lock": primary_lock_info,
                        "locks": all_locks_info,
                        "locks_count": len(cfg.locks),
                        "ble_setup_active": ble_active,
                        "ble_setup_remaining_seconds": ble_remaining,
                    }
                    self._send_json(200, data)
                    return

                if self.path == "/api/wifi/networks":
                    networks = parent.wifi_manager.list_networks()
                    self._send_json(200, {"networks": networks})
                    return

                if self.path == "/api/config":
                    cfg = parent.config_manager.load_config()
                    self._send_json(200, parent.config_manager.to_safe_dict(cfg))
                    return

                if self.path == "/api/remote-locks":
                    cfg = parent.config_manager.load_config()
                    client = SnippenBookingClient(
                        api_url=cfg.api_url,
                        api_token=cfg.api_token,
                        timeout_seconds=10.0,
                    )
                    try:
                        remote_locks = client.fetch_locks()
                        locks_data = [
                            {
                                "id": rl.id,
                                "name": rl.name,
                                "handles_objects": rl.handles_objects,
                            }
                            for rl in remote_locks
                        ]
                        parent.record_event(f"Hentet {len(remote_locks)} lås(er) fra Booking API.")
                        self._send_json(200, {"success": True, "locks": locks_data})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Kunne ikke hente låser fra Booking API: %s", exc)
                        parent.record_event(f"Kunne ikke hente låser fra Booking API: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc), "locks": []})
                    return

                self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if not self._is_authenticated():
                    self._send_auth_required()
                    return

                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    payload = json.loads(raw_body) if raw_body.strip() else {}
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "Invalid JSON format"})
                    return

                if self.path == "/api/config":
                    success, errors = parent.config_manager.update_config(payload)
                    if success:
                        parent.record_event("Konfigurasjonsinnstillinger oppdatert.")
                        self._send_json(200, {"success": True})
                    else:
                        self._send_json(400, {"success": False, "errors": errors})
                    return

                if self.path == "/api/test/unlock":
                    cfg = parent.config_manager.load_config()
                    if not cfg.locks:
                        self._send_json(400, {"error": "Ingen dørlås konfigurert"})
                        return
                    lk = cfg.locks[0]
                    parent.record_event(f"Sender test-opplåsingssignal til {lk.name}...")
                    try:
                        client = YaleLockClient(address=lk.address, key=lk.key, slot=lk.slot)

                        async def _unlock() -> Any:
                            async with client:
                                return await client.unlock(timeout=20.0)

                        res = parent.run_coroutine(_unlock(), timeout=25.0)
                        parent.record_event(f"Lås {lk.name} låst opp!")
                        parent._lock_status_cache[lk.address] = {
                            "battery": res.battery,
                            "lock_status": res.lock_status,
                            "door_status": res.door_status,
                        }
                        if parent.db:
                            parent.db.record_lock_status(
                                lock_address=lk.address,
                                battery=res.battery,
                                lock_status=res.lock_status,
                                door_status=res.door_status,
                            )
                        self._send_json(
                            200,
                            {
                                "success": True,
                                "battery": res.battery,
                                "lock_status": res.lock_status,
                                "door_status": res.door_status,
                            },
                        )
                    except Exception as exc:
                        logger.exception("Feil under opplåsing")
                        parent.record_event(f"Opplåsing feilet: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc)})
                    return

                if self.path == "/api/test/lock":
                    cfg = parent.config_manager.load_config()
                    if not cfg.locks:
                        self._send_json(400, {"error": "Ingen dørlås konfigurert"})
                        return
                    lk = cfg.locks[0]
                    parent.record_event(f"Sender test-låsesignal til {lk.name}...")
                    try:
                        client = YaleLockClient(address=lk.address, key=lk.key, slot=lk.slot)

                        async def _lock() -> Any:
                            async with client:
                                return await client.lock(timeout=20.0)

                        res = parent.run_coroutine(_lock(), timeout=25.0)
                        parent.record_event(f"Lås {lk.name} låst!")
                        parent._lock_status_cache[lk.address] = {
                            "battery": res.battery,
                            "lock_status": res.lock_status,
                            "door_status": res.door_status,
                        }
                        if parent.db:
                            parent.db.record_lock_status(
                                lock_address=lk.address,
                                battery=res.battery,
                                lock_status=res.lock_status,
                                door_status=res.door_status,
                            )
                        self._send_json(
                            200,
                            {
                                "success": True,
                                "battery": res.battery,
                                "lock_status": res.lock_status,
                                "door_status": res.door_status,
                            },
                        )
                    except Exception as exc:
                        logger.exception("Feil under låsing")
                        parent.record_event(f"Låsing feilet: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc)})
                    return

                if self.path == "/api/test/status":
                    cfg = parent.config_manager.load_config()
                    if not cfg.locks:
                        self._send_json(400, {"error": "Ingen dørlås konfigurert"})
                        return
                    lk = cfg.locks[0]
                    parent.record_event(f"Kobler til {lk.name} for å hente batterinivå...")
                    try:
                        client = YaleLockClient(address=lk.address, key=lk.key, slot=lk.slot)

                        async def _get_status() -> Any:
                            async with client:
                                return await client.get_status(timeout=20.0)

                        res = parent.run_coroutine(_get_status(), timeout=25.0)
                        parent._lock_status_cache[lk.address] = {
                            "battery": res.battery,
                            "lock_status": res.lock_status,
                            "door_status": res.door_status,
                        }
                        if parent.db:
                            parent.db.record_lock_status(
                                lock_address=lk.address,
                                battery=res.battery,
                                lock_status=res.lock_status,
                                door_status=res.door_status,
                            )
                        batt_str = f"{res.battery}%" if res.battery is not None else "N/A"
                        parent.record_event(f"Status mottatt: Batteri {batt_str}")
                        self._send_json(
                            200,
                            {
                                "success": True,
                                "battery": res.battery,
                                "lock_status": res.lock_status,
                                "door_status": res.door_status,
                            },
                        )
                    except Exception as exc:
                        logger.exception("Feil under statushenting")
                        parent.record_event(f"Statushenting feilet: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc)})
                    return

                if self.path == "/api/test/api":
                    cfg = parent.config_manager.load_config()
                    if not cfg.api_url:
                        self._send_json(400, {"error": "API URL er ikke konfigurert."})
                        return
                    parent.record_event(f"Tester kontakt med Booking API ({cfg.api_url})...")
                    try:
                        client = SnippenBookingClient(api_url=cfg.api_url, api_token=cfg.api_token)
                        bookings = client.get_active_bookings()
                        parent.record_event(
                            f"Booking API OK: {len(bookings)} reservasjoner funnet."
                        )
                        self._send_json(200, {"success": True, "bookings_count": len(bookings)})
                    except Exception as exc:
                        logger.exception("Feil ved test av booking API")
                        parent.record_event(f"API-feil: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc)})
                    return

                if self.path == "/api/sync":
                    if not parent.sync_engine:
                        self._send_json(
                            400, {"error": "Synkroniseringsmotor kjører ikke i denne prosessen."}
                        )
                        return
                    parent.record_event("Kjører manuell synkroniseringssyklus...")
                    try:
                        res = parent.run_coroutine(parent.sync_engine.sync_once(), timeout=40.0)
                        parent.record_event(
                            f"Synk fullført: {len(res.poll.added)} nye, {len(res.provision.activated)} aktivert, {len(res.errors)} feil"
                        )
                        self._send_json(
                            200,
                            {
                                "success": True,
                                "added": len(res.poll.added),
                                "activated": len(res.provision.activated),
                                "errors": res.errors,
                            },
                        )
                    except Exception as exc:
                        logger.exception("Feil under synk")
                        parent.record_event(f"Synkroniseringsfeil: {exc}")
                        self._send_json(500, {"success": False, "error": str(exc)})
                    return

                if self.path == "/api/ble-setup":
                    parent.record_event("Aktiverer BLE-oppsett (10 min)...")
                    if parent.ble_peripheral:
                        parent.ble_peripheral.activate()
                    if parent.gpio_handler:
                        parent.gpio_handler.trigger_button_press()
                    self._send_json(200, {"success": True, "active": True})
                    return

                if self.path == "/api/wifi/connect":
                    ssid = str(payload.get("ssid", "")).strip()
                    pwd = str(payload.get("password", "")).strip()
                    parent.record_event(f"Kobler til WiFi '{ssid}'...")
                    ok, msg = parent.wifi_manager.connect(ssid=ssid, password=pwd)
                    if ok:
                        parent.record_event(f"Vellykket tilkobling til {ssid}!")
                        self._send_json(200, {"success": True, "message": msg})
                    else:
                        parent.record_event(f"WiFi-oppkobling feilet for {ssid}: {msg}")
                        self._send_json(400, {"success": False, "error": msg})
                    return

                self._send_json(404, {"error": "Endpoint not found"})

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="doorman-web-server"
        )
        self._thread.start()
        logger.info("DoormanWebServer listening on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        """Shut down the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("DoormanWebServer stopped")
