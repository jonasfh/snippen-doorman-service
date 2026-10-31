"""Unit and integration tests for DoormanWebServer."""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from snippen_doorman.config_manager import ConfigManager
from snippen_doorman.gpio_button import GpioButtonHandler
from snippen_doorman.web.server import DoormanWebServer


def test_web_server_endpoints(tmp_path) -> None:
    env_file = tmp_path / "web_test.env"
    env_file.write_text(
        'SNIPPEN_DOORMAN_API_URL="http://127.0.0.1:9999/door"\n'
        'SNIPPEN_DOORMAN_BLE_ADDRESS="98:1B:B5:0B:BB:35"\n'
        'SNIPPEN_DOORMAN_BLE_KEY="438b544da1ffd82510a973d5ff9853bb"\n'
    )
    cfg_mgr = ConfigManager(env_file)
    button_pressed = False

    def on_btn():
        nonlocal button_pressed
        button_pressed = True

    class MockWifiManager:
        def list_networks(self, rescan=True):
            return [{"ssid": "Snippen-Guest", "signal": 80, "security": "WPA2", "in_use": True}]

        def connect(self, ssid, password):
            return True, f"Connected to {ssid}"

        def get_status(self):
            return {"connected": True, "ssid": "Snippen-Guest", "ip": "192.168.1.50"}

    gpio_handler = GpioButtonHandler(pin=26, on_press=on_btn)
    from snippen_doorman.ble.wifi_peripheral import BleWifiPeripheral

    ble_peripheral = BleWifiPeripheral()
    server = DoormanWebServer(
        host="127.0.0.1",
        port=0,
        config_manager=cfg_mgr,
        gpio_handler=gpio_handler,
        wifi_manager=MockWifiManager(),
        ble_peripheral=ble_peripheral,
        auth_enabled=False,
    )
    server.start()

    try:
        base_url = f"http://127.0.0.1:{server._server.server_port}"

        # 1. GET /
        with urlopen(f"{base_url}/") as res:
            assert res.status == 200
            content = res.read().decode("utf-8")
            assert "Snippen Doorman Gateway" in content

        # 2. GET /api/status
        with urlopen(f"{base_url}/api/status") as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert "hostname" in data
            assert "ip" in data
            assert data["primary_lock"]["address"] == "98:1B:B5:0B:BB:35"
            assert "ble_setup_active" in data
            assert "ble_setup_remaining_seconds" in data

        # 3. GET /api/config
        with urlopen(f"{base_url}/api/config") as res:
            assert res.status == 200
            cfg_data = json.loads(res.read().decode("utf-8"))
            assert cfg_data["api_url"] == "http://127.0.0.1:9999/door"

        # 4. POST /api/config
        post_data = json.dumps({"lead_time_minutes": 90}).encode("utf-8")
        req = Request(
            f"{base_url}/api/config", data=post_data, headers={"Content-Type": "application/json"}
        )
        with urlopen(req) as res:
            assert res.status == 200
            resp_data = json.loads(res.read().decode("utf-8"))
            assert resp_data["success"] is True

        # Verify config was updated
        assert cfg_mgr.load_config().lead_time_minutes == 90

        # 5. POST /api/ble-setup
        req = Request(
            f"{base_url}/api/ble-setup", data=b"{}", headers={"Content-Type": "application/json"}
        )
        with urlopen(req) as res:
            assert res.status == 200
            assert button_pressed is True
            assert ble_peripheral.is_active is True

        # 6. GET /api/wifi/networks
        with urlopen(f"{base_url}/api/wifi/networks") as res:
            assert res.status == 200
            net_data = json.loads(res.read().decode("utf-8"))
            assert len(net_data["networks"]) == 1
            assert net_data["networks"][0]["ssid"] == "Snippen-Guest"

        # 7. POST /api/wifi/connect
        wifi_post = json.dumps({"ssid": "Snippen-Guest", "password": "pass"}).encode("utf-8")
        req = Request(
            f"{base_url}/api/wifi/connect",
            data=wifi_post,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as res:
            assert res.status == 200
            conn_data = json.loads(res.read().decode("utf-8"))
            assert conn_data["success"] is True

        # 8. Check lock status cache reflection in /api/status
        server._lock_status_cache["98:1B:B5:0B:BB:35"] = {
            "battery": 95,
            "lock_status": "LOCKED",
            "door_status": "CLOSED",
        }
        with urlopen(f"{base_url}/api/status") as res:
            assert res.status == 200
            status_data = json.loads(res.read().decode("utf-8"))
            assert status_data["primary_lock"]["battery"] == 95
            assert status_data["primary_lock"]["lock_status"] == "LOCKED"
            assert status_data["primary_lock"]["door_status"] == "CLOSED"
            assert "locks" in status_data
            assert status_data["locks_count"] == 1
            assert status_data["locks"][0]["battery"] == 95

        # 9. GET /api/remote-locks
        from unittest.mock import MagicMock, patch

        from snippen_doorman.booking_client import RemoteLock

        with patch("snippen_doorman.web.server.SnippenBookingClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.fetch_locks.return_value = [
                RemoteLock(id=1, name="Hoveddør", handles_objects=["Hoveddel"]),
                RemoteLock(id=2, name="Kjellerdør", handles_objects=["Kjeller"]),
            ]
            mock_client_cls.return_value = mock_client

            with urlopen(f"{base_url}/api/remote-locks") as res:
                assert res.status == 200
                locks_resp = json.loads(res.read().decode("utf-8"))
                assert locks_resp["success"] is True
                assert len(locks_resp["locks"]) == 2
                assert locks_resp["locks"][0]["id"] == 1
                assert locks_resp["locks"][0]["name"] == "Hoveddør"

    finally:
        server.stop()


def test_web_dashboard_tabs_html_structure(tmp_path) -> None:
    """Verify that dashboard HTML contains all four tabs and valid script bindings (#59)."""
    env_file = tmp_path / "dash_test.env"
    env_file.write_text('SNIPPEN_DOORMAN_BLE_ADDRESS="98:1B:B5:0B:BB:35"\n')
    cfg_mgr = ConfigManager(env_file)
    server = DoormanWebServer(host="127.0.0.1", port=0, config_manager=cfg_mgr, auth_enabled=False)
    server.start()

    try:
        base_url = f"http://127.0.0.1:{server._server.server_port}"
        with urlopen(f"{base_url}/") as res:
            assert res.status == 200
            html = res.read().decode("utf-8")

        # Verify all 4 tab containers exist
        assert 'id="tab-status"' in html
        assert 'id="tab-locks"' in html
        assert 'id="tab-api"' in html
        assert 'id="tab-ble"' in html

        # Verify navigation buttons with robust click handlers
        assert "showTab('status', this)" in html
        assert "showTab('locks', this)" in html
        assert "showTab('api', this)" in html
        assert "showTab('ble', this)" in html

        # Verify forms and controls exist
        assert 'id="locks-form"' in html
        assert 'id="api-form"' in html
        assert 'id="ble-setup-status"' in html

        # Verify key JavaScript functions are defined
        assert "function showTab(name, btn)" in html
        assert "function renderLocks(locks)" in html
        assert "function addLockRow()" in html
        assert "function removeLockRow(btn)" in html
        assert "function saveLocks(e)" in html
        assert "function saveApiSettings(e)" in html
        assert "function activateBleSetup()" in html

    finally:
        server.stop()


def test_web_server_discrete_multi_lock_save_and_cleanup(tmp_path) -> None:
    """Verify GET/POST /api/config handles discrete multi-lock format and preserves secrets (#59)."""
    env_file = tmp_path / "discrete_test.env"
    env_file.write_text(
        'DOORMAN_LOCK_1_NAME="Festsalen"\n'
        'DOORMAN_LOCK_1_ADDRESS="AA:BB:CC:DD:EE:01"\n'
        'DOORMAN_LOCK_1_KEY="0123456789abcdef0123456789abcdef"\n'
        "DOORMAN_LOCK_1_SLOT=4\n"
        "DOORMAN_LOCK_1_LOCK_ID=1\n"
        'DOORMAN_LOCK_2_NAME="Peisestua"\n'
        'DOORMAN_LOCK_2_ADDRESS="AA:BB:CC:DD:EE:02"\n'
        'DOORMAN_LOCK_2_KEY="fedcba9876543210fedcba9876543210"\n'
        "DOORMAN_LOCK_2_SLOT=2\n"
        "DOORMAN_LOCK_2_LOCK_ID=1\n"
    )
    cfg_mgr = ConfigManager(env_file)
    server = DoormanWebServer(host="127.0.0.1", port=0, config_manager=cfg_mgr, auth_enabled=False)
    server.start()

    try:
        base_url = f"http://127.0.0.1:{server._server.server_port}"

        # 1. GET /api/config should load both discrete locks with masked keys
        with urlopen(f"{base_url}/api/config") as res:
            assert res.status == 200
            cfg_data = json.loads(res.read().decode("utf-8"))
            assert len(cfg_data["locks"]) == 2
            assert cfg_data["locks"][0]["name"] == "Festsalen"
            assert cfg_data["locks"][0]["lock_id"] == 1
            assert "•" in cfg_data["locks"][0]["key_masked"]
            assert cfg_data["locks"][1]["name"] == "Peisestua"
            assert cfg_data["locks"][1]["lock_id"] == 1

        # 2. POST /api/config sending back masked keys and updated slot/name
        updated_locks_payload = {
            "locks": [
                {
                    "name": "Festsalen Hovedinngang",
                    "address": "AA:BB:CC:DD:EE:01",
                    "key": cfg_data["locks"][0]["key_masked"],  # Masked key
                    "slot": 5,
                    "lock_id": 1,
                },
                {
                    "name": "Peisestua",
                    "address": "AA:BB:CC:DD:EE:02",
                    "key": cfg_data["locks"][1]["key_masked"],  # Masked key
                    "slot": 2,
                    "lock_id": 1,
                },
            ]
        }
        req = Request(
            f"{base_url}/api/config",
            data=json.dumps(updated_locks_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as res:
            assert res.status == 200
            resp = json.loads(res.read().decode("utf-8"))
            assert resp["success"] is True

        # Verify disk persistence kept secrets uncorrupted and updated slot
        fresh_cfg = cfg_mgr.load_config()
        assert len(fresh_cfg.locks) == 2
        assert fresh_cfg.locks[0].name == "Festsalen Hovedinngang"
        assert fresh_cfg.locks[0].slot == 5
        assert fresh_cfg.locks[0].key == "0123456789abcdef0123456789abcdef"
        assert fresh_cfg.locks[1].key == "fedcba9876543210fedcba9876543210"

        # Verify discrete environment variables in env file
        env_content = env_file.read_text(encoding="utf-8")
        assert 'DOORMAN_LOCK_1_NAME="Festsalen Hovedinngang"' in env_content
        assert 'DOORMAN_LOCK_1_SLOT="5"' in env_content
        assert 'DOORMAN_LOCK_2_NAME="Peisestua"' in env_content

        # 3. Reduce to 1 lock: DOORMAN_LOCK_2_* must be cleanly purged
        single_lock_payload = {
            "locks": [
                {
                    "name": "Festsalen Hovedinngang",
                    "address": "AA:BB:CC:DD:EE:01",
                    "key": "••••••••••••••••••••••••••••••••",
                    "slot": 5,
                    "lock_id": 1,
                }
            ]
        }
        req2 = Request(
            f"{base_url}/api/config",
            data=json.dumps(single_lock_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req2) as res:
            assert res.status == 200

        after_content = env_file.read_text(encoding="utf-8")
        assert "DOORMAN_LOCK_1_NAME" in after_content
        assert "DOORMAN_LOCK_2_NAME" not in after_content
        assert "DOORMAN_LOCK_2_ADDRESS" not in after_content

        final_cfg = cfg_mgr.load_config()
        assert len(final_cfg.locks) == 1
        assert final_cfg.locks[0].name == "Festsalen Hovedinngang"

    finally:
        server.stop()


def test_web_server_http_basic_auth(tmp_path) -> None:
    """Verify HTTP Basic Authentication prompts, rejects invalid credentials, and enforces password changes (#58)."""
    env_file = tmp_path / "auth_test.env"
    env_file.write_text(
        'SNIPPEN_DOORMAN_ADMIN_PASSWORD="superSecretPassword"\n'
        'SNIPPEN_DOORMAN_BLE_ADDRESS="98:1B:B5:0B:BB:35"\n'
    )
    cfg_mgr = ConfigManager(env_file)
    # Default auth_enabled=True
    server = DoormanWebServer(host="127.0.0.1", port=0, config_manager=cfg_mgr)
    server.start()

    def make_auth_header(username: str, password: str) -> dict[str, str]:
        creds = base64.b64encode(f"{username}:{password}".encode()).decode("utf-8")
        return {"Authorization": f"Basic {creds}"}

    try:
        base_url = f"http://127.0.0.1:{server._server.server_port}"

        # 1. Unauthenticated request to / must return 401 with WWW-Authenticate header
        try:
            urlopen(f"{base_url}/")
            raise AssertionError("Should have raised HTTPError 401")
        except HTTPError as err:
            assert err.code == 401
            assert 'Basic realm="Snippen Doorman Admin"' in err.headers.get("WWW-Authenticate", "")
            data = json.loads(err.read().decode("utf-8"))
            assert data["error"] == "Unauthorized"

        # 2. Unauthenticated request to /api/status must also return 401
        try:
            urlopen(f"{base_url}/api/status")
            raise AssertionError("Should have raised HTTPError 401")
        except HTTPError as err:
            assert err.code == 401

        # 3. Wrong password must return 401
        bad_req = Request(f"{base_url}/api/status", headers=make_auth_header("admin", "wrongPass"))
        try:
            urlopen(bad_req)
            raise AssertionError("Should have raised HTTPError 401")
        except HTTPError as err:
            assert err.code == 401

        # 4. Correct credentials must succeed (200)
        good_req = Request(
            f"{base_url}/api/status",
            headers=make_auth_header("admin", "superSecretPassword"),
        )
        with urlopen(good_req) as res:
            assert res.status == 200
            status_data = json.loads(res.read().decode("utf-8"))
            assert "hostname" in status_data

        # 5. OPTIONS preflight request must return 204 without auth
        opts_req = Request(f"{base_url}/api/status", method="OPTIONS")
        with urlopen(opts_req) as res:
            assert res.status == 204

        # 6. Change admin password via POST /api/config
        update_payload = json.dumps({"admin_password": "newSecurePassword2026"}).encode("utf-8")
        post_req = Request(
            f"{base_url}/api/config",
            data=update_payload,
            headers={
                **make_auth_header("admin", "superSecretPassword"),
                "Content-Type": "application/json",
            },
        )
        with urlopen(post_req) as res:
            assert res.status == 200

        # 7. Old password must now be rejected with 401
        old_req = Request(
            f"{base_url}/api/config",
            headers=make_auth_header("admin", "superSecretPassword"),
        )
        try:
            urlopen(old_req)
            raise AssertionError("Should have raised HTTPError 401 with old password")
        except HTTPError as err:
            assert err.code == 401

        # 8. New password must succeed with 200
        new_req = Request(
            f"{base_url}/api/config",
            headers=make_auth_header("admin", "newSecurePassword2026"),
        )
        with urlopen(new_req) as res:
            assert res.status == 200
            cfg_data = json.loads(res.read().decode("utf-8"))
            assert cfg_data["admin_password_configured"] is True

    finally:
        server.stop()


def test_ensure_tls_certificate_and_ssl_context(tmp_path) -> None:
    """Verify automatic generation of self-signed X.509 certificate, SAN entries, and idempotence (#68)."""
    import ipaddress
    import stat

    from cryptography import x509

    from snippen_doorman.web.tls import create_ssl_context, ensure_tls_certificate

    cert_file = tmp_path / "tls" / "cert.pem"
    key_file = tmp_path / "tls" / "key.pem"

    c_path, k_path = ensure_tls_certificate(
        cert_path=cert_file,
        key_path=key_file,
        extra_hosts=["192.168.10.42", "custom-gateway.local"],
    )
    assert c_path.is_file()
    assert k_path.is_file()

    # Check private key permissions (0600)
    key_mode = stat.S_IMODE(k_path.stat().st_mode)
    assert key_mode == 0o600

    # Parse generated certificate and verify SANs
    cert = x509.load_pem_x509_certificate(c_path.read_bytes())
    san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    dns_names = san_ext.value.get_values_for_type(x509.DNSName)
    ip_addrs = san_ext.value.get_values_for_type(x509.IPAddress)

    assert "localhost" in dns_names
    assert "snippen-doorman-service.local" in dns_names
    assert "custom-gateway.local" in dns_names
    assert ipaddress.ip_address("127.0.0.1") in ip_addrs
    assert ipaddress.ip_address("192.168.10.42") in ip_addrs

    # Verify idempotence (existing files are reused without overwriting)
    first_mtime = c_path.stat().st_mtime_ns
    first_bytes = c_path.read_bytes()
    c_path2, _ = ensure_tls_certificate(cert_path=cert_file, key_path=key_file)
    assert c_path2.read_bytes() == first_bytes
    assert c_path2.stat().st_mtime_ns == first_mtime

    # Verify SSLContext loads certificate and key cleanly
    ctx = create_ssl_context(c_path, k_path)
    assert ctx is not None


def test_web_server_https_tls_enabled(tmp_path) -> None:
    """Verify DoormanWebServer serves HTTPS when tls_enabled=True (#68)."""
    import ssl

    env_file = tmp_path / "tls_test.env"
    env_file.write_text('SNIPPEN_DOORMAN_BLE_ADDRESS="98:1B:B5:0B:BB:35"\n')
    cfg_mgr = ConfigManager(env_file)
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"

    server = DoormanWebServer(
        host="127.0.0.1",
        port=0,
        config_manager=cfg_mgr,
        auth_enabled=False,
        tls_enabled=True,
        tls_cert_path=cert_file,
        tls_key_path=key_file,
    )
    assert server.scheme == "https"
    server.start()

    try:
        assert cert_file.is_file()
        assert key_file.is_file()
        base_url = f"https://127.0.0.1:{server._server.server_port}"

        unverified_ctx = ssl.create_default_context()
        unverified_ctx.check_hostname = False
        unverified_ctx.verify_mode = ssl.CERT_NONE

        with urlopen(f"{base_url}/api/status", context=unverified_ctx) as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert data["tls_enabled"] is True
            assert "version" in data

        with urlopen(f"{base_url}/", context=unverified_ctx) as res:
            assert res.status == 200
            html = res.read().decode("utf-8")
            assert "Snippen Doorman Gateway" in html
            assert 'id="sys-tls"' in html
    finally:
        server.stop()
