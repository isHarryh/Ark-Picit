"""Base class for all application pages."""

from typing import Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea


class _AppWindow(Protocol):
    """Subset of MainWindow used by pages for safe navigation."""

    homePage: QWidget
    createPage: QWidget
    galleryPage: QWidget
    explorePage: QWidget
    settingsPage: QWidget

    def switchTo(self, interface: QWidget) -> None: ...


class BasePage(ScrollArea):
    """Scrollable page with a vertical container.

    Subclasses populate ``self.viewLayout`` with widgets and call
    ``switch_to_*`` helpers to navigate without casting the main window.
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

    def _app_window(self) -> _AppWindow:
        return cast(_AppWindow, self.window())

    def switch_to_home(self) -> None:
        window = self._app_window()
        window.switchTo(window.homePage)

    def switch_to_create(self) -> None:
        window = self._app_window()
        window.switchTo(window.createPage)

    def switch_to_gallery(self) -> None:
        window = self._app_window()
        window.switchTo(window.galleryPage)

    def switch_to_explore(self) -> None:
        window = self._app_window()
        window.switchTo(window.explorePage)

    def switch_to_settings(self) -> None:
        window = self._app_window()
        window.switchTo(window.settingsPage)
