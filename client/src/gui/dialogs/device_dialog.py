"""Dialog for browsing and selecting a device to connect.

The dialog opens immediately with a loading state; discovered candidates
populate it asynchronously. ADB devices are listed in an "ADB Devices"
group at the top, followed by the "Recommended Windows" group (windows
whose title suggests the game). Empty groups show an empty-state hint
instead of being removed.
"""

from PySide6.QtCore import QCoreApplication, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressRing,
    InfoBar,
    MessageBoxBase,
    SubtitleLabel,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from src.app.device_manager import DeviceCandidate, deviceManager
from src.app.i18n import fmt
from src.auto import DeviceKind
from src.utils.win_admin import is_admin, relaunch_as_admin

_browsing = False


def _smartphone_icon() -> QIcon:
    """Return a theme-aware smartphone icon drawn with QPainter."""
    color = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(9.5, 3.5, 13, 25), 3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(12.5, 7.5, 7, 16), 1.5, 1.5)
    painter.end()
    return QIcon(pixmap)


class DeviceDialog(MessageBoxBase):
    """List discovered devices; the selected candidate is returned on accept.

    Args:
        candidates: Discovered device candidates to display, or None to show
            a loading state until :meth:`set_candidates` is called.
        parent: Parent widget.
    """

    def __init__(self, candidates: list[DeviceCandidate] | None = None, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(460)
        self.viewLayout.setSpacing(12)
        self.viewLayout.addWidget(SubtitleLabel(self.tr("SelectControllerTitle")))

        # List and loading state share the same area, so switching between
        # them does not reflow the dialog layout.
        self._stack = QStackedWidget(self)
        self.listWidget = QListWidget(self)
        self.listWidget.setMinimumHeight(260)
        self.listWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stack.addWidget(self.listWidget)

        self._progress = IndeterminateProgressRing(self, start=False)
        self._progress.setFixedSize(32, 32)
        self._loadingTitle = BodyLabel(self.tr("SearchingDevicesTitle"), self)
        self._loadingTitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint = CaptionLabel(self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.hide()
        self._loadingPage = QWidget(self)
        self._loadingPage.setMinimumHeight(260)
        loading_vbox = QVBoxLayout(self._loadingPage)
        loading_vbox.addStretch(1)
        loading_vbox.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignHCenter)
        loading_vbox.addSpacing(12)
        loading_vbox.addWidget(self._loadingTitle)
        loading_vbox.addWidget(self._hint)
        loading_vbox.addStretch(1)
        self._stack.addWidget(self._loadingPage)

        self.viewLayout.addWidget(self._stack)

        self.yesButton.setText(self.tr("ConnectButton"))
        self.cancelButton.setText(self.tr("CancelButton"))
        self.listWidget.itemDoubleClicked.connect(lambda _item: self.accept())
        self.listWidget.currentItemChanged.connect(self._on_current_changed)

        if candidates is None:
            self.yesButton.setEnabled(False)
            self._stack.setCurrentWidget(self._loadingPage)
            self._progress.start()
        else:
            self.set_candidates(candidates)

    def set_candidates(self, candidates: list[DeviceCandidate]) -> None:
        """Populate the list with discovered candidates, replacing the loading state."""
        self._stack.setCurrentWidget(self.listWidget)
        self._progress.stop()
        self._populate(candidates)

    def set_error(self, message: str) -> None:
        """Replace the loading state with a discovery error message."""
        self._progress.stop()
        self._progress.hide()
        self._loadingTitle.setText(self.tr("SearchFailedTitle"))
        self._hint.setText(message)
        self._hint.show()

    def validate(self) -> bool:
        """Only accept the dialog when a device candidate is selected."""
        return self.selected_candidate is not None

    def _populate(self, candidates: list[DeviceCandidate]) -> None:
        adbs = [c for c in candidates if c.kind is DeviceKind.ADB]
        win32s = sorted(
            (c for c in candidates if c.kind is DeviceKind.WIN32),
            key=lambda c: c.score,
            reverse=True,
        )
        recommended = [c for c in win32s if c.score >= 2]

        priority_row: int | None = None

        before_adb = self.listWidget.count()
        self._add_group(
            self.tr("AdbDevicesGroup"), adbs,
            self.tr("NoAdbDevicesEmpty"),
        )
        priority_row = self._first_candidate_row(before_adb)

        before_recommended = self.listWidget.count()
        self._add_group(
            self.tr("RecommendedWindowsGroup"), recommended,
            self.tr("NoGameWindowEmpty"),
        )
        if priority_row is None:
            priority_row = self._first_candidate_row(before_recommended)

        if priority_row is not None:
            self.listWidget.setCurrentRow(priority_row)
        else:
            self.yesButton.setEnabled(False)

    def _first_candidate_row(self, start: int) -> int | None:
        for row in range(start, self.listWidget.count()):
            if self.listWidget.item(row).data(Qt.ItemDataRole.UserRole) is not None:
                return row
        return None

    def _on_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        has_candidate = (
            current is not None
            and current.data(Qt.ItemDataRole.UserRole) is not None
        )
        self.yesButton.setEnabled(has_candidate)

    def _add_group(
        self,
        title: str,
        candidates: list[DeviceCandidate],
        empty_text: str,
    ) -> None:
        self._add_group_header(title)
        if not candidates:
            item = QListWidgetItem(empty_text)
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            gray = QColor(150, 150, 150) if isDarkTheme() else QColor(120, 120, 120)
            item.setForeground(QBrush(gray))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.listWidget.addItem(item)
            return
        for candidate in candidates:
            self._add_candidate(candidate)

    def _add_group_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        font = item.font()
        font.setWeight(QFont.Weight.DemiBold)
        font.setPointSize(font.pointSize() + 1)
        item.setFont(font)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.listWidget.addItem(item)

    def _add_candidate(self, candidate: DeviceCandidate) -> None:
        icon = _smartphone_icon() if candidate.kind is DeviceKind.ADB else FIF.APPLICATION.icon()
        label = candidate.label
        if candidate.kind is DeviceKind.WIN32 and len(label) > 32:
            label = f"{label[:32]}..."
        item = QListWidgetItem(icon, label)
        item.setData(Qt.ItemDataRole.UserRole, candidate)
        self.listWidget.addItem(item)

    @property
    def selected_candidate(self) -> DeviceCandidate | None:
        """Return the candidate of the currently selected list item, or None."""
        item = self.listWidget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)


