"""Color helpers for the ``RRGGBB`` hex format used throughout Ark Picit."""

from __future__ import annotations

RGB = tuple[int, int, int]  # (red, green, blue), each 0-255


def normalize_hex(hex_str: str) -> str:
    """Return an uppercase 6-digit hex string without leading ``#``."""
    s = hex_str.strip().lstrip("#").upper()
    if len(s) != 6 or any(c not in "0123456789ABCDEF" for c in s):
        raise ValueError(f"Invalid hex color: {hex_str!r} (expected RRGGBB)")
    return s


def hex_to_rgb(hex_str: str) -> RGB:
    """Convert ``"RRGGBB"`` to an ``(r, g, b)`` tuple."""
    s = normalize_hex(hex_str)
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert ``(r, g, b)`` to ``"RRGGBB"``."""
    return f"{r:02X}{g:02X}{b:02X}"


def hex_to_bgr(hex_str: str) -> RGB:
    """Convert ``"RRGGBB"`` to a ``(b, g, r)`` tuple (OpenCV order)."""
    r, g, b = hex_to_rgb(hex_str)
    return b, g, r
