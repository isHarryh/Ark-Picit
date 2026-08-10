"""Main application window built on qfluentwidgets FluentWindow."""

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow, NavigationItemPosition

from src.app.signal_bus import signalBus
from src.gui.pages.create_page import CreatePage
from src.gui.pages.explore_page import ExplorePage
from src.gui.pages.gallery_page import GalleryPage
from src.gui.pages.home_page import HomePage
from src.gui.pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    """Top-level window with left navigation and stacked pages."""

    def __init__(self):
        super().__init__()

        self._init_window()
        self._init_pages()
        self._init_navigation()
        self._connect_signals()

        # Startup meta round-trip (issues/echoes the client token)
        from src.app.plaza import plaza
        plaza.newAnnouncements.connect(self._show_new_announcements)
        plaza.warmup()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_window(self) -> None:
        self.setWindowTitle("Ark Picit")
        self.setMinimumSize(960, 640)
        self.resize(1280, 720)

        # Center on screen
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        self.setMicaEffectEnabled(False)

        self.navigationInterface.setExpandWidth(180)
        self.navigationInterface.expand(useAni=False)

    def _init_pages(self) -> None:
        self.homePage = HomePage(self)
        self.createPage = CreatePage(self)
        self.galleryPage = GalleryPage(self)
        self.explorePage = ExplorePage(self)
        self.settingsPage = SettingsPage(self)

    def _init_navigation(self) -> None:
        self.addSubInterface(self.homePage, FIF.HOME, self.tr("Home"))
        self.addSubInterface(self.createPage, FIF.EDIT, self.tr("Create"))
        self.addSubInterface(self.galleryPage, FIF.PHOTO, self.tr("Gallery"))
        self.addSubInterface(self.explorePage, FIF.GLOBE, self.tr("Explore"))
        self.addSubInterface(self.settingsPage, FIF.SETTING, self.tr("Settings"),
                             position=NavigationItemPosition.BOTTOM)

    def _connect_signals(self) -> None:
        signalBus.newPainting.connect(self._go_create)
        signalBus.editPainting.connect(self._go_create)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _go_create(self) -> None:
        """Switch to the create page."""
        self.switchTo(self.createPage)

    def _show_new_announcements(self) -> None:
        """Popup the announcement dialog when a new announcement set arrives."""
        from src.app.plaza import plaza
        from src.gui.pages.settings_page import AnnouncementDialog

        dialog = AnnouncementDialog(plaza.announcements(), self, hold_seconds=3)
        dialog.exec()
