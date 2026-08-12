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
from src.app.i18n import fmt, localize_message
from src.auto import DeviceKind
from src.core.tasks import gameTask
from src.gui.dialogs.device_dialog import browse_and_connect
from src.gui.dialogs.image_dialog import RegionVerifyDialog
from src.gui.pages.base_page import BasePage


class HomePage(BasePage):
    """Landing page with welcome, quick-start and device control."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._refresh_device_card()

    def _build_ui(self) -> None:
        self.viewLayout.addWidget(TitleLabel("Ark Picit"))
        self.viewLayout.addWidget(BodyLabel(self.tr("AppTagline")))

        self.viewLayout.addSpacing(16)

        # Quick-start (title matches the SettingCardGroup headings below)
        quick_start_title = QLabel(self.tr("QuickStartTitle"), self)
        setFont(quick_start_title, 20)
        self.viewLayout.addWidget(quick_start_title)

        btn_row = QHBoxLayout()
        self.btnNew = PrimaryPushButton(FIF.EDIT, self.tr("GoToCreateButton"))
        self.btnNew.clicked.connect(self.switch_to_create)
        self.btnOpenGallery = PushButton(FIF.PHOTO, self.tr("OpenGalleryButton"))
        self.btnOpenGallery.clicked.connect(self.switch_to_gallery)
        btn_row.addWidget(self.btnNew)
        btn_row.addWidget(self.btnOpenGallery)
        btn_row.addStretch()
        self.viewLayout.addLayout(btn_row)

        self.viewLayout.addSpacing(16)

        # Controller and in-game paint task status
        self.deviceGroup = SettingCardGroup(self.tr("ControllerGroupTitle"), self)

        self.browseCard = PushSettingCard(
            self.tr("ConnectButton"), FIF.SEARCH, self.tr("ControllerGroupTitle"),
            self.tr("BrowseCardTip"),
        )
        self.browseCard.button.setIcon(FIF.CONNECT.icon())
        self.deviceGroup.addSettingCard(self.browseCard)

        self.deviceCard = SettingCard(
            FIF.EMBED, self.tr("CurrentControllerCardTitle"), self.tr("NoControllerConnectedTip")
        )
        self.deviceGroup.addSettingCard(self.deviceCard)

        self.taskCard = SettingCard(
            FIF.BRUSH, self.tr("TaskStatusCardTitle"), self.tr("NotStartedStatus")
        )
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

    # ------------------------------------------------------------------
    # Device status
    # ------------------------------------------------------------------

    def _on_device_connected(self, _device) -> None:
        self._refresh_device_card()

    def _on_connect_failed(self, _message) -> None:
        self._refresh_device_card()

    def _device_kind_label(self, kind: DeviceKind) -> str:
        """Return the localized display name of a device kind."""
        if kind is DeviceKind.WIN32:
            return self.tr("WindowsWindowKind")
        return self.tr("AdbDeviceKind")

    def _refresh_device_card(self) -> None:
        candidate = deviceManager.candidate
        if candidate is None:
            self.deviceCard.setContent(self.tr("NoControllerConnectedTip"))
        else:
            label = self._device_kind_label(candidate.kind)
            self.deviceCard.setContent(f"{label} - {candidate.label}")

    # ------------------------------------------------------------------
    # Game paint task
    # ------------------------------------------------------------------

    def _on_task_status(self, message) -> None:
        """Update the task card with the current step."""
        self.taskCard.setContent(
            fmt(self.tr("RunningStatusFormat"), localize_message(message))
        )

    def _on_task_succeeded(self, layout, image_path: str, diff_cells) -> None:
        """Ask the user to confirm the regions, then start drawing on accept.

        The detection flow brings the game window to the foreground, so the
        application window is raised here to keep the dialog visible.
        """
        self.taskCard.setContent(
            fmt(
                self.tr("CanvasRecognizedStatusFormat"),
                layout.rows,
                layout.cols,
                layout.canvas.w,
                layout.canvas.h,
                layout.canvas.x,
                layout.canvas.y,
            )
        )
        window = self.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        dialog = RegionVerifyDialog(image_path, layout, diff_cells, parent=window)
        if dialog.exec():
            gameTask.start_drawing(
                incremental=dialog.incremental_enabled,
                click_delay_ms=dialog.click_delay_ms,
            )
        else:
            gameTask.cancel()
            self.taskCard.setContent(self.tr("CancelledStatus"))

    def _on_drawing_finished(self, message) -> None:
        """Show the drawing completion state."""
        text = localize_message(message)
        self.taskCard.setContent(fmt(self.tr("SuccessStatusFormat"), text))
        InfoBar.success(self.tr("DrawingFinishedTitle"), text, parent=self.window(), duration=4000)

    def _on_task_failed(self, message) -> None:
        """Show the failure state and an error popup."""
        text = localize_message(message)
        self.taskCard.setContent(fmt(self.tr("FailedStatusFormat"), text))
        InfoBar.error(self.tr("TaskFailedTitle"), text, parent=self.window(), duration=6000)
