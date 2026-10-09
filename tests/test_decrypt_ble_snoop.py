"""Tests for tools/decrypt_ble_snoop.py."""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from tools.decrypt_ble_snoop import (
    PacketDirection,
    decode_command_details,
    decode_packed_bcd_pin,
    decrypt_aes_cbc,
    decrypt_aes_ecb,
    encode_packed_bcd_pin,
    parse_pcap_stream,
    process_capture,
    verify_august_checksum,
)

TEST_OFFLINE_KEY = bytes.fromhex("438b544da1ffd82510a973d5ff9853bb")
TEST_CLIENT_NONCE_1 = bytes.fromhex("0102030405060708")
TEST_LOCK_NONCE_1 = bytes.fromhex("1112131415161718")
EXPECTED_SESSION_KEY = TEST_CLIENT_NONCE_1 + TEST_LOCK_NONCE_1


def encrypt_aes_ecb(key: bytes, block16: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return cipher.update(block16) + cipher.finalize()


def encrypt_aes_cbc(key: bytes, block16: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return cipher.update(block16) + cipher.finalize()


def calc_august_checksum(pkt: bytearray) -> int:
    pkt[3] = 0
    return (-sum(pkt[:18])) & 0xFF


def build_command_frame(opcode: int, payload: bytes) -> bytes:
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = opcode
    pkt[2] = 0x00
    pkt[3] = 0x00
    pkt[4 : 4 + len(payload)] = payload
    pkt[16] = 0x02
    pkt[17] = 0x00
    pkt[3] = calc_august_checksum(pkt)
    return bytes(pkt)


def build_hci_acl_att_packet(
    conn_handle: int,
    att_opcode: int,
    gatt_handle: int,
    payload: bytes,
) -> bytes:
    """Build an H4 HCI ACL Data packet carrying an ATT PDU."""
    att_pdu = bytes([att_opcode]) + struct.pack("<H", gatt_handle) + payload
    l2cap_hdr = struct.pack("<HH", len(att_pdu), 0x0004)  # CID 0x0004 is ATT
    l2cap_pdu = l2cap_hdr + att_pdu
    acl_hdr = struct.pack("<HH", conn_handle & 0x0FFF, len(l2cap_pdu))
    # H4 indicator 0x02 for ACL Data
    return bytes([0x02]) + acl_hdr + l2cap_pdu


def build_btsnoop_record(
    packet_data: bytes,
    is_rx: bool,
    timestamp_us: int = 1_000_000,
) -> bytes:
    orig_len = len(packet_data)
    inc_len = orig_len
    flags = 1 if is_rx else 0
    drops = 0
    ts_raw = timestamp_us + 0x00DCDDB30F2F8000
    hdr = struct.pack(">IIIIq", orig_len, inc_len, flags, drops, ts_raw)
    return hdr + packet_data


def test_packed_bcd_pin_encoding_decoding():
    # 6-digit PIN
    pin6 = "123456"
    encoded6 = encode_packed_bcd_pin(pin6)
    assert encoded6 == bytes([0x12, 0x34, 0x56, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded6) == pin6

    # 4-digit PIN
    pin4 = "7890"
    encoded4 = encode_packed_bcd_pin(pin4)
    assert encoded4 == bytes([0x78, 0x90, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded4) == pin4

    # Odd length PIN
    pin5 = "12345"
    encoded5 = encode_packed_bcd_pin(pin5)
    assert encoded5 == bytes([0x12, 0x34, 0x5F, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_packed_bcd_pin(encoded5) == pin5

    with pytest.raises(ValueError):
        encode_packed_bcd_pin("12ab")


def test_august_checksum():
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = 0x27
    pkt[16] = 0x02
    pkt[17] = 0x00
    pkt[3] = calc_august_checksum(pkt)
    assert verify_august_checksum(bytes(pkt)) is True

    # Tampered byte
    pkt[4] = 0x55
    assert verify_august_checksum(bytes(pkt)) is False


def test_aes_ecb_and_cbc_decryption():
    key = b"0123456789abcdef"
    block = b"hello_world_1234"

    encrypted_ecb = encrypt_aes_ecb(key, block)
    assert decrypt_aes_ecb(key, encrypted_ecb) == block

    encrypted_cbc = encrypt_aes_cbc(key, block)
    assert decrypt_aes_cbc(key, encrypted_cbc) == block


def test_decode_command_details():
    # KeyCode Set
    pin_bytes = encode_packed_bcd_pin("123456")
    set_pkt = build_command_frame(0x27, pin_bytes + bytes([0x00]))
    details = decode_command_details(0x27, set_pkt)
    assert "Set PIN: '123456'" in details

    # KeyCode Access Always
    acc_payload = struct.pack("<II", 0, 0) + bytes([0x80, 0x00])
    acc_pkt = build_command_frame(0x2B, acc_payload)
    details = decode_command_details(0x2B, acc_pkt)
    assert "Always" in details

    # KeyCode Commit
    commit_payload = pin_bytes + bytes([0x03, 0x00, 0x00])  # Slot 3
    commit_pkt = build_command_frame(0x2C, commit_payload)
    details = decode_command_details(0x2C, commit_pkt)
    assert "Commit PIN '123456' -> Slot 3" in details

    # KeyCode Clear
    clear_payload = pin_bytes + bytes([0x03, 0x00, 0x00])
    clear_pkt = build_command_frame(0x28, clear_payload)
    details = decode_command_details(0x28, clear_pkt)
    assert "Clear PIN in Slot 3" in details


def test_full_btsnoop_session_decryption(tmp_path: Path):
    """End-to-end test generating synthetic btsnoop capture and decrypting the session."""
    btsnoop_file = tmp_path / "test_btsnoop.log"

    # Build btsnoop header (16 bytes)
    btsnoop_data = bytearray(b"btsnoop\x00")
    btsnoop_data += struct.pack(">II", 1, 1001)  # Version 1, HCI UART H4

    conn_handle = 0x0042
    gatt_write_handle = 0x0014
    gatt_notify_handle = 0x0017

    # 1. Handshake 1 (Host -> Lock)
    # Plaintext: [0x01, ...]
    hs1_plain = bytearray(18)
    hs1_plain[0] = 0x01
    hs1_plain[4:12] = TEST_CLIENT_NONCE_1
    hs1_plain[16] = 0x0F
    hs1_plain[17] = 2  # Slot 2
    hs1_enc = encrypt_aes_ecb(TEST_OFFLINE_KEY, hs1_plain[:16]) + hs1_plain[16:18]
    pkt1 = build_hci_acl_att_packet(conn_handle, 0x12, gatt_write_handle, hs1_enc)
    btsnoop_data += build_btsnoop_record(pkt1, is_rx=False, timestamp_us=1000)

    # 2. Handshake 2 (Lock -> Host)
    hs2_plain = bytearray(18)
    hs2_plain[0] = 0x02
    hs2_plain[4:12] = TEST_LOCK_NONCE_1
    hs2_plain[16] = 0x0F
    hs2_plain[17] = 2
    hs2_enc = encrypt_aes_ecb(TEST_OFFLINE_KEY, hs2_plain[:16]) + hs2_plain[16:18]
    pkt2 = build_hci_acl_att_packet(conn_handle, 0x1B, gatt_notify_handle, hs2_enc)
    btsnoop_data += build_btsnoop_record(pkt2, is_rx=True, timestamp_us=2000)

    # 3. Handshake 3 (Host -> Lock) - encrypted with EXPECTED_SESSION_KEY
    hs3_plain = bytearray(18)
    hs3_plain[0] = 0x03
    hs3_plain[4:12] = bytes.fromhex("9988776655443322")
    hs3_plain[16] = 0x0F
    hs3_plain[17] = 2
    hs3_enc = encrypt_aes_ecb(EXPECTED_SESSION_KEY, hs3_plain[:16]) + hs3_plain[16:18]
    pkt3 = build_hci_acl_att_packet(conn_handle, 0x12, gatt_write_handle, hs3_enc)
    btsnoop_data += build_btsnoop_record(pkt3, is_rx=False, timestamp_us=3000)

    # 4. Handshake 4 (Lock -> Host)
    hs4_plain = bytearray(18)
    hs4_plain[0] = 0x04
    hs4_plain[16] = 0x0F
    hs4_plain[17] = 2
    hs4_enc = encrypt_aes_ecb(EXPECTED_SESSION_KEY, hs4_plain[:16]) + hs4_plain[16:18]
    pkt4 = build_hci_acl_att_packet(conn_handle, 0x1B, gatt_notify_handle, hs4_enc)
    btsnoop_data += build_btsnoop_record(pkt4, is_rx=True, timestamp_us=4000)

    # 5. Command: KeyCode_Set ("123456") - encrypted with continuous AES-CBC
    tx_encryptor = Cipher(algorithms.AES(EXPECTED_SESSION_KEY), modes.CBC(bytes(16))).encryptor()
    pin_bytes = encode_packed_bcd_pin("123456")
    cmd_set = build_command_frame(0x27, pin_bytes + bytes([0x00]))
    cmd_set_enc = tx_encryptor.update(cmd_set[:16]) + cmd_set[16:18]
    pkt5 = build_hci_acl_att_packet(conn_handle, 0x12, gatt_write_handle, cmd_set_enc)
    btsnoop_data += build_btsnoop_record(pkt5, is_rx=False, timestamp_us=5000)

    # 6. Command: KeyCode_Commit (Slot 3, "123456")
    commit_payload = pin_bytes + bytes([0x03, 0x00, 0x00])
    cmd_commit = build_command_frame(0x2C, commit_payload)
    cmd_commit_enc = tx_encryptor.update(cmd_commit[:16]) + cmd_commit[16:18]
    pkt6 = build_hci_acl_att_packet(conn_handle, 0x12, gatt_write_handle, cmd_commit_enc)
    btsnoop_data += build_btsnoop_record(pkt6, is_rx=False, timestamp_us=6000)

    # 7. Command: KeyCode_Clear (Slot 3)
    clear_payload = pin_bytes + bytes([0x03, 0x00, 0x00])
    cmd_clear = build_command_frame(0x28, clear_payload)
    cmd_clear_enc = tx_encryptor.update(cmd_clear[:16]) + cmd_clear[16:18]
    pkt7 = build_hci_acl_att_packet(conn_handle, 0x12, gatt_write_handle, cmd_clear_enc)
    btsnoop_data += build_btsnoop_record(pkt7, is_rx=False, timestamp_us=7000)

    btsnoop_file.write_bytes(btsnoop_data)

    # Now process capture with our tool
    sessions = process_capture(btsnoop_file, offline_key=TEST_OFFLINE_KEY)

    assert len(sessions) == 1
    sess = sessions[0]
    assert sess.conn_handle == conn_handle
    assert sess.slot == 2
    assert sess.client_nonce_1 == TEST_CLIENT_NONCE_1.hex()
    assert sess.lock_nonce_1 == TEST_LOCK_NONCE_1.hex()
    assert sess.session_key == EXPECTED_SESSION_KEY.hex()

    # Verify decrypted frames
    opcodes = [f.opcode for f in sess.frames]
    assert opcodes == [0x01, 0x02, 0x03, 0x04, 0x27, 0x2C, 0x28]

    # Verify PIN details in frames
    set_frame = sess.frames[4]
    assert set_frame.opcode == 0x27
    assert "123456" in set_frame.details
    assert set_frame.checksum_valid is True

    commit_frame = sess.frames[5]
    assert commit_frame.opcode == 0x2C
    assert "Slot 3" in commit_frame.details
    assert "123456" in commit_frame.details

    clear_frame = sess.frames[6]
    assert clear_frame.opcode == 0x28
    assert "Slot 3" in clear_frame.details


def test_pcap_parsing():
    stream = io.BytesIO()
    # PCAP header (24 bytes)
    stream.write(
        struct.pack(
            "=IHHiIII",
            0xA1B2C3D4,
            2,
            4,
            0,
            0,
            65535,
            187,  # LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR
        )
    )
    # Packet with phdr (4 bytes direction + H4)
    data = b"\x00\x00\x00\x00\x02\x42\x00\x08\x00\x04\x00\x04\x00\x12\x14\x00"
    rec_hdr = struct.pack("=IIII", 100, 500, len(data), len(data))
    stream.write(rec_hdr + data)
    stream.seek(0)

    packets = list(parse_pcap_stream(stream))
    assert len(packets) == 1
    assert packets[0].direction == PacketDirection.HOST_TO_LOCK
    assert packets[0].timestamp_us == 100_000_500


def test_format_decrypted_details_rtc():
    """Test detail string formatting for RTC and timezone opcodes."""
    from tools.decrypt_ble_snoop import decode_command_details

    payload_rtc = bytearray(18)
    payload_rtc[0] = 0xEE
    payload_rtc[1] = 0x10
    payload_rtc[4:8] = struct.pack("<I", 1791439200)
    res = decode_command_details(0x10, bytes(payload_rtc))
    assert "Set RTC Clock" in res
    assert "1791439200" in res

    payload_tz = bytearray(18)
    payload_tz[0] = 0xEE
    payload_tz[1] = 0x30
    res_tz = decode_command_details(0x30, bytes(payload_tz))
    assert "Set Timezone" in res_tz
