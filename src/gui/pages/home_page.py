"""Home page: welcome banner and quick-start."""

from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    PrimaryPushButton,
    StrongBodyLabel,
    TitleLabel,
)
from qfluentwidgets import FluentIcon as FIF

from src.app.signal_bus import signalBus
from src.gui.components.base_page import BasePage


class HomePage(BasePage):
    """Landing page with welcome and quick-start actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        self.viewLayout.addWidget(TitleLabel("Ark Picit"))
        self.viewLayout.addWidget(BodyLabel("Pixel art painter for Arknights art mode"))

        self.viewLayout.addSpacing(16)

        # Quick-start
        self.viewLayout.addWidget(StrongBodyLabel("Quick Start"))

        btn_row = QHBoxLayout()
        self.btnNew = PrimaryPushButton(FIF.ADD, "New Painting")
        self.btnNew.clicked.connect(lambda: signalBus.newPainting.emit())
        btn_row.addWidget(self.btnNew)
        btn_row.addStretch()
        self.viewLayout.addLayout(btn_row)

        self.viewLayout.addStretch()
