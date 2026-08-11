"""ArkPicCode — URL-safe Base64 share codes (zlib-compressed).

Wire format (before compression)::

    [U8 w][U8 h][U16 hash]
    [U8 name_len][name_bytes...]
    [U8 desc_len][desc_bytes...]
    [U8 * (w*h)]
    [0x00]

The ``hash`` is the CRC-16/CCITT of the ArkPicRule (palette + default id).
Name and description are UTF-8 encoded, each prefixed with a U8 length (0-255).
All pixel IDs are >= 1 (no empty pixels).
"""

from __future__ import annotations

import base64
import struct
import zlib

from src.core.pic import ArkPic
from src.core.rule import ArkPicRule

_HEADER_FMT = ">BBH"
_HEADER_SIZE = 4
_TERMINATOR = b"\x00"


class CodeError(ValueError):
    """Raised when an ArkPicCode is malformed, corrupted or out of limits.

    The message carries the raw diagnostic text (Base64/compression errors,
    truncated data, size violations...); it is not localized. The GUI shows
    a generic "cannot parse" text and passes the message through.
    """


class CodeMismatchError(CodeError):
    """Raised when a structurally valid code does not match the current ruleset.

    ``code`` and ``params`` describe the mismatch for localized display; the
    message string is the raw diagnostic text.
    """

    def __init__(self, message: str, *, code: str, params=None):
        super().__init__(message)
        self.code = code
        self.params = dict(params or {})


class DecodedPic:
    """Result of decode(): painting plus optional metadata."""

    def __init__(self, pic: ArkPic, name: str = "", description: str = ""):
        self.pic = pic
        self.name = name
        self.description = description


def _pack_varstring(text: str) -> bytes:
    """Encode a string as [U8 len][UTF-8 bytes], clamped to 255."""
    encoded = text.encode("utf-8")[:255]
    return bytes([len(encoded)]) + encoded


def _unpack_varstring(data: bytes, offset: int) -> tuple[str, int]:
    """Decode a varstring at *offset*. Returns (text, new_offset)."""
    if offset >= len(data):
        raise CodeError("Truncated varstring length")
    length = data[offset]
    offset += 1
    if offset + length > len(data):
        raise CodeError("Truncated varstring content")
    text = data[offset:offset + length].decode("utf-8", errors="replace")
    return text, offset + length


def encode(pic: ArkPic, name: str = "", description: str = "") -> str:
    """Serialize *pic* with optional metadata into a compressed Base64 string."""
    rule = pic.rule
    ids = pic.flat

    for i, cid in enumerate(ids):
        if not (1 <= cid <= 255):
            raise CodeError(f"Pixel id {cid} out of Uint8 range at index {i}")

    header = struct.pack(_HEADER_FMT, rule.width, rule.height, rule.color_hash)
    name_bytes = _pack_varstring(name)
    desc_bytes = _pack_varstring(description)
    body = bytes(ids)
    raw = header + name_bytes + desc_bytes + body + _TERMINATOR
    compressed = zlib.compress(raw, 9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def decode(code: str, rule: ArkPicRule) -> DecodedPic:
    """Deserialize an ArkPicCode back into a :class:`DecodedPic`."""
    padded = code + "=" * (-len(code) % 4)
    try:
        compressed = base64.urlsafe_b64decode(padded)
    except Exception as e:
        raise CodeError(f"Invalid Base64: {e}") from e

    try:
        raw = zlib.decompress(compressed)
    except zlib.error as e:
        raise CodeError(f"Invalid compressed data: {e}") from e

    if len(raw) < _HEADER_SIZE + 1:
        raise CodeError(f"Data too short: {len(raw)} bytes")

    width, height, stored_hash = struct.unpack(_HEADER_FMT, raw[:_HEADER_SIZE])

    if width != rule.width or height != rule.height:
        raise CodeMismatchError(
            f"Dimension mismatch: code is {width}x{height}, rule is "
            f"{rule.width}x{rule.height}",
            code="code.dimension_mismatch",
            params={
                "code_width": width,
                "code_height": height,
                "rule_width": rule.width,
                "rule_height": rule.height,
            },
        )

    if stored_hash != rule.color_hash:
        raise CodeMismatchError(
            f"Rule hash mismatch: code has 0x{stored_hash:04X}, "
            f"rule has 0x{rule.color_hash:04X}",
            code="code.rule_hash_mismatch",
            params={
                "code_hash": f"0x{stored_hash:04X}",
                "rule_hash": f"0x{rule.color_hash:04X}",
            },
        )

    # Parse varstrings
    offset = _HEADER_SIZE
    name, offset = _unpack_varstring(raw, offset)
    description, offset = _unpack_varstring(raw, offset)

    # Remaining: pixel body + terminator
    if raw[-1:] != _TERMINATOR:
        raise CodeError("Missing or invalid terminator byte")

    body = raw[offset:-1]
    expected_pixels = width * height
    if len(body) != expected_pixels:
        raise CodeError(
            f"Pixel count mismatch: expected {expected_pixels}, got {len(body)}"
        )

    ids = list(body)
    for i, cid in enumerate(ids):
        if cid == 0:
            raise CodeError(f"Pixel id 0 found at flat index {i}")
        if cid > len(rule.colors):
            raise CodeError(
                f"Pixel id {cid} at index {i} exceeds palette size ({len(rule.colors)})"
            )

    pic = ArkPic(rule)
    pic.fill_flat(ids)
    return DecodedPic(pic, name, description)
