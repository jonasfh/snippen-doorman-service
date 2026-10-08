#!/usr/bin/env python3
"""Yale Doorman / Access BLE BTSnoop Capture Decryptor.

This tool parses Android Bluetooth HCI snoop logs (btsnoop_hci.log / PCAP / bugreport zips),
filters BLE traffic, reconstructs the AES-128 handshake nonces, derives the ephemeral session
key using the known offline key, and decrypts all AES-CBC encrypted GATT command and response
frames (such as PIN code creation, updating, querying, and deletion).

Protocol details:
- Initial handshake: AES-128-ECB using the 16-byte offline key
- Session key derivation: client_nonce_1 (8 bytes) + lock_nonce_1 (8 bytes) = 16 bytes session key
- Command encryption: AES-128-CBC using session key with zero IV (bytes(16)) on first 16 bytes,
  with the remaining 2 bytes plaintext.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import struct
import sys
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import (
    Cipher,
    CipherContext,
    algorithms,
    modes,
)

# Standard August / Yale BLE UUID constants
AUGUST_SERVICE_UUID_16 = 0xFE24
WRITE_CHAR_UUID = "bd4ac611-0b45-11e3-8ffd-0800200c9a66"
READ_CHAR_UUID = "bd4ac612-0b45-11e3-8ffd-0800200c9a66"
SECURE_WRITE_CHAR_UUID = "bd4ac613-0b45-11e3-8ffd-0800200c9a66"
SECURE_READ_CHAR_UUID = "bd4ac614-0b45-11e3-8ffd-0800200c9a66"

# Command Opcodes
OPCODES = {
    0x01: "SEC_HANDSHAKE_CLIENT_NONCE_1",
    0x02: "CMD_STATUS_POLL",
    0x03: "SEC_HANDSHAKE_CLIENT_NONCE_2",
    0x04: "SEC_HANDSHAKE_LOCK_ACK",
    0x0A: "CMD_UNLOCK",
    0x0B: "CMD_LOCK",
    0x22: "CMD_KEEP_ALIVE",
    0x27: "CMD_KEYCODE_SET",
    0x28: "CMD_KEYCODE_CLEAR",
    0x29: "CMD_KEYCODE_CLEAR_ALL",
    0x2A: "CMD_KEYCODE_UNLOCK",
    0x2B: "CMD_KEYCODE_ACCESS",
    0x2C: "CMD_KEYCODE_COMMIT",
    0x39: "CMD_UNITY_GET_KEYCODE",
    0x42: "CMD_ENTER_CREDENTIAL_LEARN_MODE",
    0x43: "CMD_DELETE_CREDENTIAL",
    0x50: "CMD_STATUS",
    0x51: "CMD_DISCONNECT",
}

OPERATION_ERRORS = {
    0: "COMM_SUCCESS",
    1: "PARAM_NOT_PAIRED",
    2: "PARAM_NOT_READABLE",
    3: "WRONG_KEY",
    4: "KEYCODE_DISABLE",
    5: "KEYCODE_INVALID_ACCESS",
    6: "KEYCODE_EXISTING_KEY",
    7: "KEYCODE_NOSPACE",
    8: "KEYCODE_TIMEOUT",
    9: "KEYCODE_DIS_ONETOUCH",
    10: "RFID_EXISTING_ID",
    11: "FINGERPRINT_EXISTING_ID",
    69: "KEYCODE_SLOT_IN_USE",
}

CREDENTIAL_TYPES = {
    0: "PIN",
    1: "RFID",
    2: "FINGERPRINT",
    4: "FACE",
}


class PacketDirection(str, Enum):
    HOST_TO_LOCK = "HOST_TO_LOCK"  # Sent by client/app (TX)
    LOCK_TO_HOST = "LOCK_TO_HOST"  # Sent by door lock (RX)


@dataclass
class RawHciPacket:
    timestamp_us: int
    direction: PacketDirection
    data: bytes


@dataclass
class AttPacket:
    timestamp_us: int
    direction: PacketDirection
    conn_handle: int
    att_opcode: int
    gatt_handle: int
    payload: bytes


@dataclass
class DecryptedFrame:
    timestamp_us: int
    direction: PacketDirection
    conn_handle: int
    gatt_handle: int
    cipher_type: str  # "AES-ECB" or "AES-CBC"
    raw_hex: str
    decrypted_hex: str
    opcode: int
    opcode_name: str
    details: str
    checksum_valid: bool


@dataclass
class BleSession:
    conn_handle: int
    mac_address: str | None
    slot: int | None
    client_nonce_1: str | None
    lock_nonce_1: str | None
    client_nonce_2: str | None
    session_key: str | None
    frames: list[DecryptedFrame]


def decode_packed_bcd_pin(raw_bytes: bytes) -> str:
    """Decode a packed BCD PIN buffer (up to 7 bytes) to a digit string."""
    digits = []
    for b in raw_bytes:
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high <= 9:
            digits.append(str(high))
        elif high == 0x0F:
            break
        if low <= 9:
            digits.append(str(low))
        elif low == 0x0F:
            break
    return "".join(digits)


def encode_packed_bcd_pin(pin: str) -> bytes:
    """Encode a digit string to a 7-byte packed BCD buffer padded with 0xFF."""
    buf = bytearray([0xFF] * 7)
    for i, ch in enumerate(pin):
        if not ch.isdigit():
            raise ValueError(f"PIN must contain only digits: {pin}")
        digit = int(ch)
        byte_idx = i // 2
        if i % 2 == 0:
            buf[byte_idx] = (buf[byte_idx] & 0x0F) | (digit << 4)
        else:
            buf[byte_idx] = (buf[byte_idx] & 0xF0) | digit
    return bytes(buf)


def verify_august_checksum(frame: bytes) -> bool:
    """Verify that the 18-byte August frame has sum(frame) % 256 == 0."""
    if len(frame) != 18:
        return False
    return (sum(frame) & 0xFF) == 0


def decrypt_aes_ecb(key: bytes, block16: bytes) -> bytes:
    """Decrypt a 16-byte block with AES-128-ECB."""
    cipher = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return cipher.update(block16) + cipher.finalize()


def decrypt_aes_cbc(key: bytes, block16: bytes) -> bytes:
    """Decrypt a 16-byte block with AES-128-CBC using a zero IV."""
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).decryptor()
    return cipher.update(block16) + cipher.finalize()


def parse_btsnoop_stream(stream: BinaryIO) -> Iterator[RawHciPacket]:
    """Parse raw HCI packets from a btsnoop stream (RFC 1761 / Android btsnoop)."""
    header = stream.read(16)
    if len(header) < 16:
        return

    magic = header[:8]
    if magic != b"btsnoop\x00":
        raise ValueError(f"Not a valid btsnoop file: magic={magic!r}")

    version, _datalink_type = struct.unpack(">II", header[8:16])
    if version != 1:
        raise ValueError(f"Unsupported btsnoop version: {version}")

    record_hdr_len = 24
    while True:
        hdr_data = stream.read(record_hdr_len)
        if len(hdr_data) < record_hdr_len:
            break

        _orig_len, inc_len, flags, _drops, ts_raw = struct.unpack(">IIIIq", hdr_data)
        packet_data = stream.read(inc_len)
        if len(packet_data) < inc_len:
            break

        # In btsnoop, timestamp is microseconds since 01/01/0000 00:00:00
        # Offset to Unix epoch is 0x00dcddb30f2f8000
        ts_us = ts_raw - 0x00DCDDB30F2F8000
        if ts_us < 0:
            ts_us = ts_raw

        # Bit 0 of flags: 0 = Host -> Controller (TX), 1 = Controller -> Host (RX)
        direction = PacketDirection.LOCK_TO_HOST if (flags & 0x01) else PacketDirection.HOST_TO_LOCK

        yield RawHciPacket(timestamp_us=ts_us, direction=direction, data=packet_data)


def parse_pcap_stream(stream: BinaryIO) -> Iterator[RawHciPacket]:
    """Parse raw HCI packets from a PCAP stream."""
    header = stream.read(24)
    if len(header) < 24:
        return

    magic = header[:4]
    if magic == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    elif magic == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    else:
        raise ValueError(f"Not a valid PCAP file: magic={magic.hex()}")

    _v_maj, _v_min, _thiszone, _sigfigs, _snaplen, network = struct.unpack(
        f"{endian}HHIIII", header[4:24]
    )

    rec_hdr_len = 16
    while True:
        hdr_data = stream.read(rec_hdr_len)
        if len(hdr_data) < rec_hdr_len:
            break

        ts_sec, ts_usec, incl_len, _orig_len = struct.unpack(f"{endian}IIII", hdr_data)
        packet_data = stream.read(incl_len)
        if len(packet_data) < incl_len:
            break

        ts_us = ts_sec * 1_000_000 + ts_usec

        direction = PacketDirection.HOST_TO_LOCK
        data = packet_data

        # PCAP LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR = 187
        if network == 187 and len(data) >= 4:
            phdr_dir = struct.unpack(f"{endian}I", data[:4])[0]
            direction = (
                PacketDirection.LOCK_TO_HOST if phdr_dir == 1 else PacketDirection.HOST_TO_LOCK
            )
            data = data[4:]
        # PCAP LINKTYPE_BLUETOOTH_LINUX_MONITOR = 201
        elif network == 201 and len(data) >= 6:
            opcode = struct.unpack(f"{endian}H", data[:2])[0]
            # In Linux monitor: opcode 2 = ACL TX, 3 = ACL RX, 4 = Event, etc.
            direction = (
                PacketDirection.LOCK_TO_HOST
                if (opcode in (3, 4, 7))
                else PacketDirection.HOST_TO_LOCK
            )
            data = data[6:]

        yield RawHciPacket(timestamp_us=ts_us, direction=direction, data=data)


def extract_att_packets(
    hci_packets: Iterator[RawHciPacket],
) -> Iterator[AttPacket]:
    """Extract ATT PDUs from a stream of raw HCI packets."""
    for raw in hci_packets:
        data = raw.data
        if not data:
            continue

        # Check H4 packet indicator
        h4_type = data[0]
        payload = data[1:] if h4_type in (0x01, 0x02, 0x03, 0x04) else data

        # ACL Data packet (H4 type 0x02 or direct HCI ACL)
        if h4_type == 0x02 or (len(payload) >= 8 and h4_type not in (1, 3, 4)):
            if len(payload) < 8:
                continue

            handle_flags = struct.unpack("<H", payload[0:2])[0]
            conn_handle = handle_flags & 0x0FFF
            _data_len = struct.unpack("<H", payload[2:4])[0]

            # L2CAP header
            l2cap_len, l2cap_cid = struct.unpack("<HH", payload[4:8])
            if l2cap_cid == 0x0004 and len(payload) >= 8 + l2cap_len:
                att_pdu = payload[8 : 8 + l2cap_len]
                if not att_pdu:
                    continue

                att_opcode = att_pdu[0]
                # ATT Write Request (0x12), Write Command (0x52), Handle Notification (0x1B), Indication (0x1D)
                if att_opcode in (0x12, 0x52, 0x1B, 0x1D) and len(att_pdu) >= 3:
                    gatt_handle = struct.unpack("<H", att_pdu[1:3])[0]
                    att_payload = att_pdu[3:]
                    yield AttPacket(
                        timestamp_us=raw.timestamp_us,
                        direction=raw.direction,
                        conn_handle=conn_handle,
                        att_opcode=att_opcode,
                        gatt_handle=gatt_handle,
                        payload=att_payload,
                    )


def decode_command_details(opcode: int, payload: bytes) -> str:
    """Decode human-readable details from the decrypted 18-byte command/response."""
    op_name = OPCODES.get(opcode, f"0x{opcode:02X}")

    if opcode == 0x27:  # CMD_KEYCODE_SET
        pin = decode_packed_bcd_pin(payload[4:11])
        cred_type = CREDENTIAL_TYPES.get(payload[12], str(payload[12]))
        return f"Set PIN: '{pin}' (type={cred_type})"

    if opcode == 0x28:  # CMD_KEYCODE_CLEAR
        slot = payload[11] | (payload[13] << 8)
        pin = decode_packed_bcd_pin(payload[4:11])
        cred_type = CREDENTIAL_TYPES.get(payload[12], str(payload[12]))
        return f"Clear PIN in Slot {slot} (pin='{pin}', type={cred_type})"

    if opcode == 0x29:  # CMD_KEYCODE_CLEAR_ALL
        return "Clear all PIN codes"

    if opcode == 0x2B:  # CMD_KEYCODE_ACCESS
        start_ts = struct.unpack("<I", payload[4:8])[0]
        end_ts = struct.unpack("<I", payload[8:12])[0]
        access_type = payload[12]
        cred_type = CREDENTIAL_TYPES.get(payload[13], str(payload[13]))

        sched_str = "Always"
        if access_type == 0x80:
            sched_str = "Always (0x80)"
        elif access_type in (0x81, 0x82):
            st_dt = datetime.fromtimestamp(start_ts, tz=UTC).isoformat() if start_ts else "0"
            et_dt = datetime.fromtimestamp(end_ts, tz=UTC).isoformat() if end_ts else "0"
            sched_str = f"Temporary ({st_dt} -> {et_dt})"
        else:
            sched_str = f"Recurring (days_mask=0x{access_type:02X}, {start_ts}s -> {end_ts}s)"

        return f"Set Schedule: {sched_str} (type={cred_type})"

    if opcode == 0x2C:  # CMD_KEYCODE_COMMIT
        slot = payload[11] | (payload[13] << 8)
        pin = decode_packed_bcd_pin(payload[4:11])
        cred_type = CREDENTIAL_TYPES.get(payload[12], str(payload[12]))
        return f"Commit PIN '{pin}' -> Slot {slot} (type={cred_type})"

    if opcode == 0x39:  # CMD_UNITY_GET_KEYCODE
        slot = payload[4] | (payload[5] << 8)
        pin = decode_packed_bcd_pin(payload[6:13])
        return f"Query Slot {slot} (returned PIN='{pin}')"

    if opcode == 0x0A:
        return "Command: Unlock Door"
    if opcode == 0x0B:
        return "Command: Lock Door"
    if opcode == 0x02:
        return "Poll Lock Status / Ping"
    if opcode == 0x22:
        return "Keep-Alive / Heartbeat"
    if opcode == 0x50:
        return "Query Lock Status"
    if opcode == 0x51:
        return "Command: Disconnect"

    # Status response check
    if payload[0] in (0xAA, 0xBB, 0xCC):
        err_code = payload[3]
        err_name = OPERATION_ERRORS.get(err_code, f"0x{err_code:02X}")
        return f"Response to {op_name} (status={err_name})"

    return f"Opcode {op_name} (payload={payload.hex()})"


class SessionDecryptor:
    """State machine for tracking and decrypting a Yale Doorman BLE connection."""

    def __init__(self, offline_key: bytes, conn_handle: int):
        self.offline_key = offline_key
        self.conn_handle = conn_handle
        self.slot: int | None = None
        self.client_nonce_1: bytes | None = None
        self.lock_nonce_1: bytes | None = None
        self.client_nonce_2: bytes | None = None
        self.session_key: bytes | None = None
        self.is_established: bool = False
        self.tx_cipher: CipherContext | None = None
        self.rx_cipher: CipherContext | None = None
        self.frames: list[DecryptedFrame] = []

    def process_packet(self, pkt: AttPacket) -> DecryptedFrame | None:
        """Process an ATT packet and attempt handshake or command decryption."""
        if len(pkt.payload) != 18:
            return None

        # State 1: Awaiting Client Nonce 1 (Handshake 1)
        if self.client_nonce_1 is None and pkt.direction == PacketDirection.HOST_TO_LOCK:
            decrypted_16 = decrypt_aes_ecb(self.offline_key, pkt.payload[:16])
            plain = decrypted_16 + pkt.payload[16:18]
            if plain[0] == 0x01 and plain[16] == 0x0F:
                self.client_nonce_1 = plain[4:12]
                self.slot = plain[17]
                frame = DecryptedFrame(
                    timestamp_us=pkt.timestamp_us,
                    direction=pkt.direction,
                    conn_handle=pkt.conn_handle,
                    gatt_handle=pkt.gatt_handle,
                    cipher_type="AES-ECB (offline key)",
                    raw_hex=pkt.payload.hex(),
                    decrypted_hex=plain.hex(),
                    opcode=0x01,
                    opcode_name=OPCODES[0x01],
                    details=f"Handshake 1: Client Nonce={self.client_nonce_1.hex()} (Slot {self.slot})",
                    checksum_valid=True,
                )
                self.frames.append(frame)
                return frame

        # State 2: Awaiting Lock Nonce 1 (Handshake 2)
        if (
            self.client_nonce_1 is not None
            and self.lock_nonce_1 is None
            and pkt.direction == PacketDirection.LOCK_TO_HOST
        ):
            decrypted_16 = decrypt_aes_ecb(self.offline_key, pkt.payload[:16])
            plain = decrypted_16 + pkt.payload[16:18]
            if plain[0] == 0x02 and plain[16] == 0x0F:
                self.lock_nonce_1 = plain[4:12]
                # Derive session key!
                self.session_key = self.client_nonce_1 + self.lock_nonce_1
                frame = DecryptedFrame(
                    timestamp_us=pkt.timestamp_us,
                    direction=pkt.direction,
                    conn_handle=pkt.conn_handle,
                    gatt_handle=pkt.gatt_handle,
                    cipher_type="AES-ECB (offline key)",
                    raw_hex=pkt.payload.hex(),
                    decrypted_hex=plain.hex(),
                    opcode=0x02,
                    opcode_name=OPCODES[0x02],
                    details=f"Handshake 2: Lock Nonce={self.lock_nonce_1.hex()} -> Derived Session Key={self.session_key.hex()}",
                    checksum_valid=True,
                )
                self.frames.append(frame)
                return frame

        # State 3: Awaiting Client Nonce 2 (Handshake 3)
        if (
            self.session_key is not None
            and self.client_nonce_2 is None
            and pkt.direction == PacketDirection.HOST_TO_LOCK
        ):
            decrypted_16 = decrypt_aes_ecb(self.session_key, pkt.payload[:16])
            plain = decrypted_16 + pkt.payload[16:18]
            if plain[0] == 0x03 and plain[16] == 0x0F:
                self.client_nonce_2 = plain[4:12]
                frame = DecryptedFrame(
                    timestamp_us=pkt.timestamp_us,
                    direction=pkt.direction,
                    conn_handle=pkt.conn_handle,
                    gatt_handle=pkt.gatt_handle,
                    cipher_type="AES-ECB (session key)",
                    raw_hex=pkt.payload.hex(),
                    decrypted_hex=plain.hex(),
                    opcode=0x03,
                    opcode_name=OPCODES[0x03],
                    details=f"Handshake 3: Client Nonce 2={self.client_nonce_2.hex()}",
                    checksum_valid=True,
                )
                self.frames.append(frame)
                return frame

        # State 4: Awaiting Lock Handshake ACK (Handshake 4)
        if (
            self.session_key is not None
            and not self.is_established
            and pkt.direction == PacketDirection.LOCK_TO_HOST
        ):
            decrypted_16 = decrypt_aes_ecb(self.session_key, pkt.payload[:16])
            plain = decrypted_16 + pkt.payload[16:18]
            if plain[0] == 0x04:
                self.is_established = True
                self.tx_cipher = Cipher(
                    algorithms.AES(self.session_key), modes.CBC(bytes(16))
                ).decryptor()
                self.rx_cipher = Cipher(
                    algorithms.AES(self.session_key), modes.CBC(bytes(16))
                ).decryptor()
                frame = DecryptedFrame(
                    timestamp_us=pkt.timestamp_us,
                    direction=pkt.direction,
                    conn_handle=pkt.conn_handle,
                    gatt_handle=pkt.gatt_handle,
                    cipher_type="AES-ECB (session key)",
                    raw_hex=pkt.payload.hex(),
                    decrypted_hex=plain.hex(),
                    opcode=0x04,
                    opcode_name=OPCODES[0x04],
                    details="Handshake 4: Lock Session Initialized (AES-CBC Ready)",
                    checksum_valid=True,
                )
                self.frames.append(frame)
                return frame

        # State 5: Established session - Decrypt continuous AES-CBC frames
        if self.session_key is not None and self.is_established:
            if pkt.direction == PacketDirection.HOST_TO_LOCK:
                assert self.tx_cipher is not None
                decrypted_16 = self.tx_cipher.update(pkt.payload[:16])
            else:
                assert self.rx_cipher is not None
                decrypted_16 = self.rx_cipher.update(pkt.payload[:16])
            plain = decrypted_16 + pkt.payload[16:18]

            chk_valid = verify_august_checksum(plain)
            opcode = plain[1]
            op_name = OPCODES.get(opcode, f"0x{opcode:02X}")
            details = decode_command_details(opcode, plain)

            frame = DecryptedFrame(
                timestamp_us=pkt.timestamp_us,
                direction=pkt.direction,
                conn_handle=pkt.conn_handle,
                gatt_handle=pkt.gatt_handle,
                cipher_type="AES-CBC (session key)",
                raw_hex=pkt.payload.hex(),
                decrypted_hex=plain.hex(),
                opcode=opcode,
                opcode_name=op_name,
                details=details,
                checksum_valid=chk_valid,
            )
            self.frames.append(frame)
            return frame

        return None


def open_capture_stream(file_path: Path) -> BinaryIO:
    """Open a capture file, supporting direct files or zip archives (bugreports)."""
    if file_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(file_path, "r") as zf:
            candidates = [
                name
                for name in zf.namelist()
                if "snoop" in name.lower() or "snooz" in name.lower() or name.endswith(".pcap")
            ]
            if not candidates:
                raise FileNotFoundError(
                    f"No btsnoop, btsnooz, or pcap logs found inside {file_path}"
                )
            # Prefer btsnoop_hci.log, then btsnooz_hci.log, avoiding .last unless only option
            best = next(
                (c for c in candidates if c.endswith("btsnoop_hci.log")),
                next(
                    (c for c in candidates if c.endswith("btsnooz_hci.log")),
                    candidates[0],
                ),
            )
            print(f"[*] Reading '{best}' from archive {file_path.name}...")
            return io.BytesIO(zf.read(best))

    return file_path.open("rb")


def process_capture(
    input_path: Path,
    offline_key: bytes,
    target_slot: int | None = None,
) -> list[BleSession]:
    """Parse capture file and decrypt all Yale Doorman BLE sessions."""
    stream = open_capture_stream(input_path)
    magic = stream.read(8)
    stream.seek(0)

    if magic.startswith(b"btsnoop\x00"):
        raw_packets = parse_btsnoop_stream(stream)
    elif magic[:4] in (b"\xa1\xb2\xc3\xd4", b"\xd4\xc3\xb2\xa1"):
        raw_packets = parse_pcap_stream(stream)
    else:
        raise ValueError(f"Unknown capture format: magic={magic.hex()}")

    att_packets = extract_att_packets(raw_packets)

    sessions: dict[int, SessionDecryptor] = {}
    completed_sessions: list[BleSession] = []

    for pkt in att_packets:
        handle = pkt.conn_handle
        if handle not in sessions:
            sessions[handle] = SessionDecryptor(offline_key=offline_key, conn_handle=handle)

        decryptor = sessions[handle]
        decryptor.process_packet(pkt)

    for handle, dec in sessions.items():
        if dec.frames:
            if target_slot is not None and dec.slot != target_slot:
                continue
            completed_sessions.append(
                BleSession(
                    conn_handle=handle,
                    mac_address=None,
                    slot=dec.slot,
                    client_nonce_1=dec.client_nonce_1.hex() if dec.client_nonce_1 else None,
                    lock_nonce_1=dec.lock_nonce_1.hex() if dec.lock_nonce_1 else None,
                    client_nonce_2=dec.client_nonce_2.hex() if dec.client_nonce_2 else None,
                    session_key=dec.session_key.hex() if dec.session_key else None,
                    frames=dec.frames,
                )
            )

    return completed_sessions


def format_timestamp(us: int) -> str:
    """Format microsecond timestamp to readable string."""
    try:
        dt = datetime.fromtimestamp(us / 1_000_000, tz=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except (ValueError, OSError):
        return f"{us} us"


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Decrypt Yale Doorman / Access BLE GATT sessions from btsnoop logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to btsnoop_hci.log, .pcap, or Android bugreport.zip",
    )
    parser.add_argument(
        "-k",
        "--key",
        type=str,
        default=os.getenv("SNIPPEN_DOORMAN_BLE_KEY", ""),
        help="16-byte offline AES key in hex (defaults to SNIPPEN_DOORMAN_BLE_KEY env var)",
    )
    parser.add_argument(
        "-s",
        "--slot",
        type=int,
        default=None,
        help="Filter by key slot index (e.g. 2)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as structured JSON",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Display raw encrypted and decrypted hexadecimal payloads",
    )

    args = parser.parse_args()

    key_val = args.key
    if not key_val:
        # Try reading .env file in cwd or parents
        for env_path in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("SNIPPEN_DOORMAN_BLE_KEY="):
                        key_val = line.split("=", 1)[1].strip("\"' ")
                        break
            if key_val:
                break

    if not key_val:
        print(
            "Error: Offline key must be provided via -k/--key or SNIPPEN_DOORMAN_BLE_KEY in environment or .env.",
            file=sys.stderr,
        )
        return 1

    try:
        offline_key = bytes.fromhex(key_val)
        if len(offline_key) != 16:
            raise ValueError
    except ValueError:
        print("Error: Offline key must be exactly 32 hex characters (16 bytes).", file=sys.stderr)
        return 1

    if not args.input.exists():
        print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
        return 1

    try:
        sessions = process_capture(args.input, offline_key=offline_key, target_slot=args.slot)
    except (ValueError, OSError, struct.error, zipfile.BadZipFile) as exc:
        print(f"Error processing capture: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(s) for s in sessions], indent=2))
        return 0

    if not sessions:
        print("[!] No matching Yale Doorman sessions or decrypted frames found in capture.")
        return 0

    print("=" * 80)
    print("Yale Doorman BLE Session Decryption Report")
    print("=" * 80)

    for i, sess in enumerate(sessions, 1):
        print(f"\n[+] Session #{i} (Conn Handle: 0x{sess.conn_handle:04X}, Slot: {sess.slot})")
        print(f"    - Client Nonce 1: {sess.client_nonce_1}")
        print(f"    - Lock Nonce 1:   {sess.lock_nonce_1}")
        print(f"    - Session Key:    {sess.session_key}")
        print(f"    - Total Frames:   {len(sess.frames)}")
        print("\n    Chronological Frame Log:")
        print("    " + "-" * 76)

        for frame in sess.frames:
            ts = format_timestamp(frame.timestamp_us)
            dir_arrow = (
                ">>> (Host -> Lock)"
                if frame.direction == PacketDirection.HOST_TO_LOCK
                else "<<< (Lock -> Host)"
            )
            chk_status = "OK" if frame.checksum_valid else "INVALID"

            print(f"    [{ts}] {dir_arrow:20} {frame.opcode_name}")
            print(f"      {frame.details}")
            if args.verbose:
                print(f"      Cipher:    {frame.cipher_type}")
                print(f"      Raw Hex:   {frame.raw_hex}")
                print(f"      Plain Hex: {frame.decrypted_hex} (checksum: {chk_status})")
            print()

    print("=" * 80)
    print(f"Analysis complete: {len(sessions)} session(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
