"""Settings page: theme and advanced API settings."""

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ExpandGroupSettingCard,
    InfoBar,
    LineEdit,
    OptionsSettingCard,
    PasswordLineEdit,
    PushButton,
    SettingCard,
    SettingCardGroup,
    SubtitleLabel,
    SwitchButton,
    Theme,
    ToolButton,
    qconfig,
    setTheme,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.config import cfg
from src.app.network import HttpResult
from src.app.plaza import NetworkDisabledReason, plaza
from src.gui.components.base_page import BasePage

_REPOSITORY_URL = "https://github.com/isHarryh/Ark-Picit"
_ISSUE_URL = f"{_REPOSITORY_URL}/issues/new"


class _AnnouncementCard(SettingCard):
    """Opens the announcement viewer or admin manager."""

    def __init__(self, parent=None):
        super().__init__(FIF.MEGAPHONE, "Announcements", None, parent)
        self.viewBtn = PushButton(FIF.INFO, "View")
        self.hBoxLayout.addWidget(self.viewBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.viewBtn.clicked.connect(self._show)
        plaza.adminChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.viewBtn.setText("Manage" if plaza.is_admin else "View")

    def _show(self) -> None:
        dialog = (
            AnnouncementManagerDialog(plaza.announcements(), self.window())
            if plaza.is_admin
            else AnnouncementDialog(plaza.announcements(), self.window())
        )
        dialog.exec()


class _AboutCard(SettingCard):
    """Opens the project repository and new-issue page."""

    def __init__(self, parent=None):
        super().__init__(FIF.INFO, "About", None, parent)
        githubBtn = PushButton("GitHub")
        issueBtn = PushButton("Submit Issue")
        githubBtn.clicked.connect(
            lambda _checked=False: QDesktopServices.openUrl(QUrl(_REPOSITORY_URL))
        )
        issueBtn.clicked.connect(
            lambda _checked=False: QDesktopServices.openUrl(QUrl(_ISSUE_URL))
        )
        self.hBoxLayout.addWidget(githubBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(issueBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class _NetworkCard(SettingCard):
    """Toggles network communication; locked when the API version mismatches."""

    def __init__(self, parent=None):
        super().__init__(FIF.GLOBE, "Disable network", None, parent)
        self.switchBtn = SwitchButton(self)
        self.hBoxLayout.addWidget(self.switchBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.switchBtn.checkedChanged.connect(self._on_toggled)
        plaza.networkDisabledChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        locked = plaza.disabled_reason() == NetworkDisabledReason.VERSION_MISMATCH
        self.switchBtn.setEnabled(not locked)
        self.switchBtn.setChecked(not plaza.is_network_enabled())

    def _on_toggled(self, checked: bool) -> None:
        plaza.set_network_enabled(not checked)


class AnnouncementDialog(QDialog):
    """Shows the server announcements, one item per row.

    With a positive ``hold_seconds`` the close button stays disabled (and ESC /
    the window close button are ignored) until that many seconds have elapsed,
    so new announcements cannot be dismissed instantly.
    """

    def __init__(self, announcements: list, parent=None, hold_seconds: int = 0):
        super().__init__(parent)
        self._hold_remaining = max(0, hold_seconds)
        self.setWindowTitle("Announcements")
        self.resize(480, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addWidget(SubtitleLabel("Announcements"))

        if announcements:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            content = QWidget()
            column = QVBoxLayout(content)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(8)
            for index, item in enumerate(announcements, 1):
                text = (
                    str(item.get("title") or item.get("content") or item)
                    if isinstance(item, dict)
                    else str(item)
                )
                column.addWidget(BodyLabel(f"{index}. {text}"))
            column.addStretch()
            scroll.setWidget(content)
            root.addWidget(scroll, 1)
        else:
            root.addWidget(CaptionLabel("No announcements at this time."))
            root.addStretch()

        closeBtn = PushButton(FIF.CLOSE, "Close")
        closeBtn.clicked.connect(self.accept)
        if self._hold_remaining:
            self._closeBtn = closeBtn
            self._update_close_btn()
            self._holdTimer = QTimer(self)
            self._holdTimer.setInterval(1000)
            self._holdTimer.timeout.connect(self._on_hold_tick)
            self._holdTimer.start()
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(closeBtn)
        root.addLayout(buttons)

    def _on_hold_tick(self) -> None:
        self._hold_remaining -= 1
        self._update_close_btn()
        if self._hold_remaining <= 0:
            self._holdTimer.stop()

    def _update_close_btn(self) -> None:
        if self._hold_remaining > 0:
            self._closeBtn.setEnabled(False)
            self._closeBtn.setText(f"Close ({self._hold_remaining}s)")
        else:
            self._closeBtn.setEnabled(True)
            self._closeBtn.setText("Close")

    def reject(self) -> None:
        if self._hold_remaining > 0:
            return
        super().reject()


class AnnouncementManagerDialog(QDialog):
    """Edits and publishes the complete server announcement list."""

    def __init__(self, announcements: list, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[QWidget, LineEdit]] = []
        self.setWindowTitle("Manage Announcements")
        self.resize(560, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addWidget(SubtitleLabel("Manage Announcements"))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._entriesLayout = QVBoxLayout(content)
        self._entriesLayout.setContentsMargins(0, 0, 0, 0)
        self._entriesLayout.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        for item in announcements:
            self._add_entry(
                str(item.get("title") or item.get("content") or item)
                if isinstance(item, dict)
                else str(item)
            )

        addBtn = PushButton(FIF.ADD, "Add announcement")
        addBtn.clicked.connect(lambda _checked=False: self._add_entry())
        root.addWidget(addBtn, 0, Qt.AlignmentFlag.AlignLeft)

        self.saveBtn = PushButton(FIF.SAVE, "Save")
        cancelBtn = PushButton(FIF.CLOSE, "Cancel")
        self.saveBtn.clicked.connect(self._save)
        cancelBtn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancelBtn)
        buttons.addWidget(self.saveBtn)
        root.addLayout(buttons)

    def _add_entry(self, text: str = "") -> None:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        edit = LineEdit(row)
        edit.setText(text)
        edit.setPlaceholderText("Announcement text")
        removeBtn = ToolButton(FIF.DELETE, row)
        removeBtn.setToolTip("Delete")
        removeBtn.clicked.connect(lambda: self._remove_entry(row))

        layout.addWidget(edit, 1)
        layout.addWidget(removeBtn)
        self._rows.append((row, edit))
        self._entriesLayout.addWidget(row)
        edit.setFocus()

    def _remove_entry(self, row: QWidget) -> None:
        self._rows = [(widget, edit) for widget, edit in self._rows if widget is not row]
        self._entriesLayout.removeWidget(row)
        row.deleteLater()

    def _save(self) -> None:
        announcements = [edit.text().strip() for _, edit in self._rows]
        if any(not text for text in announcements):
            InfoBar.warning(
                "Announcements",
                "Announcement text cannot be empty.",
                parent=self,
            )
            return

        self.saveBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.saveBtn.setEnabled(True)
            if not result.ok:
                InfoBar.error("Save failed", result.detail(), parent=self)
                return
            InfoBar.success(
                "Announcements updated",
                "The announcement list was published.",
                parent=self.parentWidget(),
            )
            self.accept()

        plaza.publish_announcements(announcements, on_done)


class _ServerUrlCard(SettingCard):
    """Edits the API server base URL."""

    def __init__(self, parent=None):
        super().__init__(FIF.LINK, "API base URL", None, parent)
        self.urlEdit = LineEdit(self)
        self.urlEdit.setText(str(qconfig.get(cfg().exploreServerUrl)))
        self.urlEdit.setClearButtonEnabled(True)
        self.urlEdit.setFixedWidth(260)
        self.hBoxLayout.addWidget(self.urlEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.urlEdit.editingFinished.connect(self._apply)

    def _apply(self) -> None:
        plaza.set_server_url(self.urlEdit.text().strip())


class _TokenCard(SettingCard):
    """Verifies the mystery code; unlocks the Admin explore view on success."""

    def __init__(self, parent=None):
        super().__init__(FIF.CERTIFICATE, "Mystery code", None, parent)
        self.tokenEdit = PasswordLineEdit(self)
        self.tokenEdit.setPlaceholderText("Enter the code")
        self.tokenEdit.setFixedWidth(200)
        self.verifyBtn = ToolButton(FIF.ACCEPT, self)
        self.verifyBtn.setToolTip("Verify")
        self.hBoxLayout.addWidget(self.tokenEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.verifyBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.verifyBtn.clicked.connect(self._verify)

    def _verify(self) -> None:
        token = self.tokenEdit.text().strip()
        if not token:
            InfoBar.warning("Mystery Code", "Please enter a code first.", parent=self.window())
            return
        self.verifyBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.verifyBtn.setEnabled(True)
            if not result.ok:
                InfoBar.error("Verification failed", result.detail(), parent=self.window())
                return
            if plaza.is_admin:
                qconfig.set(cfg().exploreToken, token)
                InfoBar.success("Verified", "The code was accepted.", parent=self.window())
            else:
                InfoBar.warning("Verification failed", "That code was not accepted.", parent=self.window())

        plaza.verify_token(token, on_done)


class SettingsPage(BasePage):
    """Application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        # --- Announcements (above appearance) ---
        self.announcementCard = _AnnouncementCard(self)
        self.viewLayout.addWidget(self.announcementCard)

        self.aboutCard = _AboutCard(self)
        self.viewLayout.addWidget(self.aboutCard)

        # --- Appearance ---
        self.appearanceGroup = SettingCardGroup("Appearance", self)

        self.themeCard = OptionsSettingCard(
            cfg().themeMode,
            FIF.BRUSH,
            "Theme",
            None,
            texts=["Light", "Dark", "Use system setting"],
        )

        self.appearanceGroup.addSettingCard(self.themeCard)
        # Keep the group at its content height so the section below
        # stays adjacent (the group's internal stretch would otherwise
        # absorb all free layout space).
        self.appearanceGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.viewLayout.addWidget(self.appearanceGroup)

        # --- Advanced heading ---
        self.advancedGroup = SettingCardGroup("Advanced", self)
        self.advancedGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.viewLayout.addWidget(self.advancedGroup)

        # --- Network (collapsed by default) ---
        self.apiGroup = ExpandGroupSettingCard(FIF.WIFI, "Network", None, self)
        self.networkCard = _NetworkCard(self)
        self.serverCard = _ServerUrlCard(self)
        self.tokenCard = _TokenCard(self)
        self.apiGroup.addGroupWidget(self.networkCard)
        self.apiGroup.addGroupWidget(self.serverCard)
        self.apiGroup.addGroupWidget(self.tokenCard)
        self.apiGroup.setExpand(False)
        self.viewLayout.addWidget(self.apiGroup)

        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.themeCard.optionChanged.connect(self._apply_theme)

    def _apply_theme(self, _key) -> None:
        theme_value = qconfig.get(cfg().themeMode)
        if theme_value == Theme.LIGHT:
            setTheme(Theme.LIGHT)
        elif theme_value == Theme.DARK:
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)
