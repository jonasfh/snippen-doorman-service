"""BLE PIN code protocol helpers and definitions for Yale Doorman locks."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime

# Keypad and RTC opcodes
CMD_SET_RTC = 0x10
CMD_KEYCODE_SET = 0x27
CMD_KEYCODE_CLEAR = 0x28
CMD_KEYCODE_CLEAR_ALL = 0x29
CMD_KEYCODE_UNLOCK = 0x2A
CMD_KEYCODE_ACCESS = 0x2B
CMD_KEYCODE_COMMIT = 0x2C
CMD_UNITY_GET_KEYCODE = 0x39

CREDENTIAL_TYPE_PIN = 0x00

SCHEDULE_ALWAYS = 0x80
SCHEDULE_TEMPORARY = 0x81

# Error codes returned in byte 15 of lock response
OPERATION_ERRORS: dict[int, str] = {
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


class YalePinError(Exception):
    """Exception raised when a PIN operation on the Yale lock fails."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class YalePinCode:
    """Represents a PIN code stored in or programmed to the Yale lock."""

    slot: int
    pin: str
    name: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def encode_packed_bcd_pin(pin: str) -> bytes:
    """Encode a digit string into 7-byte packed BCD buffer padded with 0xFF.

    First digit goes into high nibble of byte 0, second digit into low nibble, etc.
    """
    if not pin:
        raise ValueError("PIN must not be empty.")
    if not pin.isdigit():
        raise ValueError(f"PIN must contain only digits: {pin}")
    if not (4 <= len(pin) <= 6):
        raise ValueError(f"PIN length must be between 4 and 6 digits, got {len(pin)}")

    buf = bytearray([0xFF] * 7)
    for i, ch in enumerate(pin):
        digit = int(ch)
        byte_idx = i // 2
        if i % 2 == 0:
            buf[byte_idx] = (buf[byte_idx] & 0x0F) | (digit << 4)
        else:
            buf[byte_idx] = (buf[byte_idx] & 0xF0) | digit
    return bytes(buf)


def decode_packed_bcd_pin(raw_bytes: bytes) -> str:
    """Decode a packed BCD PIN buffer (up to 7 bytes) to a digit string."""
    if not raw_bytes or set(raw_bytes) in ({0x00}, {0xFF}):
        return ""
    digits: list[str] = []
    for b in raw_bytes:
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high <= 9:
            digits.append(str(high))
        elif high == 0x0F:
            break
        else:
            return ""
        if low <= 9:
            digits.append(str(low))
        elif low == 0x0F:
            break
        else:
            return ""
    pin = "".join(digits)
    if not (4 <= len(pin) <= 6):
        return ""
    return pin


def calculate_august_checksum(pkt: bytearray) -> int:
    """Calculate the 1-byte August packet checksum (modulo 256 negation)."""
    pkt[3] = 0
    return (-sum(pkt[:18])) & 0xFF


def build_pin_packet(opcode: int, payload: bytes) -> bytearray:
    """Construct standard 18-byte August command packet."""
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = opcode
    pkt[2] = 0x00
    pkt[3] = 0x00
    if payload:
        pkt[4 : 4 + len(payload)] = payload[:12]
    pkt[16] = 0x02
    pkt[17] = 0x00
    pkt[3] = calculate_august_checksum(pkt)
    return pkt


def build_set_rtc_packet(timestamp: datetime | int | None = None) -> bytearray:
    """Build CMD_SET_RTC (0x10) packet to synchronize the lock's hardware clock.

    Args:
        timestamp: Optional timestamp as datetime or Unix epoch seconds. Defaults to now (UTC).

    Returns:
        18-byte command packet with August checksum.
    """
    if timestamp is None:
        ts = int(datetime.now(UTC).timestamp())
    elif isinstance(timestamp, datetime):
        ts = int(timestamp.timestamp())
    elif isinstance(timestamp, int):
        if timestamp < 0:
            raise ValueError("Timestamp must be non-negative.")
        ts = timestamp
    else:
        raise TypeError(f"Invalid timestamp type: {type(timestamp)}")

    payload = bytearray(12)
    payload[0:4] = struct.pack("<I", ts)
    return build_pin_packet(CMD_SET_RTC, bytes(payload))


