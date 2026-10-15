"""Contract tests for Web Config frontend and WebServer static serving."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from snippen_doorman.ble.wifi_peripheral import (
    CHAR_COMMAND_UUID,
    CHAR_CONFIG_UUID,
    CHAR_STATUS_UUID,
    SERVICE_UUID,
)
from snippen_doorman.config_manager import ConfigManager
from snippen_doorman.web.server import DoormanWebServer


def test_web_config_files_exist() -> None:
    """Verify all required PWA web-config files are present."""
    base_dir = Path(__file__).resolve().parent.parent / "tools" / "web-config"
    assert (base_dir / "index.html").is_file()
    assert (base_dir / "manifest.json").is_file()
    assert (base_dir / "sw.js").is_file()
    assert (base_dir / "css" / "styles.css").is_file()
    assert (base_dir / "js" / "ble.js").is_file()
    assert (base_dir / "js" / "app.js").is_file()
    assert (base_dir / "assets" / "icon.svg").is_file()


def test_manifest_json_validity() -> None:
    """Verify manifest.json parses as valid JSON with required fields."""
    base_dir = Path(__file__).resolve().parent.parent / "tools" / "web-config"
    manifest_data = json.loads((base_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["short_name"] == "Doorman BLE"
    assert manifest_data["display"] == "standalone"
    assert len(manifest_data["icons"]) >= 1


def test_ble_uuid_contract() -> None:
    """Verify JS UUIDs in ble.js match Python BLE peripheral constants."""
    base_dir = Path(__file__).resolve().parent.parent / "tools" / "web-config"
    ble_js = (base_dir / "js" / "ble.js").read_text(encoding="utf-8")
    assert SERVICE_UUID in ble_js
    assert CHAR_CONFIG_UUID in ble_js
    assert CHAR_STATUS_UUID in ble_js
    assert CHAR_COMMAND_UUID in ble_js


def test_server_serves_web_config_assets(tmp_path: Path) -> None:
    """Verify DoormanWebServer serves web-config static files with correct content types."""
    env_file = tmp_path / "web_config_test.env"
    env_file.write_text("SNIPPEN_DOORMAN_API_URL='http://test.local'\n")
    cfg_mgr = ConfigManager(env_file)

    server = DoormanWebServer(
        host="127.0.0.1",
        port=0,
        config_manager=cfg_mgr,
    )
    server.start()

    try:
        port = server._server.server_port
        base = f"http://127.0.0.1:{port}"

        # 1. /web-config redirects/serves index.html
        with urlopen(f"{base}/web-config") as res:
            assert res.status == 200
            assert "text/html" in res.headers.get("Content-Type", "")
            body = res.read().decode("utf-8")
            assert "Snippen Doorman | WiFi Oppsett" in body

        # 2. /web-config/js/ble.js serves JavaScript
        with urlopen(f"{base}/web-config/js/ble.js") as res:
            assert res.status == 200
            assert "javascript" in res.headers.get("Content-Type", "")
            js_body = res.read().decode("utf-8")
            assert "SnippenBLEClient" in js_body

        # 3. /web-config/css/styles.css serves CSS
        with urlopen(f"{base}/web-config/css/styles.css") as res:
            assert res.status == 200
            assert "text/css" in res.headers.get("Content-Type", "")

        # 4. /web-config/nonexistent returns 404
        from urllib.error import HTTPError

        try:
            urlopen(f"{base}/web-config/missing.png")
            assert False, "Should have raised HTTP 404"
        except HTTPError as exc:
            assert exc.code == 404

    finally:
        server.stop()
