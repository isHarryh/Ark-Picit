"""ArkPicCode structural parsing for the plaza server.

Only metadata extraction and structural validation are needed server-side;
mapping pixel IDs to real colors requires a ruleset and stays a client concern.

Wire format (before compression)::

    [U8 w][U8 h][U16 hash]
    [U8 name_len][name_bytes...]
    [U8 desc_len][desc_bytes...]
    [U8 * (w*h)]
    [0x00]
"""

from __future__ import annotations

import base64
import struct
import zlib
from dataclasses import dataclass

_HEADER_FMT = ">BBH"
_HEADER_SIZE = 4
_TERMINATOR = b"\x00"
MAX_CONTENT_CHARS = 200_000  # encoded content field size limit
_MAX_UNCOMPRESSED = 512 * 1024  # decompression bomb guard


class CodeError(ValueError):
    """Raised when an ArkPicCode is malformed or too large."""


@dataclass(frozen=True)
class ParsedCode:
    """Metadata extracted from a structurally valid ArkPicCode."""

    width: int
    height: int
    name: str
    description: str


def parse_code(code: str, max_length: int = MAX_CONTENT_CHARS) -> ParsedCode:
    """Parse *code*, validating its structure and size limits."""
    if not code or len(code) > max_length:
        raise CodeError(f"Invalid content length: {len(code)}")

    padded = code + "=" * (-len(code) % 4)
    try:
        compressed = base64.urlsafe_b64decode(padded)
    except Exception as e:
        raise CodeError(f"Invalid Base64: {e}") from e

    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, _MAX_UNCOMPRESSED)
    if decompressor.unconsumed_tail or len(raw) >= _MAX_UNCOMPRESSED:
        raise CodeError("Compressed payload exceeds the size limit")
    if len(raw) < _HEADER_SIZE + 1:
        raise CodeError(f"Data too short: {len(raw)} bytes")

    width, height, _hash = struct.unpack(_HEADER_FMT, raw[:_HEADER_SIZE])
    if width < 1 or height < 1:
        raise CodeError(f"Invalid dimensions: {width}x{height}")

    offset = _HEADER_SIZE
    name, offset = _unpack_varstring(raw, offset)
    description, offset = _unpack_varstring(raw, offset)

    if raw[-1:] != _TERMINATOR:
        raise CodeError("Missing or invalid terminator byte")

    body = raw[offset:-1]
    expected = width * height
    if len(body) != expected:
        raise CodeError(f"Pixel count mismatch: expected {expected}, got {len(body)}")
    if any(b == 0 for b in body):
        raise CodeError("Pixel id 0 found in the body")

    return ParsedCode(width=width, height=height, name=name, description=description)


def _unpack_varstring(data: bytes, offset: int) -> tuple[str, int]:
    """Decode a [U8 len][UTF-8 bytes] string at *offset*."""
    if offset >= len(data):
        raise CodeError("Truncated varstring length")
    length = data[offset]
    offset += 1
    if offset + length > len(data):
        raise CodeError("Truncated varstring content")
    text = data[offset : offset + length].decode("utf-8", errors="replace")
    return text, offset + length
