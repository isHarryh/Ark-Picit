"""Base class for all application pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea


class BasePage(ScrollArea):
    """Scrollable page with a vertical container.

    Subclasses populate ``self.viewLayout`` with widgets.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(type(self).__name__)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self.viewLayout = QVBoxLayout(self._container)
        self.viewLayout.setContentsMargins(36, 20, 36, 20)
        self.viewLayout.setSpacing(8)

        self.setWidget(self._container)

        # Keep the page background transparent. QScrollArea.setWidget() enables autoFillBackground
        # and the viewport is flagged WA_StyledBackground, both of which would paint palette().window()
        # a dark native color when the OS is in dark mode, regardless of the app theme.
        self._container.setAutoFillBackground(False)
        self.enableTransparentBackground()
