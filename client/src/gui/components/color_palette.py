"""Color palette widget showing swatches from an ArkPicRule."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import StrongBodyLabel

from src.core.rule import ArkPicRule


class _Swatch(QWidget):
    """A single color square that emits its id on click."""

    clicked = Signal(int)  # color_id (1-based)

    def __init__(self, color_id: int, hex_color: str, size: int = 32, parent=None):
        super().__init__(parent)
        self._cid = color_id
        self._hex = hex_color
        self._selected = False
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def color_id(self) -> int:
        return self._cid

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(f"#{self._hex}"))
        if self._selected:
            pen = QPen(QColor(0, 120, 215))
            pen.setWidth(3)
            p.setPen(pen)
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def mousePressEvent(self, _event):
        self.clicked.emit(self._cid)


class ColorPalette(QWidget):
    """Scrollable palette of clickable color swatches.

    Emits :attr:`colorSelected` with the 1-based color id.
    """

    colorSelected = Signal(int)

    def __init__(self, rule: ArkPicRule, parent=None):
        super().__init__(parent)
        self._rule = rule
        self._selected_id = rule.default_color_id
        self._swatches: list[_Swatch] = []
        self._build_ui()
        self._highlight_selected()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(StrongBodyLabel(self.tr("PaletteTitle")))

        # Swatch grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(4)
        cols = 4
        for i, hex_color in enumerate(self._rule.colors):
            cid = i + 1
            sw = _Swatch(cid, hex_color)
            sw.clicked.connect(self._on_click)
            self._swatches.append(sw)
            grid.addWidget(sw, i // cols, i % cols)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def _on_click(self, cid: int) -> None:
        self._selected_id = cid
        self._highlight_selected()
        self.colorSelected.emit(cid)

    def _highlight_selected(self) -> None:
        for sw in self._swatches:
            sw.set_selected(sw.color_id == self._selected_id)

    @property
    def selected_id(self) -> int:
        return self._selected_id
