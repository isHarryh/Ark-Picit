"""In-game painting: select palette colors and click canvas cells.

Pure task helper used by the paint flow. Step progress is reported through
an optional ``report`` callable.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.auto import Automator
from src.auto.base import MatchResult, Point, Region
from src.core.color import hex_to_bgr, rgb_to_hex
from src.core.pic import ArkPic
from src.core.rule import ArkPicRule
from src.core.tasks.canvas import CanvasLayout, GameTaskError

PALETTE_WINDOW_SIZE = (32, 32)  # solid color template window
PALETTE_COLOR_TOLERANCE = 5  # max per-channel distance from the target color
PALETTE_COLOR_COVERAGE = 0.95  # required matched fraction of the window
PALETTE_DRAG_DURATION_MS = 200
PALETTE_DRAG_ANCHOR_X = 0.2  # horizontal drag anchor as a palette width fraction
PALETTE_DRAG_TOP = 0.2  # start/end y as a palette height fraction
PALETTE_DRAG_BOTTOM = 0.8  # end/start y as a palette height fraction
PALETTE_SCROLL_SETTLE_MS = 400
PALETTE_SCROLL_TIMEOUT_MS = 5000
PALETTE_CLICK_HOLD_MS = 100  # hold the swatch press; games may miss instantaneous clicks
PALETTE_SELECT_DELAY_S = 0.25  # wait for the swatch selection to register
CELL_CLICK_DELAY_MS = 67  # default pause between canvas cell clicks (Normal speed)

_SKIP_MESSAGE = (
    "The in-game canvas already matches this painting. "
    "Disable incremental mode to repaint."
)


def _noop(_message: str) -> None:
    return


def paint_canvas(
    automator: Automator,
    layout: CanvasLayout,
    rule: ArkPicRule,
    pic: ArkPic,
    *,
    incremental: bool,
    diff_cells: set[tuple[int, int]],
    click_delay_ms: int = CELL_CLICK_DELAY_MS,
    report: Callable[[str], None] | None = None,
) -> str:
    """Select each used palette color and click every cell of that color.

    With *incremental* enabled, only the cells in *diff_cells* are painted;
    when nothing differs, painting is skipped entirely and the skip message
    is returned. *click_delay_ms* is the pause between cell clicks; faster
    speeds may cause the game to miss clicks.
    """
    notify = report or _noop
    if incremental and not diff_cells:
        notify("Canvas already matches painting")
        return _SKIP_MESSAGE
    for color_id in sorted({cid for cid in pic.flat if cid > 0}):
        hex_color = rule.colors[color_id - 1]
        color_bgr = hex_to_bgr(hex_color)
        notify(f"Selecting color #{hex_color}")
        match = _click_palette_color(automator, layout, color_bgr, notify)
        automator.click_match(match, hold_ms=PALETTE_CLICK_HOLD_MS)
        time.sleep(PALETTE_SELECT_DELAY_S)

        cells = _paint_cells_of_color(layout, pic, color_id, incremental, diff_cells)
        notify(f"Painting {len(cells)} cells with #{hex_color}")
        for region in cells:
            automator.click_region(region)
            time.sleep(click_delay_ms / 1000)
    notify("Drawing complete")
    return "All colors painted"


def _paint_cells_of_color(
    layout: CanvasLayout,
    pic: ArkPic,
    color_id: int,
    incremental: bool,
    diff_cells: set[tuple[int, int]],
) -> list[Region]:
    """Return the canvas cell regions to paint for *color_id*.

    Matching cells are skipped in incremental mode.
    """
    cells: list[Region] = []
    for row in range(layout.rows):
        for col in range(layout.cols):
            if pic.grid[row][col] != color_id:
                continue
            if incremental and (row, col) not in diff_cells:
                continue
            cells.append(layout.cell_region(row, col))
    return cells


def _click_palette_color(
    automator: Automator,
    layout: CanvasLayout,
    color_bgr: tuple[int, int, int],
    notify: Callable[[str], None],
) -> MatchResult:
    """Find the *color_bgr* swatch in the palette, scrolling up then down as needed.

    Raises GameTaskError when the color cannot be found after both scrolls.
    """
    # Each iteration retries after one palette scroll; None checks the
    # palette as-is before any scrolling.
    scrolls = (
        (None, ""),
        (False, "Palette color not visible, scrolling up..."),
        (True, "Palette color still not visible, scrolling back down..."),
    )
    for down, message in scrolls:
        match = _find_palette_color(automator, layout, color_bgr)
        if match is not None:
            return match
        if down is None:
            continue
        notify(message)
        start, end = _palette_drag_points(layout, down=down)
        automator.drag_point(start, end, duration_ms=PALETTE_DRAG_DURATION_MS)
        _settle_palette(automator, layout)
    raise GameTaskError(
        f"Color not found in palette: #{rgb_to_hex(color_bgr[2], color_bgr[1], color_bgr[0])}"
    )


def _find_palette_color(
    automator: Automator,
    layout: CanvasLayout,
    color_bgr: tuple[int, int, int],
) -> MatchResult | None:
    return automator.find_color(
        color_bgr,
        layout.palette,
        window_size=PALETTE_WINDOW_SIZE,
        tolerance=PALETTE_COLOR_TOLERANCE,
        coverage=PALETTE_COLOR_COVERAGE,
    )


def _settle_palette(automator: Automator, layout: CanvasLayout) -> None:
    automator.wait_stable(
        layout.palette,
        quiet_ms=PALETTE_SCROLL_SETTLE_MS,
        timeout_ms=PALETTE_SCROLL_TIMEOUT_MS,
        interval_ms=100,
    )


def _palette_drag_points(layout: CanvasLayout, *, down: bool) -> tuple[Point, Point]:
    """Return the exact palette drag endpoints (no randomization).

    Dragging down goes from the 20%/20% point to the 20%/80% point of the
    palette; dragging up is the reverse gesture.
    """
    palette = layout.palette
    x = palette.x + round(PALETTE_DRAG_ANCHOR_X * palette.w)
    top = Point(x, palette.y + round(PALETTE_DRAG_TOP * palette.h))
    bottom = Point(x, palette.y + round(PALETTE_DRAG_BOTTOM * palette.h))
    return (top, bottom) if down else (bottom, top)