def build_set_pin_packet(pin: str) -> bytearray:
    """Build CMD_KEYCODE_SET (0x27) packet for preparing a PIN code."""
    payload = bytearray(12)
    payload[0:7] = encode_packed_bcd_pin(pin)
    payload[8] = CREDENTIAL_TYPE_PIN
    return build_pin_packet(CMD_KEYCODE_SET, bytes(payload))


def build_schedule_packet(
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> bytearray:
    """Build CMD_KEYCODE_ACCESS (0x2B) packet defining time schedule."""
    payload = bytearray(12)
    if valid_from is not None or valid_to is not None:
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from")
        start_ts = int(valid_from.timestamp()) if valid_from else 0
        end_ts = int(valid_to.timestamp()) if valid_to else 0
        payload[0:4] = struct.pack("<I", start_ts)
        payload[4:8] = struct.pack("<I", end_ts)
        payload[8] = SCHEDULE_TEMPORARY
    else:
        payload[0:4] = struct.pack("<I", 0)
        payload[4:8] = struct.pack("<I", 0)
        payload[8] = SCHEDULE_ALWAYS

    payload[9] = CREDENTIAL_TYPE_PIN
    return build_pin_packet(CMD_KEYCODE_ACCESS, bytes(payload))


def build_commit_pin_packet(pin: str, slot: int) -> bytearray:
    """Build CMD_KEYCODE_COMMIT (0x2C) packet binding PIN to a slot."""
    if slot < 0:
        raise ValueError("Slot must be 0 or higher.")
    payload = bytearray(12)
    payload[0:7] = encode_packed_bcd_pin(pin)
    payload[7] = slot & 0xFF
    payload[8] = CREDENTIAL_TYPE_PIN
    payload[9] = (slot >> 8) & 0xFF
    return build_pin_packet(CMD_KEYCODE_COMMIT, bytes(payload))


def build_clear_pin_packet(slot: int, pin: str | None = None) -> bytearray:
    """Build CMD_KEYCODE_CLEAR (0x28) packet deleting PIN for a slot."""
    if slot < 0:
        raise ValueError("Slot must be 0 or higher.")
    payload = bytearray(12)
    if pin:
        payload[0:7] = encode_packed_bcd_pin(pin)
    else:
        payload[0:7] = bytes([0xFF] * 7)
    payload[7] = slot & 0xFF
    payload[8] = CREDENTIAL_TYPE_PIN
    payload[9] = (slot >> 8) & 0xFF
    return build_pin_packet(CMD_KEYCODE_CLEAR, bytes(payload))


def build_query_pin_packet(slot: int) -> bytearray:
    """Build CMD_UNITY_GET_KEYCODE (0x39) packet querying PIN at a slot."""
    if slot < 0:
        raise ValueError("Slot must be 0 or higher.")
    payload = bytearray(12)
    payload[0:2] = struct.pack("<H", slot)
    return build_pin_packet(CMD_UNITY_GET_KEYCODE, bytes(payload))


def check_pin_response_error(response: bytes, expected_opcode: int) -> None:
    """Verify response frame and raise YalePinError if the operation failed."""
    if len(response) < 16:
        raise YalePinError(
            f"Invalid response length ({len(response)} bytes), expected at least 16 bytes."
        )

    if response[0] not in (0xAA, 0xBB, 0xCC):
        raise YalePinError(f"Unexpected response header 0x{response[0]:02X}")

    if response[1] != expected_opcode:
        raise YalePinError(
            f"Response opcode mismatch: expected 0x{expected_opcode:02X}, got 0x{response[1]:02X}"
        )

    # In 0xBB result frames, byte 15 is the operation result code
    err_code = response[15]
    if err_code != 0:
        err_name = OPERATION_ERRORS.get(err_code, f"UNKNOWN_ERROR_0x{err_code:02X}")
        raise YalePinError(
            f"Lock rejected opcode 0x{expected_opcode:02X}: {err_name} (code 0x{err_code:02X})",
            code=err_code,
        )
