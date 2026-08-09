"""Interactive image cropper widget with adjustable crop rectangle."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class ImageCropper(QWidget):
    """Displays an image with a draggable, resizable crop rectangle.

    The crop rectangle starts centered with a target aspect ratio, but the
    user can freely drag and resize it.  Pressing Enter or double-clicking
    confirms the crop.

    Emits:
        - :attr:`cropChanged`: whenever the crop rect moves.
    """

    cropChanged = Signal()

    HANDLE_SIZE = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)

        self._pixmap: QPixmap | None = None
        self._display_rect = QRect()  # area where image is drawn
        self._crop_rect = QRect()  # crop in display coordinates
        self._aspect_ratio: float | None = None  # w/h, None = free
        self._drag_mode: str | None = None  # "move" | handle id | None
        self._drag_start: QPoint = QPoint()
        self._drag_start_rect = QRect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_image(self, qimage: QImage) -> None:
        self._pixmap = QPixmap.fromImage(qimage)
        self._fit_display()
        self._init_crop()
        self.update()

    def set_aspect_ratio(self, ratio: float | None) -> None:
        """Set the crop aspect ratio (w/h), or None for free-form."""
        self._aspect_ratio = ratio
        if ratio is not None and self._crop_rect.isValid():
            self._constrain_aspect()
            self.update()
            self.cropChanged.emit()

    def get_crop_rect(self) -> QRect:
        """Return the crop rectangle in original image coordinates."""
        if self._pixmap is None or not self._crop_rect.isValid():
            return QRect()
        sx = self._pixmap.width() / max(self._display_rect.width(), 1)
        sy = self._pixmap.height() / max(self._display_rect.height(), 1)
        x = int((self._crop_rect.x() - self._display_rect.x()) * sx)
        y = int((self._crop_rect.y() - self._display_rect.y()) * sy)
        w = int(self._crop_rect.width() * sx)
        h = int(self._crop_rect.height() * sy)
        return QRect(x, y, w, h)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _fit_display(self) -> None:
        if self._pixmap is None:
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        cw, ch = self.width(), self.height()
        if cw <= 0 or ch <= 0:
            return
        scale = min(cw / pw, ch / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        dx = (cw - dw) // 2
        dy = (ch - dh) // 2
        self._display_rect = QRect(dx, dy, dw, dh)

    def _init_crop(self) -> None:
        """Place a centered crop rect covering 80% of the image."""
        if not self._display_rect.isValid():
            return
        dr = self._display_rect
        cw = int(dr.width() * 0.8)
        ch = int(dr.height() * 0.8)
        if self._aspect_ratio is not None:
            if cw / ch > self._aspect_ratio:
                cw = int(ch * self._aspect_ratio)
            else:
                ch = int(cw / self._aspect_ratio)
        cx = dr.x() + (dr.width() - cw) // 2
        cy = dr.y() + (dr.height() - ch) // 2
        self._crop_rect = QRect(cx, cy, cw, ch)

    def _constrain_aspect(self) -> None:
        if self._aspect_ratio is None or not self._crop_rect.isValid():
            return
        # Adjust height to match aspect ratio, keep center
        c = self._crop_rect
        new_h = max(1, int(c.width() / self._aspect_ratio))
        cy = c.center().y() - new_h // 2
        self._crop_rect = QRect(c.x(), cy, c.width(), new_h)
        self._clamp_crop()

    def _clamp_crop(self) -> None:
        c = self._crop_rect
        dr = self._display_rect
        if not dr.isValid():
            return
        min_size = 20
        if c.width() < min_size:
            c.setWidth(min_size)
        if c.height() < min_size:
            c.setHeight(min_size)
        if c.x() < dr.x():
            c.moveLeft(dr.x())
        if c.y() < dr.y():
            c.moveTop(dr.y())
        if c.right() > dr.right():
            c.moveRight(dr.right())
        if c.bottom() > dr.bottom():
            c.moveBottom(dr.bottom())

    def resizeEvent(self, _event) -> None:
        self._fit_display()
        if self._pixmap and not self._crop_rect.isValid():
            self._init_crop()
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Background
        p.fillRect(self.rect(), QColor(30, 30, 30))

        if self._pixmap is None or not self._display_rect.isValid():
            return

        # Draw image
        p.drawPixmap(self._display_rect, self._pixmap)

        # Dim outside crop
        c = self._crop_rect
        dim = QColor(0, 0, 0, 140)
        # Top strip
        p.fillRect(QRect(0, 0, self.width(), c.top()), dim)
        # Bottom strip
        p.fillRect(QRect(0, c.bottom() + 1, self.width(), self.height() - c.bottom() - 1), dim)
        # Left strip
        p.fillRect(QRect(0, c.top(), c.left(), c.height()), dim)
        # Right strip
        p.fillRect(QRect(c.right() + 1, c.top(), self.width() - c.right() - 1, c.height()), dim)

        # Crop border
        border_pen = QPen(QColor(0, 120, 215))
        border_pen.setWidth(2)
        p.setPen(border_pen)
        p.drawRect(c)

        # Handles
        p.setBrush(QColor(0, 120, 215))
        p.setPen(Qt.PenStyle.NoPen)
        for handle_rect in self._handle_rects(c):
            p.drawRect(handle_rect)

    def _handle_rects(self, c: QRect) -> list[QRect]:
        hs = self.HANDLE_SIZE
        return [
            QRect(c.left() - hs // 2, c.top() - hs // 2, hs, hs),          # TL
            QRect(c.right() - hs // 2, c.top() - hs // 2, hs, hs),         # TR
            QRect(c.left() - hs // 2, c.bottom() - hs // 2, hs, hs),       # BL
            QRect(c.right() - hs // 2, c.bottom() - hs // 2, hs, hs),      # BR
        ]

    def _hit_test(self, pos: QPoint) -> str | None:
        c = self._crop_rect
        if not c.isValid():
            return None
        rects = self._handle_rects(c)
        if rects[0].contains(pos):
            return "tl"
        if rects[1].contains(pos):
            return "tr"
        if rects[2].contains(pos):
            return "bl"
        if rects[3].contains(pos):
            return "br"
        if c.contains(pos):
            return "move"
        return None

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._crop_rect.isValid():
            return
        pos = event.position().toPoint()
        self._drag_mode = self._hit_test(pos)
        if self._drag_mode:
            self._drag_start = pos
            self._drag_start_rect = QRect(self._crop_rect)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._drag_mode is None:
            cursor = self._hit_test(pos)
            self.setCursor(self._cursor_for_mode(cursor) if cursor else Qt.CursorShape.ArrowCursor)
            return

        if self._drag_mode == "move":
            delta = pos - self._drag_start
            self._crop_rect = self._drag_start_rect.translated(delta)
            self._clamp_crop()
        else:
            self._resize_crop(pos)
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        if self._drag_mode is not None:
            self.cropChanged.emit()
        self._drag_mode = None

    def _resize_crop(self, pos: QPoint) -> None:
        c = QRect(self._drag_start_rect)
        if self._drag_mode == "tl":
            c.setTopLeft(pos)
        elif self._drag_mode == "tr":
            c.setTopRight(pos)
        elif self._drag_mode == "bl":
            c.setBottomLeft(pos)
        elif self._drag_mode == "br":
            c.setBottomRight(pos)

        # Normalize (in case of dragging past the opposite corner)
        c = c.normalized()

        if self._aspect_ratio is not None:
            new_h = max(1, int(c.width() / self._aspect_ratio))
            if self._drag_mode in ("tl", "bl"):
                # Keep top or bottom edge, adjust other
                old_center = self._drag_start_rect.center()
                c.setHeight(new_h)
                c.moveCenter(QPoint(c.center().x(), old_center.y()))
            else:
                old_center = self._drag_start_rect.center()
                c.setHeight(new_h)
                c.moveCenter(QPoint(c.center().x(), old_center.y()))

        self._crop_rect = c
        self._clamp_crop()

    @staticmethod
    def _cursor_for_mode(mode: str) -> Qt.CursorShape:
        return {
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
            "move": Qt.CursorShape.SizeAllCursor,
        }.get(mode, Qt.CursorShape.ArrowCursor)
