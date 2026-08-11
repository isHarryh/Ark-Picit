"""ArkPicRule — defines the canvas dimensions, palette, and default color."""

from __future__ import annotations

import binascii

from src.core.color import normalize_hex

# Uint8 limits
MAX_SIZE = 255
# Color IDs are non-zero Uint8, so at most 255 colors in the palette.
MAX_COLORS = 255


def rule_hash(colors: list[str]) -> int:
    """Compute a deterministic Uint16 hash (CRC-16/CCITT) of the palette.

    The palette is canonicalized (normalized + uppercased) before hashing so
    that ``["ff0000"]`` and ``["FF0000"]`` produce the same hash. Only the
    colors participate; the default color id does not.
    """
    normalized = [normalize_hex(c) for c in colors]
    return binascii.crc_hqx("".join(normalized).encode("ascii"), 0xFFFF)


class ArkPicRule:
    """A rule describing the dimensions and palette of an ArkPic painting.

    Args:
        width:  Canvas width in pixels (1-255).
        height: Canvas height in pixels (1-255).
        colors: List of ``"RRGGBB"`` hex strings.  Color IDs used in
                :class:`ArkPic` are 1-based indices into this list.
        default_color_id: 1-based ID of the default fill color (1-len(colors)).
                          New canvases are filled with this color.
    """

    def __init__(
        self,
        width: int,
        height: int,
        colors: list[str],
        default_color_id: int = 1,
    ) -> None:
        if not (1 <= width <= MAX_SIZE):
            raise ValueError(f"width must be 1-{MAX_SIZE}, got {width}")
        if not (1 <= height <= MAX_SIZE):
            raise ValueError(f"height must be 1-{MAX_SIZE}, got {height}")
        colors = [normalize_hex(c) for c in colors]
        if len(colors) > MAX_COLORS:
            raise ValueError(f"at most {MAX_COLORS} colors, got {len(colors)}")
        if not (1 <= default_color_id <= len(colors)):
            raise ValueError(
                f"default_color_id must be 1-{len(colors)}, got {default_color_id}"
            )

        self.width = width
        self.height = height
        self.colors = colors
        self.default_color_id = default_color_id

    @property
    def color_hash(self) -> int:
        """Uint16 hash of the palette, used in ArkPicCode."""
        return rule_hash(self.colors)

    def color_id_of(self, hex_color: str) -> int:
        """Return the 1-based ID for *hex_color*, or 0 if not in the palette."""
        target = normalize_hex(hex_color)
        for i, c in enumerate(self.colors):
            if c == target:
                return i + 1
        return 0

    def __repr__(self) -> str:
        return (
            f"ArkPicRule(width={self.width}, height={self.height}, "
            f"colors={len(self.colors)}, default={self.default_color_id})"
        )
