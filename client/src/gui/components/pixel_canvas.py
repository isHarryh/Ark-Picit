"""Interactive pixel-art canvas widget with undo/redo support and dynamic sizing."""

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme

from src.core.pic import ArkPic

_UNDO_LIMIT = 100


def _flood_fill(pic: ArkPic, x: int, y: int, replace_id: int) -> None:
    """Replace all connected pixels with the same value as (x, y)."""
    target = pic.get(x, y)
    if target == replace_id:
        return
    w, h = pic.rule.width, pic.rule.height
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if cx < 0 or cx >= w or cy < 0 or cy >= h:
            continue
        if pic.get(cx, cy) != target:
            continue
        pic.set(cx, cy, replace_id)
        stack.append((cx + 1, cy))
        stack.append((cx - 1, cy))
        stack.append((cx, cy + 1))
        stack.append((cx, cy - 1))


class PixelCanvas(QWidget):
    """A scalable, clickable pixel grid for painting.

    The canvas dynamically resizes to fit its parent while maintaining the
    pixel grid's aspect ratio.

    Emits:
        - :attr:`contentChanged`: whenever pixels are modified.
        - :attr:`undoAvailabilityChanged`: undo becomes (un)available.
        - :attr:`redoAvailabilityChanged`: redo becomes (un)available.
    """

    contentChanged = Signal()
    undoAvailabilityChanged = Signal(bool)
    redoAvailabilityChanged = Signal(bool)

    def __init__(self, pic: ArkPic, parent=None):
        super().__init__(parent)
        self._pic = pic
        self._color_id = pic.rule.default_color_id
        self._tool: str = "paint"  # "paint" | "fill"
        self._painting = False
        self._hover: QPoint | None = None
        self._undo_stack: list[list[list[int]]] = []
        self._redo_stack: list[list[list[int]]] = []
        self._scale = 20  # recalculated on resize

        self.setMouseTracking(True)
        self.setMinimumSize(100, 100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def pic(self) -> ArkPic:
        return self._pic

    def set_color_id(self, cid: int) -> None:
        self._color_id = cid

    def set_tool(self, tool: str) -> None:
        self._tool = tool

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self) -> None:
        """Undo the last operation. Does nothing if stack is empty."""
        if not self._undo_stack:
            return
        self._redo_stack.append(self._pic.snapshot())
        snap = self._undo_stack.pop()
        self._pic.restore(snap)
        self.contentChanged.emit()
        self.undoAvailabilityChanged.emit(self.can_undo)
        self.redoAvailabilityChanged.emit(self.can_redo)
        self.update()

    def redo(self) -> None:
        """Redo the last undone operation."""
        if not self._redo_stack:
            return
        self._undo_stack.append(self._pic.snapshot())
        snap = self._redo_stack.pop()
        self._pic.restore(snap)
        self.contentChanged.emit()
        self.undoAvailabilityChanged.emit(self.can_undo)
        self.redoAvailabilityChanged.emit(self.can_redo)
        self.update()

    def clear(self) -> None:
        """Fill entire canvas with the default color."""
        self._push_undo()
        self._pic.fill_default()
        self.contentChanged.emit()
        self.update()

    # ------------------------------------------------------------------
    # Undo / Redo stack
    # ------------------------------------------------------------------

    def _push_undo(self) -> None:
        """Snapshot current state before a modification."""
        self._undo_stack.append(self._pic.snapshot())
        if len(self._undo_stack) > _UNDO_LIMIT:
            self._undo_stack.pop(0)
        # Clear redo stack on new action
        self._redo_stack.clear()
        self.undoAvailabilityChanged.emit(True)
        self.redoAvailabilityChanged.emit(False)

    # ------------------------------------------------------------------
    # Dynamic scaling
    # ------------------------------------------------------------------

    def _recalculate_scale(self) -> None:
        """Compute pixel scale to fit the widget while keeping aspect ratio."""
        w, h = self._pic.rule.width, self._pic.rule.height
        if w <= 0 or h <= 0:
            return
        cw, ch = self.width(), self.height()
        if cw <= 0 or ch <= 0:
            return
        self._scale = max(1, min(cw // w, ch // h))

    def resizeEvent(self, _event) -> None:
        self._recalculate_scale()
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        s = self._scale
        if s < 1:
            return

        w = self._pic.rule.width
        h = self._pic.rule.height
        dark = isDarkTheme()

        # Grid color: #EEEEEE in light, slightly lighter in dark
        grid_color = QColor("#EEEEEE") if not dark else QColor(40, 40, 40)
        grid_pen = QPen(grid_color)
        grid_pen.setWidth(1)

        # Offset to center the grid
        ox = (self.width() - w * s) // 2
        oy = (self.height() - h * s) // 2
        painter.translate(ox, oy)

        for y in range(h):
            for x in range(w):
                rect = QRect(x * s, y * s, s, s)
                cid = self._pic.get(x, y)
                hex_color = self._pic.rule.colors[cid - 1]
                painter.fillRect(rect, QColor(f"#{hex_color}"))

        # Grid lines
        painter.setPen(grid_pen)
        for x in range(w + 1):
            painter.drawLine(x * s, 0, x * s, h * s)
        for y in range(h + 1):
            painter.drawLine(0, y * s, w * s, y * s)

        # Hover highlight
        if self._hover is not None:
            hx = (self._hover.x() - ox) // s
            hy = (self._hover.y() - oy) // s
            if 0 <= hx < w and 0 <= hy < h:
                hover_pen = QPen(QColor(0, 120, 215))
                hover_pen.setWidth(2)
                painter.setPen(hover_pen)
                painter.drawRect(QRect(hx * s, hy * s, s, s))

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------

    def _pixel_coords(self, pos: QPoint) -> tuple[int, int]:
        """Convert widget coordinates to pixel grid coordinates."""
        s = self._scale
        w = self._pic.rule.width
        h = self._pic.rule.height
        ox = (self.width() - w * s) // 2
        oy = (self.height() - h * s) // 2
        return (pos.x() - ox) // s, (pos.y() - oy) // s

    def _apply(self, x: int, y: int) -> None:
        if not (0 <= x < self._pic.rule.width and 0 <= y < self._pic.rule.height):
            return

        if self._tool == "fill":
            _flood_fill(self._pic, x, y, self._color_id)
            self.contentChanged.emit()
            self.update()
        else:  # paint
            if self._pic.get(x, y) != self._color_id:
                self._pic.set(x, y, self._color_id)
                self.contentChanged.emit()
                self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        x, y = self._pixel_coords(event.position().toPoint())

        if event.button() == Qt.MouseButton.LeftButton:
            self._push_undo()
            self._apply(x, y)
            self._painting = True
        elif event.button() == Qt.MouseButton.RightButton:
            old_id = self._color_id
            self._color_id = self._pic.rule.default_color_id
            self._push_undo()
            self._apply(x, y)
            self._color_id = old_id
            self._painting = True

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover = event.position().toPoint()
        self.update()

        if self._painting:
            x, y = self._pixel_coords(self._hover)
            self._apply(x, y)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._painting = False

    def leaveEvent(self, _event: QEvent) -> None:
        self._hover = None
        self.update()
