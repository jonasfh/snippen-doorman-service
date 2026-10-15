"""Unit and integration tests for DoormanWebServer."""

from __future__ import annotations

import json
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

    finally:
        server.stop()
