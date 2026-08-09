"""In-game canvas detection and painting preparation flow.

The task verifies that the game is on the canvas page, zooms the canvas out
via the scale slider, then recognizes the drawing canvas, its cell grid and
the palette region. Any template matching failure aborts the task with an
error message.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
from PySide6.QtCore import QObject, Signal

from src.auto import Automator, Device
from src.auto.base import MatchResult, Point, Region
from src.core.color import hex_to_bgr, rgb_to_hex
from src.core.pic import ArkPic
from src.core.quantize import quantize_image
from src.core.rule import ArkPicRule
from src.utils.paths import ASSETS_DIR, SCREENSHOT_DIR

logger = logging.getLogger(__name__)

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
SETTLE_QUIET_MS = 400
SETTLE_TIMEOUT_MS = 8000

PALETTE_WINDOW_SIZE = (32, 32)  # solid color template window
PALETTE_CELL_SPAN = 13  # palette width in canvas cell units
PALETTE_COLOR_TOLERANCE = 5  # max per-channel distance from the target color
PALETTE_COLOR_COVERAGE = 0.95  # required matched fraction of the window
PALETTE_DRAG_DURATION_MS = 250
PALETTE_DRAG_ANCHOR_X = 0.2  # horizontal drag anchor as a palette width fraction
PALETTE_DRAG_TOP = 0.2  # start/end y as a palette height fraction
PALETTE_DRAG_BOTTOM = 0.8  # end/start y as a palette height fraction
PALETTE_SCROLL_SETTLE_MS = 250
PALETTE_SCROLL_TIMEOUT_MS = 5000
PALETTE_CLICK_HOLD_MS = 100  # hold the swatch press; games may miss instantaneous clicks
PALETTE_SELECT_DELAY_MS = 0.33  # wait for the swatch selection to register
CELL_CLICK_DELAY_MS = 0.1  # pause between canvas cell clicks so none are dropped


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


class GamePaintTask(QObject):
    """Detect the in-game canvas page and recognize its drawing regions.

    Emits :attr:`statusChanged` during execution, then either
    :attr:`succeeded` with the recognized layout and the path of an annotated
    verification screenshot, or :attr:`failed` with an error message.
    """

    statusChanged = Signal(str)  # step description
    succeeded = Signal(object, str, object)  # CanvasLayout, verification image path, diff cells
    drawingFinished = Signal(str)  # success message
    failed = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._automator: Automator | None = None
        self._layout: CanvasLayout | None = None
        self._pic: ArkPic | None = None
        self._rule: ArkPicRule | None = None
        self._incremental = True
        self._diff_cells: set[tuple[int, int]] = set()

    @property
    def running(self) -> bool:
        """Return whether a task is currently running."""
        return self._running

    def start(self, device: Device, rule: ArkPicRule, pic: ArkPic) -> None:
        """Run the detection flow on *device* in a worker thread.

        A restart while running is rejected with a :attr:`failed` signal.
        """
        if self._running:
            self.failed.emit("Task is already running")
            return
        self._running = True
        threading.Thread(target=self._run, args=(device, rule, pic), daemon=True).start()

    def start_drawing(self, incremental: bool = True) -> None:
        """Begin painting after the user confirms the verification screenshot.

        With *incremental* enabled, only cells whose current in-game color
        differs from the painting are painted; a painting that already
        matches is skipped entirely. Requires a successful detection first;
        otherwise a :attr:`failed` signal is emitted.
        """
        if self._automator is None or self._layout is None or self._pic is None:
            self.failed.emit("No verified canvas layout; run detection first")
            return
        if self._running:
            self.failed.emit("Task is already running")
            return
        self._incremental = incremental
        self._running = True
        threading.Thread(target=self._draw, daemon=True).start()

    def cancel(self) -> None:
        """Discard the verified layout; no drawing is performed."""
        self._automator = None
        self._layout = None
        self._pic = None
        self._rule = None
        self._diff_cells = set()

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------

    def _fail(self, automator: Automator, exc: Exception) -> None:
        """Save an error screenshot, stop the task and emit the failure signal."""
        error_path = self._save_error_screenshot(automator)
        logger.info("Saved error screenshot: %s", error_path)
        self._running = False
        self.failed.emit(f"{exc} (error screenshot: {error_path})")

    def _run(self, device: Device, rule: ArkPicRule, pic: ArkPic) -> None:
        automator = Automator(device)
        try:
            layout, image_path, diff_cells = self._detect_canvas(automator, rule, pic)
        except GameTaskError as exc:
            self._fail(automator, exc)
            return
        except Exception as exc:
            logger.exception("In-game canvas detection failed")
            self._running = False
            self.failed.emit(str(exc))
            return
        self._running = False
        self._automator = automator
        self._layout = layout
        self._pic = pic
        self._rule = rule
        self._diff_cells = diff_cells
        self.succeeded.emit(layout, image_path, diff_cells)

    def _detect_canvas(
        self, automator: Automator, rule: ArkPicRule, pic: ArkPic
    ) -> tuple[CanvasLayout, str, set[tuple[int, int]]]:
        self.statusChanged.emit("Checking canvas page...")
        in_canvas_1 = automator.find_template(
            TEMPLATE_IN_CANVAS_1, ROI_IN_CANVAS_1, threshold=MATCH_THRESHOLD
        )
        in_canvas_2 = automator.find_template(
            TEMPLATE_IN_CANVAS_2, ROI_IN_CANVAS_2, threshold=MATCH_THRESHOLD
        )
        if in_canvas_1 is None or in_canvas_2 is None:
            raise GameTaskError("Not in the canvas page (In Canvas icons not found)")

        self.statusChanged.emit("Adjusting canvas zoom...")
        slider = automator.find_template(
            TEMPLATE_SLIDER, ROI_SLIDER, threshold=MATCH_THRESHOLD
        )
        if slider is None:
            raise GameTaskError("Canvas scale slider not found")
        screen_width, screen_height = automator.screen_size
        # Drag the slider from its match center straight down to the bottom
        # edge; all drags are exact point-to-point operations, never randomized.
        start = slider.center
        end = Point(start.x, screen_height - SLIDER_DRAG_EDGE_MARGIN)
        automator.drag_point(start, end, duration_ms=SLIDER_DRAG_DURATION_MS)
        automator.wait_stable(
            quiet_ms=SETTLE_QUIET_MS, timeout_ms=SETTLE_TIMEOUT_MS, interval_ms=200
        )

        self.statusChanged.emit("Locating canvas and palette...")
        anchor_lt = automator.find_template(
            TEMPLATE_ANCHOR_LT, ROI_ANCHOR_LT, threshold=MATCH_THRESHOLD
        )
        anchor_rb = automator.find_template(
            TEMPLATE_ANCHOR_RB, ROI_ANCHOR_RB, threshold=MATCH_THRESHOLD
        )
        if anchor_lt is None or anchor_rb is None:
            raise GameTaskError("Canvas anchors not found")
        layout = self._build_layout(
            in_canvas_1,
            in_canvas_2,
            slider,
            anchor_lt,
            anchor_rb,
            rule,
            (screen_width, screen_height),
        )

        self.statusChanged.emit("Reading canvas content...")
        diff_cells = self._read_diff_cells(automator, layout, rule, pic)

        self.statusChanged.emit("Generating verification screenshot...")
        image_path = self._save_verification_image(automator, layout)
        return layout, image_path, diff_cells

    def _read_diff_cells(
        self,
        automator: Automator,
        layout: CanvasLayout,
        rule: ArkPicRule,
        pic: ArkPic,
    ) -> set[tuple[int, int]]:
        """Convert the in-game canvas pixels and return the cells differing from *pic*."""
        screen = automator.scale.screen_normalized(automator.screenshot())
        canvas = layout.canvas
        crop = screen[canvas.y : canvas.y + canvas.h, canvas.x : canvas.x + canvas.w].copy()
        game_pic = quantize_image(crop, rule, anti_alias=True)
        return {
            (row, col)
            for row in range(rule.height)
            for col in range(rule.width)
            if game_pic.grid[row][col] != pic.grid[row][col]
        }

    def _build_layout(
        self,
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

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        automator = self._automator
        layout = self._layout
        rule = self._rule
        pic = self._pic
        assert automator is not None and layout is not None and rule is not None and pic is not None
        try:
            message = self._run_draw(automator, layout, rule, pic)
        except GameTaskError as exc:
            self._fail(automator, exc)
            self.cancel()
            return
        except Exception as exc:
            logger.exception("In-game drawing failed")
            self._running = False
            self.cancel()
            self.failed.emit(str(exc))
            return
        self._running = False
        self.cancel()
        self.drawingFinished.emit(message)

    def _run_draw(
        self,
        automator: Automator,
        layout: CanvasLayout,
        rule: ArkPicRule,
        pic: ArkPic,
    ) -> str:
        """Select each used palette color and click every cell of that color.

        With incremental mode enabled, only the cells recorded in
        :attr:`_diff_cells` are painted; when nothing differs, painting is
        skipped entirely and the skip message is returned.
        """
        if self._incremental and not self._diff_cells:
            self.statusChanged.emit("Canvas already matches painting")
            return (
                "The in-game canvas already matches this painting. "
                "Disable incremental mode to repaint."
            )
        for color_id in sorted({cid for cid in pic.flat if cid > 0}):
            hex_color = rule.colors[color_id - 1]
            color_bgr = hex_to_bgr(hex_color)
            self.statusChanged.emit(f"Selecting color #{hex_color}")
            match = self._click_palette_color(automator, layout, color_bgr)
            automator.click_match(match, hold_ms=PALETTE_CLICK_HOLD_MS)
            time.sleep(PALETTE_SELECT_DELAY_MS)

            cells = self._paint_cells_of_color(layout, pic, color_id)
            self.statusChanged.emit(f"Painting {len(cells)} cells with #{hex_color}")
            for region in cells:
                automator.click_region(region)
                time.sleep(CELL_CLICK_DELAY_MS)
        self.statusChanged.emit("Drawing complete")
        return "All colors painted"

    def _paint_cells_of_color(
        self,
        layout: CanvasLayout,
        pic: ArkPic,
        color_id: int,
    ) -> list[Region]:
        """Return the canvas cell regions to paint for *color_id*.

        Matching cells are skipped in incremental mode.
        """
        cells: list[Region] = []
        for row in range(layout.rows):
            for col in range(layout.cols):
                if pic.grid[row][col] != color_id:
                    continue
                if self._incremental and (row, col) not in self._diff_cells:
                    continue
                cells.append(layout.cell_region(row, col))
        return cells

    def _click_palette_color(
        self,
        automator: Automator,
        layout: CanvasLayout,
        color_bgr: tuple[int, int, int],
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
            match = self._find_palette_color(automator, layout, color_bgr)
            if match is not None:
                return match
            if down is None:
                continue
            self.statusChanged.emit(message)
            start, end = self._palette_drag_points(layout, down=down)
            automator.drag_point(start, end, duration_ms=PALETTE_DRAG_DURATION_MS)
            self._settle_palette(automator, layout)
        raise GameTaskError(
            f"Color not found in palette: #{rgb_to_hex(color_bgr[2], color_bgr[1], color_bgr[0])}"
        )

    def _find_palette_color(
        self,
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

    def _settle_palette(self, automator: Automator, layout: CanvasLayout) -> None:
        automator.wait_stable(
            layout.palette,
            quiet_ms=PALETTE_SCROLL_SETTLE_MS,
            timeout_ms=PALETTE_SCROLL_TIMEOUT_MS,
            interval_ms=150,
        )

    def _palette_drag_points(self, layout: CanvasLayout, *, down: bool) -> tuple[Point, Point]:
        """Return the exact palette drag endpoints (no randomization).

        Dragging down goes from the 20%/20% point to the 20%/80% point of the
        palette; dragging up is the reverse gesture.
        """
        palette = layout.palette
        x = palette.x + round(PALETTE_DRAG_ANCHOR_X * palette.w)
        top = Point(x, palette.y + round(PALETTE_DRAG_TOP * palette.h))
        bottom = Point(x, palette.y + round(PALETTE_DRAG_BOTTOM * palette.h))
        return (top, bottom) if down else (bottom, top)

    # ------------------------------------------------------------------
    # Verification screenshot
    # ------------------------------------------------------------------

    def _save_error_screenshot(self, automator: Automator) -> str:
        """Save the current screen as a diagnostic image for a failed task."""
        try:
            screen = automator.scale.screen_normalized(automator.screenshot())
        except Exception:
            logger.exception("Failed to capture error screenshot")
            return "<unavailable>"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"game_task_error_{datetime.now():%Y%m%d_%H%M%S}.png"
        cv2.imwrite(str(path), screen)
        return str(path)

    def _save_verification_image(self, automator: Automator, layout: CanvasLayout) -> str:
        """Draw the recognized regions onto a normalized screenshot and save it."""
        screen = automator.scale.screen_normalized(automator.screenshot())
        annotated = screen.copy()
        green = (0, 200, 0)
        blue = (255, 120, 0)
        yellow = (0, 215, 255)
        cyan = (255, 255, 0)
        magenta = (255, 0, 255)

        def _draw_box(result: MatchResult, color: tuple[int, int, int], label: str) -> None:
            x1, y1 = result.point.x, result.point.y
            x2, y2 = x1 + result.width, y1 + result.height
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                annotated, label, (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, color, 1, cv2.LINE_AA,
            )

        _draw_box(layout.in_canvas_1, green, "InCanvas1")
        _draw_box(layout.in_canvas_2, green, "InCanvas2")
        _draw_box(layout.slider, blue, "Slider")
        _draw_box(layout.anchor_lt, yellow, "AnchorLT")
        _draw_box(layout.anchor_rb, yellow, "AnchorRB")

        canvas = layout.canvas
        cv2.rectangle(annotated, (canvas.x, canvas.y), (canvas.x + canvas.w, canvas.y + canvas.h), cyan, 3)
        for col in range(1, layout.cols):
            x = canvas.x + round(col * layout.cell_width)
            cv2.line(annotated, (x, canvas.y), (x, canvas.y + canvas.h), cyan, 1)
        for row in range(1, layout.rows):
            y = canvas.y + round(row * layout.cell_height)
            cv2.line(annotated, (canvas.x, y), (canvas.x + canvas.w, y), cyan, 1)

        palette = layout.palette
        cv2.rectangle(annotated, (palette.x, palette.y), (palette.x + palette.w, palette.y + palette.h), magenta, 2)
        cv2.putText(
            annotated, "Palette", (palette.x, max(palette.y - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, magenta, 1, cv2.LINE_AA,
        )

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"canvas_verify_{datetime.now():%Y%m%d_%H%M%S}.png"
        cv2.imwrite(str(path), annotated)
        logger.info("Saved region verification image: %s", path)
        return str(path)


gameTask = GamePaintTask()
