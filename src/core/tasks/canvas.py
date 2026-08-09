"""In-game canvas calibration and content reading.

Pure task helpers shared by the paint flow and the canvas import flow.
Step progress is reported through an optional ``report`` callable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.auto import Automator
from src.auto.base import MatchResult, Point, Region
from src.core.pic import ArkPic
from src.core.quantize import quantize_image
from src.core.rule import ArkPicRule
from src.utils.paths import ASSETS_DIR

# Templates are captured at 720p short side (see assets/images/win720p).
_TEMPLATE_DIR = ASSETS_DIR / "images" / "win720p"

TEMPLATE_IN_CANVAS_1 = _TEMPLATE_DIR / "InCanvasPage1.png"
TEMPLATE_IN_CANVAS_2 = _TEMPLATE_DIR / "InCanvasPage2.png"
TEMPLATE_SLIDER = _TEMPLATE_DIR / "CanvasScaleSlider.png"
TEMPLATE_ANCHOR_LT = _TEMPLATE_DIR / "CanvasAnchorLT.png"
TEMPLATE_ANCHOR_RB = _TEMPLATE_DIR / "CanvasAnchorRB.png"

ROI_IN_CANVAS_1 = Region(30, 60, 150, 150)
ROI_IN_CANVAS_2 = Region(860, 160, 150, 150)
ROI_SLIDER = Region(30, 210, 290, 500)
ROI_ANCHOR_LT = Region(230, 90, 150, 120)
ROI_ANCHOR_RB = Region(790, 600, 150, 120)
MATCH_THRESHOLD = 0.8

SLIDER_DRAG_EDGE_MARGIN = 10  # pixels from the bottom edge of the screen
SLIDER_DRAG_DURATION_MS = 300
SETTLE_QUIET_MS = 250
SETTLE_TIMEOUT_MS = 5000

PALETTE_CELL_SPAN = 13  # palette width in canvas cell units


class GameTaskError(Exception):
    """Raised when the in-game canvas flow cannot continue."""


@dataclass(frozen=True, slots=True)
class CanvasLayout:
    """Recognized regions inside the game's canvas page.

    All coordinates are in the normalized (720p short side) space.
    """

    in_canvas_1: MatchResult
    in_canvas_2: MatchResult
    slider: MatchResult
    anchor_lt: MatchResult
    anchor_rb: MatchResult
    canvas: Region
    palette: Region
    rows: int
    cols: int
    cell_width: float
    cell_height: float
    screen_size: tuple[int, int]

    def cell_region(self, row: int, col: int) -> Region:
        """Return the drawing region of the cell at (*row*, *col*).

        Cell boundaries are rounded so the grid tiles the canvas exactly.
        """
        x0 = round(self.canvas.x + col * self.cell_width)
        y0 = round(self.canvas.y + row * self.cell_height)
        x1 = round(self.canvas.x + (col + 1) * self.cell_width)
        y1 = round(self.canvas.y + (row + 1) * self.cell_height)
        return Region(x0, y0, x1 - x0, y1 - y0)


def _noop(_message: str) -> None:
    return


def calibrate_canvas_layout(
    automator: Automator,
    rule: ArkPicRule,
    report: Callable[[str], None] | None = None,
) -> CanvasLayout:
    """Detect the canvas page, zoom out via the scale slider and recognize regions.

    Verifies the In Canvas page icons, drags the scale slider to the bottom
    edge, then locates the anchors and builds the canvas/palette layout.
    Any failed template match raises :class:`GameTaskError`.
    """
    notify = report or _noop
    notify("Checking canvas page...")
    in_canvas_1 = automator.find_template(
        TEMPLATE_IN_CANVAS_1, ROI_IN_CANVAS_1, threshold=MATCH_THRESHOLD
    )
    in_canvas_2 = automator.find_template(
        TEMPLATE_IN_CANVAS_2, ROI_IN_CANVAS_2, threshold=MATCH_THRESHOLD
    )
    if in_canvas_1 is None or in_canvas_2 is None:
        raise GameTaskError("Not in the canvas page (In Canvas icons not found)")

    notify("Adjusting canvas zoom...")
    slider = automator.find_template(TEMPLATE_SLIDER, ROI_SLIDER, threshold=MATCH_THRESHOLD)
    if slider is None:
        raise GameTaskError("Canvas scale slider not found")
    screen_width, screen_height = automator.screen_size
    # Drag the slider from its match center straight down to the bottom edge;
    # all drags are exact point-to-point operations, never randomized.
    start = slider.center
    end = Point(start.x, screen_height - SLIDER_DRAG_EDGE_MARGIN)
    automator.drag_point(start, end, duration_ms=SLIDER_DRAG_DURATION_MS)
    automator.wait_stable(
        quiet_ms=SETTLE_QUIET_MS, timeout_ms=SETTLE_TIMEOUT_MS, interval_ms=100
    )

    notify("Locating canvas and palette...")
    anchor_lt = automator.find_template(TEMPLATE_ANCHOR_LT, ROI_ANCHOR_LT, threshold=MATCH_THRESHOLD)
    anchor_rb = automator.find_template(TEMPLATE_ANCHOR_RB, ROI_ANCHOR_RB, threshold=MATCH_THRESHOLD)
    if anchor_lt is None or anchor_rb is None:
        raise GameTaskError("Canvas anchors not found")
    return _build_layout(
        in_canvas_1,
        in_canvas_2,
        slider,
        anchor_lt,
        anchor_rb,
        rule,
        (screen_width, screen_height),
    )


def read_canvas_pic(automator: Automator, layout: CanvasLayout, rule: ArkPicRule) -> ArkPic:
    """Quantize the current in-game canvas content into an ArkPic."""
    screen = automator.scale.screen_normalized(automator.screenshot())
    canvas = layout.canvas
    crop = screen[canvas.y : canvas.y + canvas.h, canvas.x : canvas.x + canvas.w].copy()
    return quantize_image(crop, rule, color_match="voting")


def read_diff_cells(
    automator: Automator,
    layout: CanvasLayout,
    rule: ArkPicRule,
    pic: ArkPic,
) -> set[tuple[int, int]]:
    """Return the cells whose current in-game color differs from *pic*."""
    game_pic = read_canvas_pic(automator, layout, rule)
    return {
        (row, col)
        for row in range(rule.height)
        for col in range(rule.width)
        if game_pic.grid[row][col] != pic.grid[row][col]
    }


def read_game_canvas(
    automator: Automator,
    rule: ArkPicRule,
    report: Callable[[str], None] | None = None,
) -> ArkPic:
    """Calibrate the canvas page and read its content as an ArkPic.

    Used by the canvas import flow; combines calibration with content reading.
    """
    layout = calibrate_canvas_layout(automator, rule, report)
    return read_canvas_pic(automator, layout, rule)


def _build_layout(
    in_canvas_1: MatchResult,
    in_canvas_2: MatchResult,
    slider: MatchResult,
    anchor_lt: MatchResult,
    anchor_rb: MatchResult,
    rule: ArkPicRule,
    screen_size: tuple[int, int],
) -> CanvasLayout:
    # The canvas spans from the top-left anchor's bottom-right corner to
    # the bottom-right anchor's top-left corner.
    canvas_tl = Point(anchor_lt.point.x + anchor_lt.width, anchor_lt.point.y + anchor_lt.height)
    canvas_br = Point(anchor_rb.point.x, anchor_rb.point.y)
    canvas_width = canvas_br.x - canvas_tl.x
    canvas_height = canvas_br.y - canvas_tl.y
    if canvas_width <= 0 or canvas_height <= 0:
        raise GameTaskError("Invalid canvas anchor positions")
    canvas = Region(canvas_tl.x, canvas_tl.y, canvas_width, canvas_height)

    # The palette starts at the second In Canvas icon's bottom-left corner,
    # extends right by PALETTE_CELL_SPAN canvas cell widths and down to
    # the bottom-right anchor's top edge.
    cols = rule.width
    rows = rule.height
    cell_width = canvas_width / cols
    palette_x = in_canvas_2.point.x
    palette_y = in_canvas_2.point.y + in_canvas_2.height
    palette_width = round(PALETTE_CELL_SPAN * cell_width)
    palette_height = canvas_br.y - palette_y
    if palette_width <= 0 or palette_height <= 0:
        raise GameTaskError("Invalid palette region")
    palette = Region(palette_x, palette_y, palette_width, palette_height)

    return CanvasLayout(
        in_canvas_1=in_canvas_1,
        in_canvas_2=in_canvas_2,
        slider=slider,
        anchor_lt=anchor_lt,
        anchor_rb=anchor_rb,
        canvas=canvas,
        palette=palette,
        rows=rows,
        cols=cols,
        cell_width=cell_width,
        cell_height=canvas_height / rows,
        screen_size=screen_size,
    )
