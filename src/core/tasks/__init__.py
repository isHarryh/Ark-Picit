"""Reusable in-game canvas tasks shared by the paint and import flows."""

from src.core.tasks.canvas import (
    CanvasLayout,
    GameTaskError,
    calibrate_canvas_layout,
    read_canvas_pic,
    read_diff_cells,
    read_game_canvas,
)
from src.core.tasks.game_task import GamePaintTask, gameTask
from src.core.tasks.paint import CELL_CLICK_DELAY_MS, paint_canvas

__all__ = [
    "CELL_CLICK_DELAY_MS",
    "CanvasLayout",
    "GamePaintTask",
    "GameTaskError",
    "calibrate_canvas_layout",
    "gameTask",
    "paint_canvas",
    "read_canvas_pic",
    "read_diff_cells",
    "read_game_canvas",
]