class AdminRequiredDialog(MessageBoxBase):
    """Warn that the Windows controller requires administrator privileges.

    Offers to relaunch the application elevated (UAC) or cancel; the
    connection is aborted in either case.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(440)
        self.viewLayout.setSpacing(12)
        self.viewLayout.addWidget(SubtitleLabel(self.tr("AdminRequiredTitle")))
        self.viewLayout.addWidget(BodyLabel(self.tr("AdminRequiredTip")))
        self.yesButton.setText(self.tr("RestartAsAdminButton"))
        self.cancelButton.setText(self.tr("CancelButton"))


def browse_and_connect(parent: QWidget, on_connected=None) -> None:
    """Open the browse dialog immediately and populate it as discovery finishes.

    The dialog starts in a loading state; discovered candidates are shown
    as soon as the (slow) window/adb scan completes. Notifications
    (connection result or failure) are shown as InfoBars on *parent*.
    *on_connected* is invoked with the connected device after a successful
    connection. Connecting a Windows window requires administrator
    privileges: without them a warning dialog offers to relaunch the
    application elevated (UAC) or cancel.
    """
    global _browsing
    if _browsing:
        return
    _browsing = True

    dialog = DeviceDialog(candidates=None, parent=parent)

    def _cleanup() -> None:
        global _browsing
        _browsing = False
        deviceManager.discoveryFinished.disconnect(_on_discovered)
        deviceManager.discoveryFailed.disconnect(_on_discovery_failed)
        deviceManager.deviceConnected.disconnect(_on_connected)
        deviceManager.deviceConnectionFailed.disconnect(_on_failed)

    def _on_discovered(candidates: list[DeviceCandidate]) -> None:
        if dialog.isHidden():
            _cleanup()
            return
        dialog.set_candidates(candidates)

    def _on_discovery_failed(message: str) -> None:
        if dialog.isHidden():
            _cleanup()
            return
        dialog.set_error(message)

    def _on_connected(device) -> None:
        _cleanup()
        candidate = deviceManager.candidate
        label = candidate.label if candidate else QCoreApplication.translate(
            "DeviceDialog", "ControllerWord"
        )
        InfoBar.success(
            QCoreApplication.translate("DeviceDialog", "ConnectedTitle"),
            fmt(QCoreApplication.translate("DeviceDialog", "ConnectedTip"), label),
            parent=parent,
            duration=3000,
        )
        if on_connected is not None:
            on_connected(device)

    def _on_failed(message: str) -> None:
        _cleanup()
        if "unauthorized" in message:
            message = (
                f"{message}. "
                + QCoreApplication.translate("DeviceDialog", "AdbUnauthorizedTip")
            )
        InfoBar.error(
            QCoreApplication.translate("DeviceDialog", "ConnectionFailedTitle"),
            message, parent=parent, duration=6000,
        )

    deviceManager.discoveryFinished.connect(_on_discovered)
    deviceManager.discoveryFailed.connect(_on_discovery_failed)
    deviceManager.deviceConnected.connect(_on_connected)
    deviceManager.deviceConnectionFailed.connect(_on_failed)
    deviceManager.discover()

    accepted = dialog.exec()
    candidate = dialog.selected_candidate if accepted else None
    if candidate is None:
        _cleanup()
        return
    if candidate.kind is DeviceKind.WIN32 and not is_admin():
        _cleanup()
        warning = AdminRequiredDialog(parent=parent)
        if warning.exec() and relaunch_as_admin():
            instance = QCoreApplication.instance()
            if instance is not None:
                instance.quit()
        return
    deviceManager.connect(candidate)
