"""Unit tests for BLE PIN protocol implementation."""

from datetime import UTC, datetime

import pytest

from snippen_doorman.ble.pin import (
    CMD_KEYCODE_ACCESS,
    CMD_KEYCODE_CLEAR,
    CMD_KEYCODE_COMMIT,
    CMD_KEYCODE_SET,
    CMD_UNITY_GET_KEYCODE,
    SCHEDULE_ALWAYS,
    SCHEDULE_TEMPORARY,
    YalePinCode,
    YalePinError,
    build_clear_pin_packet,
    build_commit_pin_packet,
    build_query_pin_packet,
    build_schedule_packet,
    build_set_pin_packet,
    calculate_august_checksum,
    check_pin_response_error,
    decode_packed_bcd_pin,
    encode_packed_bcd_pin,
)


def test_packed_bcd_encoding_decoding() -> None:
    """Test encoding and decoding of PIN codes to packed BCD."""
    # 6-digit PIN
    pin6 = "123456"
    encoded6 = encode_packed_bcd_pin(pin6)
    assert len(encoded6) == 7
    assert encoded6 == bytes([0x12, 0x34, 0x56, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded6) == pin6

    # 4-digit PIN
    pin4 = "9876"
    encoded4 = encode_packed_bcd_pin(pin4)
    assert encoded4 == bytes([0x98, 0x76, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded4) == pin4

    # 5-digit PIN (odd length)
    pin5 = "54321"
    encoded5 = encode_packed_bcd_pin(pin5)
    assert encoded5 == bytes([0x54, 0x32, 0x1F, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded5) == pin5

    # Edge cases: empty, all zeros, all 0xFF, non-BCD bytes
    assert decode_packed_bcd_pin(b"") == ""
    assert decode_packed_bcd_pin(b"\x00" * 7) == ""
    assert decode_packed_bcd_pin(b"\xff" * 7) == ""
    assert (
        decode_packed_bcd_pin(bytes([0x12, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])) == ""
    )  # 2 digits only


def test_pin_validation_errors() -> None:
    """Test validation errors for invalid PIN values."""
    with pytest.raises(ValueError, match="must not be empty"):
        encode_packed_bcd_pin("")

    with pytest.raises(ValueError, match="only digits"):
        encode_packed_bcd_pin("12a4")

    with pytest.raises(ValueError, match="between 4 and 6 digits"):
        encode_packed_bcd_pin("123")  # too short

    with pytest.raises(ValueError, match="between 4 and 6 digits"):
        encode_packed_bcd_pin("1234567")  # too long


def test_packet_builders() -> None:
    """Test construction of August 18-byte GATT packets."""
    # 1. Set PIN (0x27)
    set_pkt = build_set_pin_packet("123456")
    assert len(set_pkt) == 18
    assert set_pkt[0] == 0xEE
    assert set_pkt[1] == CMD_KEYCODE_SET
    assert set_pkt[4:7] == bytes([0x12, 0x34, 0x56])
    assert set_pkt[16:18] == bytes([0x02, 0x00])
    # August checksum verification: sum(pkt) % 256 == 0
    assert (sum(set_pkt) & 0xFF) == 0

    # 2. Schedule always (0x2B)
    sched_always = build_schedule_packet()
    assert len(sched_always) == 18
    assert sched_always[1] == CMD_KEYCODE_ACCESS
    assert sched_always[12] == SCHEDULE_ALWAYS
    assert (sum(sched_always) & 0xFF) == 0

    # 3. Schedule temporary (0x2B)
    dt_from = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    dt_to = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
    sched_temp = build_schedule_packet(valid_from=dt_from, valid_to=dt_to)

    assert sched_temp[1] == CMD_KEYCODE_ACCESS
    assert sched_temp[12] == SCHEDULE_TEMPORARY
    assert (sum(sched_temp) & 0xFF) == 0

    # Invalid schedule range
    with pytest.raises(ValueError, match="cannot be earlier"):
        build_schedule_packet(valid_from=dt_to, valid_to=dt_from)

    # 4. Commit PIN (0x2C)
    commit_pkt = build_commit_pin_packet("123456", slot=3)
    assert len(commit_pkt) == 18
    assert commit_pkt[1] == CMD_KEYCODE_COMMIT
    assert commit_pkt[11] == 3  # slot byte
    assert (sum(commit_pkt) & 0xFF) == 0

    with pytest.raises(ValueError, match="Slot"):
        build_commit_pin_packet("123456", slot=-1)

    # 5. Clear PIN (0x28)
    clear_pkt = build_clear_pin_packet(slot=3)
    assert len(clear_pkt) == 18
    assert clear_pkt[1] == CMD_KEYCODE_CLEAR
    assert clear_pkt[11] == 3
    assert (sum(clear_pkt) & 0xFF) == 0

    # 6. Query PIN (0x39)
    query_pkt = build_query_pin_packet(slot=3)
    assert len(query_pkt) == 18
    assert query_pkt[1] == CMD_UNITY_GET_KEYCODE
    assert query_pkt[4] == 3
    assert (sum(query_pkt) & 0xFF) == 0


def test_checksum_calculation() -> None:
    """Test calculate_august_checksum function."""
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = 0x0A  # CMD_UNLOCK
    pkt[16] = 0x02
    cs = calculate_august_checksum(pkt)
    pkt[3] = cs
    assert (sum(pkt) & 0xFF) == 0


def test_check_pin_response_error() -> None:
    """Test parsing and error handling of response frames."""
    # Valid success frame (0xBB, opcode 0x27, error 0x00 at byte 15)
    valid_resp = bytearray(18)
    valid_resp[0] = 0xBB
    valid_resp[1] = 0x27
    valid_resp[15] = 0x00
    check_pin_response_error(bytes(valid_resp), expected_opcode=0x27)

    # Frame too short
    with pytest.raises(YalePinError, match="Invalid response length"):
        check_pin_response_error(b"\xbb\x27", expected_opcode=0x27)

    # 0xCC is a valid response header
    valid_cc_resp = bytearray(valid_resp)
    valid_cc_resp[0] = 0xCC
    check_pin_response_error(bytes(valid_cc_resp), expected_opcode=0x27)

    # Unexpected header
    invalid_hdr = bytearray(valid_resp)
    invalid_hdr[0] = 0xDD
    with pytest.raises(YalePinError, match="Unexpected response header"):
        check_pin_response_error(bytes(invalid_hdr), expected_opcode=0x27)

    # Opcode mismatch
    with pytest.raises(YalePinError, match="Response opcode mismatch"):
        check_pin_response_error(bytes(valid_resp), expected_opcode=0x2C)

    # Slot in use error (code 69 / 0x45)
    slot_in_use_resp = bytearray(valid_resp)
    slot_in_use_resp[15] = 69
    with pytest.raises(YalePinError, match="KEYCODE_SLOT_IN_USE") as excinfo:
        check_pin_response_error(bytes(slot_in_use_resp), expected_opcode=0x27)
    assert excinfo.value.code == 69

    # Existing key error (code 6)
    existing_key_resp = bytearray(valid_resp)
    existing_key_resp[15] = 6
    with pytest.raises(YalePinError, match="KEYCODE_EXISTING_KEY") as excinfo:
        check_pin_response_error(bytes(existing_key_resp), expected_opcode=0x27)
    assert excinfo.value.code == 6


def test_yale_pin_code_dataclass() -> None:
    """Test YalePinCode dataclass initialization."""
    pin_obj = YalePinCode(slot=1, pin="123456", name="Guest")
    assert pin_obj.slot == 1
    assert pin_obj.pin == "123456"
    assert pin_obj.name == "Guest"
    assert pin_obj.valid_from is None
    assert pin_obj.valid_to is None
