"""Home page: welcome banner, quick-start and device control."""

from PySide6.QtWidgets import QHBoxLayout, QLabel
from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    PushSettingCard,
    SettingCard,
    SettingCardGroup,
    TitleLabel,
    setFont,
)
from qfluentwidgets import FluentIcon as FIF

from src.app.device_manager import deviceManager
from src.core.game_task import gameTask
from src.gui.components.base_page import BasePage
from src.gui.dialogs.device_dialog import browse_and_connect
from src.gui.dialogs.image_dialog import RegionVerifyDialog


class HomePage(BasePage):
    """Landing page with welcome, quick-start and device control."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._refresh_device_card()

    def _build_ui(self) -> None:
        self.viewLayout.addWidget(TitleLabel("Ark Picit"))
        self.viewLayout.addWidget(BodyLabel("Arknights Pixel Art Painter"))

        self.viewLayout.addSpacing(16)

        # Quick-start (title matches the SettingCardGroup headings below)
        quick_start_title = QLabel("Quick Start", self)
        setFont(quick_start_title, 20)
        self.viewLayout.addWidget(quick_start_title)

        btn_row = QHBoxLayout()
        self.btnNew = PrimaryPushButton(FIF.EDIT, "Go to Create")
        self.btnNew.clicked.connect(self._go_create)
        self.btnOpenGallery = PushButton(FIF.PHOTO, "Open My Gallery")
        self.btnOpenGallery.clicked.connect(self._open_gallery)
        btn_row.addWidget(self.btnNew)
        btn_row.addWidget(self.btnOpenGallery)
        btn_row.addStretch()
        self.viewLayout.addLayout(btn_row)

        self.viewLayout.addSpacing(16)

        # Controller and in-game paint task status
        self.deviceGroup = SettingCardGroup("Controller", self)

        self.browseCard = PushSettingCard(
            "Connect", FIF.SEARCH, "Controller", "Browse and connect a game window or adb device",
        )
        self.browseCard.button.setIcon(FIF.CONNECT.icon())
        self.deviceGroup.addSettingCard(self.browseCard)

        self.deviceCard = SettingCard(FIF.EMBED, "Current Controller", "No controller connected")
        self.deviceGroup.addSettingCard(self.deviceCard)

        self.taskCard = SettingCard(FIF.BRUSH, "Task Status", "Not started")
        self.deviceGroup.addSettingCard(self.taskCard)

        self.viewLayout.addWidget(self.deviceGroup)

        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.browseCard.clicked.connect(lambda: browse_and_connect(self.window()))
        deviceManager.deviceConnected.connect(self._on_device_connected)
        deviceManager.deviceConnectionFailed.connect(self._on_connect_failed)
        gameTask.statusChanged.connect(self._on_task_status)
        gameTask.succeeded.connect(self._on_task_succeeded)
        gameTask.drawingFinished.connect(self._on_drawing_finished)
        gameTask.failed.connect(self._on_task_failed)

    def _go_create(self) -> None:
        """Switch to the create page without resetting the current canvas."""
        window = self.window()
        window.switchTo(window.createPage)

    def _open_gallery(self) -> None:
        """Switch to the gallery page."""
        window = self.window()
        window.switchTo(window.galleryPage)

    # ------------------------------------------------------------------
    # Device status
    # ------------------------------------------------------------------

    def _on_device_connected(self, _device) -> None:
        self._refresh_device_card()

    def _on_connect_failed(self, _message: str) -> None:
        self._refresh_device_card()

    def _refresh_device_card(self) -> None:
        candidate = deviceManager.candidate
        if candidate is None:
            self.deviceCard.setContent("No controller connected")
        else:
            self.deviceCard.setContent(f"{candidate.kind.value} - {candidate.label}")

    # ------------------------------------------------------------------
    # Game paint task
    # ------------------------------------------------------------------

    def _on_task_status(self, message: str) -> None:
        """Update the task card with the current step."""
        self.taskCard.setContent(f"Running: {message}")

    def _on_task_succeeded(self, layout, image_path: str, diff_cells) -> None:
        """Ask the user to confirm the regions, then start drawing on accept.

        The detection flow brings the game window to the foreground, so the
        application window is raised here to keep the dialog visible.
        """
        self.taskCard.setContent(
            f"Success: canvas {layout.rows}x{layout.cols} recognized "
            f"({layout.canvas.w}x{layout.canvas.h} at {layout.canvas.x},{layout.canvas.y})"
        )
        window = self.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        dialog = RegionVerifyDialog(image_path, layout, diff_cells, parent=window)
        if dialog.exec():
            gameTask.start_drawing(incremental=dialog.incremental_enabled)
        else:
            gameTask.cancel()
            self.taskCard.setContent("Cancelled")

    def _on_drawing_finished(self, message: str) -> None:
        """Show the drawing completion state."""
        self.taskCard.setContent(f"Success: {message}")
        InfoBar.success("Drawing finished", message, parent=self.window(), duration=4000)

    def _on_task_failed(self, message: str) -> None:
        """Show the failure state and an error popup."""
        self.taskCard.setContent(f"Failed: {message}")
        InfoBar.error("Task failed", message, parent=self.window(), duration=6000)
