"""Dialog for browsing and selecting a device to connect.

Windows whose titles mention the game are listed in a "Recommended Windows"
group at the top, followed by "Other Windows" and "ADB Devices".
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidgetItem, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, ListWidget, MessageBoxBase, SubtitleLabel

from src.app.device_manager import DeviceCandidate, deviceManager
from src.auto import DeviceKind

_browsing = False

RECOMMENDED_KEYWORDS = ("明日方舟", "arknights")


def _is_recommended(candidate: DeviceCandidate) -> bool:
    """Return whether a window candidate should be in the recommended group."""
    if candidate.kind is not DeviceKind.WIN32:
        return False
    lowered = candidate.label.lower()
    return any(keyword in lowered for keyword in RECOMMENDED_KEYWORDS)


class DeviceDialog(MessageBoxBase):
    """List discovered devices; the selected candidate is returned on accept.

    Args:
        candidates: Discovered device candidates to display.
        parent: Parent widget.
    """

    def __init__(self, candidates: list[DeviceCandidate], parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(460)
        self.viewLayout.setSpacing(12)
        self.viewLayout.addWidget(SubtitleLabel("Select a device to connect"))

        self.listWidget = ListWidget(self)
        self.listWidget.setMinimumHeight(260)
        self._populate(candidates)
        self.viewLayout.addWidget(self.listWidget)

        self.yesButton.setText("Connect")
        self.cancelButton.setText("Cancel")
        self.listWidget.itemDoubleClicked.connect(lambda _item: self.accept())

    def _populate(self, candidates: list[DeviceCandidate]) -> None:
        windows = [c for c in candidates if c.kind is DeviceKind.WIN32]
        adbs = [c for c in candidates if c.kind is DeviceKind.ADB]
        recommended = [c for c in windows if _is_recommended(c)]
        others = [c for c in windows if not _is_recommended(c)]

        if recommended:
            self._add_group_header("Recommended Windows")
            for candidate in recommended:
                self._add_candidate(candidate)
        if others:
            self._add_group_header("Other Windows")
            for candidate in others:
                self._add_candidate(candidate)
        if adbs:
            self._add_group_header("ADB Devices")
            for candidate in adbs:
                self._add_candidate(candidate)

        for row in range(self.listWidget.count()):
            item = self.listWidget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                self.listWidget.setCurrentRow(row)
                break

    def _add_group_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        font = item.font()
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.listWidget.addItem(item)

    def _add_candidate(self, candidate: DeviceCandidate) -> None:
        icon = FIF.PHONE if candidate.kind is DeviceKind.ADB else FIF.EMBED
        item = QListWidgetItem(icon.icon(), candidate.label)
        item.setData(Qt.ItemDataRole.UserRole, candidate)
        self.listWidget.addItem(item)

    @property
    def selected_candidate(self) -> DeviceCandidate | None:
        """Return the candidate of the currently selected list item, or None."""
        item = self.listWidget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)


def browse_and_connect(parent: QWidget, on_connected=None) -> None:
    """Discover devices, show the browse dialog, and connect the selection.

    A fresh discovery runs every time this is invoked, so no separate
    refresh control is needed. Notifications (nothing found / connection
    result) are shown as InfoBars on *parent*. *on_connected* is invoked
    with the connected device after a successful connection.
    """
    global _browsing
    if _browsing:
        return
    _browsing = True

    def _cleanup() -> None:
        global _browsing
        _browsing = False
        deviceManager.discoveryFinished.disconnect(_on_discovered)
        deviceManager.deviceConnected.disconnect(_on_connected)
        deviceManager.deviceConnectionFailed.disconnect(_on_failed)

    def _on_discovered(candidates: list[DeviceCandidate]) -> None:
        if not candidates:
            _cleanup()
            InfoBar.warning(
                "No devices found",
                "No windows or adb devices are available. Start the game or an emulator, then try again.",
                parent=parent,
                duration=5000,
            )
            return
        dialog = DeviceDialog(candidates, parent)
        candidate = dialog.selected_candidate if dialog.exec() else None
        if candidate is None:
            _cleanup()
            return
        deviceManager.connect(candidate)

    def _on_connected(device) -> None:
        _cleanup()
        candidate = deviceManager.candidate
        InfoBar.success(
            "Device connected",
            f"Connected to {candidate.label if candidate else 'device'}",
            parent=parent,
            duration=3000,
        )
        if on_connected is not None:
            on_connected(device)

    def _on_failed(message: str) -> None:
        _cleanup()
        InfoBar.error("Connection failed", message, parent=parent, duration=5000)

    deviceManager.discoveryFinished.connect(_on_discovered)
    deviceManager.deviceConnected.connect(_on_connected)
    deviceManager.deviceConnectionFailed.connect(_on_failed)
    deviceManager.discover()
