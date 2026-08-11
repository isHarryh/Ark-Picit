"""GamePaintTask: orchestrates the in-game detection and painting flows.

The heavy lifting lives in :mod:`src.core.tasks.canvas` (calibration and
content reading) and :mod:`src.core.tasks.paint` (painting); this class
wires them to worker threads and Qt signals.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

import cv2
from PySide6.QtCore import QObject, Signal

from src.auto import Automator, Device
from src.auto.base import MatchResult
from src.core.pic import ArkPic
from src.core.rule import ArkPicRule
from src.core.tasks.canvas import (
    CanvasLayout,
    GameTaskError,
    calibrate_canvas_layout,
    read_diff_cells,
)
from src.core.tasks.paint import CELL_CLICK_DELAY_MS, paint_canvas
from src.utils.paths import SCREENSHOT_DIR
from src.utils.user_message import UserMessage

logger = logging.getLogger(__name__)


class GamePaintTask(QObject):
    """Run the in-game detection and painting flows in worker threads.

    Emits :attr:`statusChanged` during execution, then either
    :attr:`succeeded` with the recognized layout and the path of an annotated
    verification screenshot, or :attr:`failed` with a localized message.
    """

    statusChanged = Signal(object)  # UserMessage step description
    succeeded = Signal(object, str, object)  # CanvasLayout, verification image path, diff cells
    drawingFinished = Signal(object)  # UserMessage success message
    failed = Signal(object)  # UserMessage error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._automator: Automator | None = None
        self._layout: CanvasLayout | None = None
        self._pic: ArkPic | None = None
        self._rule: ArkPicRule | None = None
        self._incremental = True
        self._click_delay_ms = CELL_CLICK_DELAY_MS
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
            self.failed.emit(UserMessage("task.already_running"))
            return
        self._running = True
        threading.Thread(target=self._run, args=(device, rule, pic), daemon=True).start()

    def start_drawing(self, incremental: bool = True, click_delay_ms: int = CELL_CLICK_DELAY_MS) -> None:
        """Begin painting after the user confirms the verification screenshot.

        With *incremental* enabled, only cells whose current in-game color
        differs from the painting are painted; a painting that already
        matches is skipped entirely. *click_delay_ms* is the pause between
        cell clicks; faster speeds may cause the game to miss clicks.
        Requires a successful detection first; otherwise a :attr:`failed`
        signal is emitted.
        """
        if self._automator is None or self._layout is None or self._pic is None:
            self.failed.emit(UserMessage("task.no_verified_layout"))
            return
        if self._running:
            self.failed.emit(UserMessage("task.already_running"))
            return
        self._incremental = incremental
        self._click_delay_ms = click_delay_ms
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
        if isinstance(exc, GameTaskError):
            message = UserMessage(
                exc.code,
                exc.params,
                f"{exc} (error screenshot: {error_path})",
            )
        else:
            message = UserMessage(
                "task.generic",
                {},
                f"{exc} (error screenshot: {error_path})",
            )
        self.failed.emit(message)

    def _run(self, device: Device, rule: ArkPicRule, pic: ArkPic) -> None:
        automator = Automator(device)
        try:
            layout = calibrate_canvas_layout(automator, rule, self.statusChanged.emit)
            self.statusChanged.emit(UserMessage("task.reading_canvas_content"))
            diff_cells = read_diff_cells(automator, layout, rule, pic)
            self.statusChanged.emit(UserMessage("task.generating_verification_screenshot"))
            image_path = self._save_verification_image(automator, layout)
        except GameTaskError as exc:
            self._fail(automator, exc)
            return
        except Exception as exc:
            logger.exception("In-game canvas detection failed")
            self._running = False
            self.failed.emit(UserMessage("task.generic", {}, str(exc)))
            return
        self._running = False
        self._automator = automator
        self._layout = layout
        self._pic = pic
        self._rule = rule
        self._diff_cells = diff_cells
        self.succeeded.emit(layout, image_path, diff_cells)

    def _draw(self) -> None:
        automator = self._automator
        layout = self._layout
        rule = self._rule
        pic = self._pic
        assert automator is not None and layout is not None and rule is not None and pic is not None
        try:
            message = paint_canvas(
                automator,
                layout,
                rule,
                pic,
                incremental=self._incremental,
                diff_cells=self._diff_cells,
                click_delay_ms=self._click_delay_ms,
                report=self.statusChanged.emit,
            )
        except GameTaskError as exc:
            self._fail(automator, exc)
            self.cancel()
            return
        except Exception as exc:
            logger.exception("In-game drawing failed")
            self._running = False
            self.cancel()
            self.failed.emit(UserMessage("task.generic", {}, str(exc)))
            return
        self._running = False
        self.cancel()
        self.drawingFinished.emit(message)

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
