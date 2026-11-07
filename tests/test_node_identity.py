"""Unit tests for node and service identity resolution (issue #76)."""

from snippen_doorman.node_identity import (
    NodeIdentity,
    get_local_hostname,
    get_local_ip,
    get_mac_address,
    resolve_node_identity,
)


def test_node_identity_to_service_dict():
    identity = NodeIdentity(
        service_id="grendehus-node",
        service_name="Grendehuset (Hovedbygg)",
        hostname="snippen-pi-grendehus",
        ip_address="192.168.1.120",
        mac_address="d8:3a:dd:12:34:56",
        version="0.20.0",
        lock_ids=["1", "2"],
    )

    data = identity.to_service_dict()
    assert data == {
        "id": "grendehus-node",
        "name": "Grendehuset (Hovedbygg)",
        "version": "0.20.0",
        "hostname": "snippen-pi-grendehus",
        "ip_address": "192.168.1.120",
        "mac_address": "d8:3a:dd:12:34:56",
        "lock_ids": ["1", "2"],
    }


def test_resolve_explicit_parameters():
    identity = resolve_node_identity(
        service_id="custom-service",
        service_name="Custom Service Name",
        hostname="custom-host",
        ip_address="10.0.0.42",
        mac_address="aa:bb:cc:dd:ee:ff",
        lock_ids=[1, "2", None],
        version="1.2.3",
    )

    assert identity.service_id == "custom-service"
    assert identity.service_name == "Custom Service Name"
    assert identity.hostname == "custom-host"
    assert identity.ip_address == "10.0.0.42"
    assert identity.mac_address == "aa:bb:cc:dd:ee:ff"
    assert identity.version == "1.2.3"
    assert identity.lock_ids == ["1", "2"]


def test_resolve_from_environment():
    env = {
        "SNIPPEN_DOORMAN_SERVICE_ID": "env-service-node",
        "SNIPPEN_DOORMAN_SERVICE_NAME": "Env Door Display",
    }
    identity = resolve_node_identity(
        env=env,
        hostname="host-node",
        ip_address="192.168.1.15",
        mac_address="00:11:22:33:44:55",
    )

    assert identity.service_id == "env-service-node"
    assert identity.service_name == "Env Door Display"
    assert identity.hostname == "host-node"


def test_fallback_to_mac_address():
    # If no service_id is provided, should fallback to doorman-<mac>
    identity = resolve_node_identity(
        service_id=None,
        service_name=None,
        mac_address="D8:3A:DD:12:34:56",
        hostname="snippen-pi",
        env={},
    )

    assert identity.service_id == "doorman-d83add123456"
    assert identity.service_name == "Doorman (doorman-d83add123456)"
    assert identity.mac_address == "D8:3A:DD:12:34:56"


def test_fallback_to_hostname_when_mac_unavailable():
    # If MAC is missing or zeroes, fallback to hostname
    identity = resolve_node_identity(
        service_id=None,
        service_name=None,
        mac_address="00:00:00:00:00:00",
        hostname="standalone-pi-box",
        env={},
    )

    assert identity.service_id == "standalone-pi-box"
    assert identity.service_name == "Doorman (standalone-pi-box)"


def test_fallback_to_default_node_when_hostname_is_localhost():
    identity = resolve_node_identity(
        service_id=None,
        service_name=None,
        mac_address="",
        hostname="localhost",
        env={},
    )

    assert identity.service_id == "doorman-node"
    assert identity.service_name == "Doorman (doorman-node)"


def test_auto_detection_helpers():
    host = get_local_hostname()
    assert isinstance(host, str)
    assert len(host) > 0

    ip = get_local_ip()
    assert isinstance(ip, str)
    assert len(ip) > 0

    mac = get_mac_address()
    assert isinstance(mac, str)
    assert len(mac) >= 12
