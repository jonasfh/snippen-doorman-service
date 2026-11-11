"""BLE PIN code helpers and adapter types for Yale Doorman locks."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime

from yalexs_ble import util as yalexs_util
from yalexs_ble.const import VALUE_TO_OPERATION_ERROR, Commands
from yalexs_ble.session import YaleXSBLEError

# Keypad and RTC opcodes (SET_RTC is 0x10 upstream in Yale-Libs/yalexs-ble#436)
CMD_SET_RTC = int(getattr(Commands, "SET_RTC", 0x10))
CMD_KEYCODE_SET = Commands.KEYCODE_SET.value
CMD_KEYCODE_CLEAR = Commands.KEYCODE_CLEAR.value
CMD_KEYCODE_ACCESS = Commands.KEYCODE_ACCESS.value
CMD_KEYCODE_COMMIT = Commands.KEYCODE_COMMIT.value

CREDENTIAL_TYPE_PIN = 0x00

SCHEDULE_ALWAYS = 0x80
SCHEDULE_TEMPORARY = 0x81


class YalePinError(YaleXSBLEError):
    """Exception raised when a PIN or RTC operation on the Yale lock fails."""

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


def validate_doorman_pin(pin: str) -> None:
    """Validate that a PIN meets Yale Doorman Classic constraints (4-6 digits)."""
    if not pin:
        raise ValueError("PIN must not be empty.")
    if not pin.isdigit():
        raise ValueError(f"PIN must contain only digits: {pin}")
    if not (4 <= len(pin) <= 6):
        raise ValueError(f"PIN length must be between 4 and 6 digits, got {len(pin)}")


def encode_packed_bcd_pin(pin: str) -> bytes:
    """Validate a 4-6 digit PIN and encode via yalexs_ble packed BCD helper."""
    validate_doorman_pin(pin)
    return yalexs_util.encode_keycode_pin(pin)


def decode_packed_bcd_pin(raw_bytes: bytes) -> str:
    """Decode a packed BCD PIN buffer via yalexs_ble; returns '' if empty/invalid."""
    if not raw_bytes or set(raw_bytes) in ({0x00}, {0xFF}):
        return ""
    try:
        pin = yalexs_util.decode_keycode_pin(raw_bytes)
    except ValueError:
        return ""
    if not pin or not (4 <= len(pin) <= 6):
        return ""
    return pin


def build_pin_packet(opcode: int, payload: bytes) -> bytearray:
    """Construct standard 18-byte August command packet with checksum."""
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = opcode
    pkt[2] = 0x00
    pkt[3] = 0x00
    if payload:
        pkt[4 : 4 + len(payload)] = payload[:12]
    pkt[16] = 0x02
    pkt[17] = 0x00
    pkt[3] = yalexs_util._simple_checksum(pkt)
    return pkt


def build_set_rtc_packet(timestamp: datetime | int | None = None) -> bytearray:
    """Build CMD_SET_RTC (0x10) packet (fallback for yalexs-ble without PushLock.set_rtc)."""
    if timestamp is None:
        ts = int(datetime.now(UTC).timestamp())
    elif isinstance(timestamp, datetime):
        ts = int(timestamp.timestamp())
    elif isinstance(timestamp, int) and not isinstance(timestamp, bool):
        if timestamp < 0:
            raise ValueError("Timestamp must be non-negative.")
        ts = timestamp
    else:
        raise TypeError(f"Invalid timestamp type: {type(timestamp)}")

    payload = bytearray(12)
    payload[0:4] = struct.pack("<I", ts)
    return build_pin_packet(CMD_SET_RTC, bytes(payload))


def build_set_pin_packet(pin: str) -> bytearray:
    """Build CMD_KEYCODE_SET (0x27) packet (fallback for temporary schedule path)."""
    payload = bytearray(12)
    payload[0:7] = encode_packed_bcd_pin(pin)
    payload[8] = CREDENTIAL_TYPE_PIN
    return build_pin_packet(CMD_KEYCODE_SET, bytes(payload))


def build_schedule_packet(
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> bytearray:
    """Build CMD_KEYCODE_ACCESS (0x2B) packet (fallback for temporary schedule path)."""
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
    """Build CMD_KEYCODE_COMMIT (0x2C) packet (fallback for temporary schedule path)."""
    if slot < 1:
        raise ValueError("Slot must be 1 or higher.")
    payload = bytearray(12)
    payload[0:7] = encode_packed_bcd_pin(pin)
    payload[7] = slot & 0xFF
    payload[8] = CREDENTIAL_TYPE_PIN
    payload[9] = (slot >> 8) & 0xFF
    return build_pin_packet(CMD_KEYCODE_COMMIT, bytes(payload))


def check_pin_response_error(response: bytes, expected_opcode: int) -> None:
    """Verify response frame and raise YalePinError if the operation failed."""
    if len(response) < 16:
        raise YalePinError(
            f"Invalid response length ({len(response)} bytes), expected at least 16 bytes."
        )

    if response[0] not in (0xAA, 0xBB):
        raise YalePinError(f"Unexpected response header 0x{response[0]:02X}")

    if response[1] != expected_opcode:
        raise YalePinError(
            f"Response opcode mismatch: expected 0x{expected_opcode:02X}, got 0x{response[1]:02X}"
        )

    err_code = response[15]
    if err_code != 0:
        err_enum = VALUE_TO_OPERATION_ERROR.get(err_code)
        err_name = err_enum.name if err_enum is not None else f"UNKNOWN_ERROR_0x{err_code:02X}"
        raise YalePinError(
            f"Lock rejected opcode 0x{expected_opcode:02X}: {err_name} (code 0x{err_code:02X})",
            code=err_code,
        )
