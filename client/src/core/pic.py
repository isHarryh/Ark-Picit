"""ArkPic — a pixel-art painting bound to an ArkPicRule.

All pixels always have a valid color ID (1-based into ``rule.colors``).
There are no empty pixels — the canvas is initialized to ``rule.default_color_id``.
"""

from __future__ import annotations

from src.core.rule import ArkPicRule


class ArkPic:
    """A painting consisting of color IDs laid out on a 2-D grid.

    Pixels are stored as ``self.grid[y][x]`` where each value is a 1-based
    color ID into :attr:`rule.colors`.  The value 0 is never permitted.

    Args:
        rule: The rule governing dimensions, palette, and default color.
    """

    def __init__(self, rule: ArkPicRule) -> None:
        self.rule = rule
        default = rule.default_color_id
        self.grid: list[list[int]] = [
            [default for _ in range(rule.width)]
            for _ in range(rule.height)
        ]

    # ------------------------------------------------------------------
    # Pixel access
    # ------------------------------------------------------------------

    def get(self, x: int, y: int) -> int:
        """Return the color ID at ``(x, y)``."""
        return self.grid[y][x]

    def set(self, x: int, y: int, color_id: int) -> None:
        """Set the pixel at ``(x, y)`` to *color_id* (must be >= 1)."""
        if not (0 <= x < self.rule.width):
            raise IndexError(f"x out of range: {x}")
        if not (0 <= y < self.rule.height):
            raise IndexError(f"y out of range: {y}")
        if not (1 <= color_id <= len(self.rule.colors)):
            raise ValueError(
                f"color_id must be 1-{len(self.rule.colors)}, got {color_id}"
            )
        self.grid[y][x] = color_id

    def set_color(self, x: int, y: int, hex_color: str) -> None:
        """Set the pixel using a hex color string (must exist in the palette)."""
        cid = self.rule.color_id_of(hex_color)
        if cid == 0:
            raise ValueError(f"Color {hex_color!r} not in rule palette")
        self.set(x, y, cid)

    def fill_flat(self, ids: list[int]) -> None:
        """Fill the entire grid from a flat row-major list of color IDs."""
        expected = self.rule.width * self.rule.height
        if len(ids) != expected:
            raise ValueError(f"Expected {expected} ids, got {len(ids)}")
        for cid in ids:
            if not (1 <= cid <= len(self.rule.colors)):
                raise ValueError(f"Invalid color_id {cid} (must be 1-{len(self.rule.colors)})")
        for y in range(self.rule.height):
            row = ids[y * self.rule.width : (y + 1) * self.rule.width]
            self.grid[y] = list(row)

    def fill_default(self) -> None:
        """Reset every pixel to the rule's default color."""
        d = self.rule.default_color_id
        for y in range(self.rule.height):
            for x in range(self.rule.width):
                self.grid[y][x] = d

    @property
    def flat(self) -> list[int]:
        """Return all color IDs as a flat row-major list."""
        return [v for row in self.grid for v in row]

    def snapshot(self) -> list[list[int]]:
        """Return a deep copy of the grid for undo purposes."""
        return [row[:] for row in self.grid]

    def restore(self, snap: list[list[int]]) -> None:
        """Restore grid from a snapshot."""
        self.grid = [row[:] for row in snap]

    def __repr__(self) -> str:
        return f"ArkPic({self.rule})"
