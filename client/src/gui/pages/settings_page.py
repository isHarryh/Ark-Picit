"""Settings page: theme and advanced API settings."""

import re

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
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
    ToolButton,
    qconfig,
    setTheme,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.config import cfg
from src.app.dist import app_version
from src.app.i18n import fmt, localize_http_error
from src.app.network import HttpResult
from src.app.plaza import NetworkDisabledReason, plaza
from src.gui.pages.base_page import BasePage

_REPOSITORY_URL = "https://github.com/isHarryh/Ark-Picit"
_ISSUE_URL = f"{_REPOSITORY_URL}/issues/new"

_ACCENT_COLOR = "#0078D7"
_URL_RE = re.compile(r"https?://[^\s]+")


class _AnnouncementCard(SettingCard):
    """Opens the announcement viewer or admin manager."""

    def __init__(self, parent=None):
        super().__init__(FIF.MEGAPHONE, self.tr("AnnouncementsTitle"), None, parent)
        self.viewBtn = PushButton(FIF.INFO, self.tr("ViewButton"))
        self.hBoxLayout.addWidget(self.viewBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.viewBtn.clicked.connect(self._show)
        plaza.adminChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.viewBtn.setText(self.tr("ManageButton") if plaza.is_admin else self.tr("ViewButton"))

    def _show(self) -> None:
        dialog = (
            AnnouncementManagerDialog(plaza.announcements(), self.window())
            if plaza.is_admin
            else AnnouncementDialog(plaza.announcements(), self.window())
        )
        dialog.exec()


class _AboutCard(SettingCard):
    """Shows the app version and opens the project repository / issue page."""

    def __init__(self, parent=None):
        super().__init__(FIF.INFO, self.tr("AboutTitle"), f"v{app_version()}", parent)
        githubBtn = PushButton("GitHub")
        issueBtn = PushButton(self.tr("SubmitIssueButton"))
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


class _ExpandItemCard(SettingCard):
    """SettingCard without its own background, for use inside an expand panel."""

    def paintEvent(self, e) -> None:
        pass


class _NetworkCard(_ExpandItemCard):
    """Toggles network communication; locked when the API version mismatches."""

    def __init__(self, parent=None):
        super().__init__(FIF.GLOBE, self.tr("DisableNetworkTitle"), None, parent)
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


def _announce_text(item) -> str:
    """Normalize an announcement payload item to its display text."""
    if isinstance(item, dict):
        return str(item.get("title") or item.get("content") or item)
    return str(item)


def _linkify(text: str) -> str:
    """Escape HTML and wrap bare http(s) URLs in anchor tags for QLabel rich text."""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return _URL_RE.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)


class _AnnouncementItemCard(QFrame):
    """A single announcement row: accent color bar + auto-wrapping rich text."""

    def __init__(self, index: int, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("announcementCard")
        self.setStyleSheet(
            "#announcementCard { background: rgba(0, 0, 0, 0.03); border-radius: 6px; }"
            "QWidget { background: transparent; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left accent color bar
        bar = QFrame(self)
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background: {_ACCENT_COLOR}; border-top-left-radius: 6px; border-bottom-left-radius: 6px;")
        layout.addWidget(bar)

        # Right text area: "N. <rich text with auto links>"
        label = QLabel(self)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setText(f"<b>{index}.</b> {_linkify(text)}")
        label.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(label, 1)


class AnnouncementDialog(QDialog):
    """Shows the server announcements as cards in a scrollable area.

    With a positive ``hold_seconds`` the close button stays disabled (and ESC /
    the window close button are ignored) until that many seconds have elapsed,
    so new announcements cannot be dismissed instantly.
    """

    def __init__(self, announcements: list, parent=None, hold_seconds: int = 0):
        super().__init__(parent)
        self._hold_remaining = max(0, hold_seconds)
        self.setWindowTitle(self.tr("AnnouncementsTitle"))
        self.resize(480, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addWidget(SubtitleLabel(self.tr("AnnouncementsTitle")))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        items = [_announce_text(item) for item in announcements]
        if items:
            for index, text in enumerate(items, 1):
                column.addWidget(_AnnouncementItemCard(index, text, self))
        else:
            column.addWidget(CaptionLabel(self.tr("NoAnnouncementsTip")))
        column.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self._closeBtn = PushButton(FIF.CLOSE, self.tr("CloseButton"))
        self._closeBtn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._closeBtn)
        root.addLayout(buttons)

        if self._hold_remaining:
            self._update_close_btn()
            self._holdTimer = QTimer(self)
            self._holdTimer.setInterval(1000)
            self._holdTimer.timeout.connect(self._on_hold_tick)
            self._holdTimer.start()

    def _on_hold_tick(self) -> None:
        self._hold_remaining -= 1
        self._update_close_btn()
        if self._hold_remaining <= 0:
            self._holdTimer.stop()

    def _update_close_btn(self) -> None:
        if self._hold_remaining > 0:
            self._closeBtn.setEnabled(False)
            self._closeBtn.setText(
                fmt(self.tr("CloseCountdownButton"), self._hold_remaining)
            )
        else:
            self._closeBtn.setEnabled(True)
            self._closeBtn.setText(self.tr("CloseButton"))

    def reject(self) -> None:
        if self._hold_remaining > 0:
            return
        super().reject()


class AnnouncementManagerDialog(QDialog):
    """Edits and publishes the complete server announcement list."""

    def __init__(self, announcements: list, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[QWidget, LineEdit]] = []
        self.setWindowTitle(self.tr("ManageAnnouncementsTitle"))
        self.resize(560, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addWidget(SubtitleLabel(self.tr("ManageAnnouncementsTitle")))

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

        addBtn = PushButton(FIF.ADD, self.tr("AddAnnouncementButton"))
        addBtn.clicked.connect(lambda _checked=False: self._add_entry())
        root.addWidget(addBtn, 0, Qt.AlignmentFlag.AlignLeft)

        self.saveBtn = PushButton(FIF.SAVE, self.tr("SaveButton"))
        cancelBtn = PushButton(FIF.CLOSE, self.tr("CancelButton"))
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
        edit.setPlaceholderText(self.tr("AnnouncementTextPlaceholder"))
        removeBtn = ToolButton(FIF.DELETE, row)
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
                self.tr("AnnouncementsTitle"),
                self.tr("EmptyAnnouncementTip"),
                parent=self,
            )
            return

        self.saveBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.saveBtn.setEnabled(True)
            if not result.ok:
                InfoBar.error(self.tr("SaveFailedTitle"), localize_http_error(result), parent=self)
                return
            InfoBar.success(
                self.tr("AnnouncementsUpdatedTitle"),
                self.tr("AnnouncementsPublishedTip"),
                parent=self.parentWidget(),
            )
            self.accept()

        plaza.publish_announcements(announcements, on_done)


class _ServerUrlCard(_ExpandItemCard):
    """Edits the API server base URL."""

    def __init__(self, parent=None):
        super().__init__(FIF.LINK, self.tr("ServerUrlTitle"), None, parent)
        self.urlEdit = LineEdit(self)
        self.urlEdit.setText(str(qconfig.get(cfg().exploreServerUrl)))
        self.urlEdit.setClearButtonEnabled(True)
        self.urlEdit.setFixedWidth(260)
        self.hBoxLayout.addWidget(self.urlEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.urlEdit.editingFinished.connect(self._apply)

    def _apply(self) -> None:
        plaza.set_server_url(self.urlEdit.text().strip())


class _TokenCard(_ExpandItemCard):
    """Verifies the mystery code; unlocks the Admin explore view on success."""

    def __init__(self, parent=None):
        super().__init__(FIF.CERTIFICATE, self.tr("MysteryCodeTitle"), None, parent)
        self.tokenEdit = PasswordLineEdit(self)
        self.tokenEdit.setFixedWidth(260)
        self.hBoxLayout.addWidget(self.tokenEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.tokenEdit.editingFinished.connect(self._verify)

    def _verify(self) -> None:
        token = self.tokenEdit.text().strip()
        if not token:
            InfoBar.warning(
                self.tr("MysteryCodeTitle"), self.tr("EnterCodeFirstTip"),
                parent=self.window(),
            )
            return
        self.tokenEdit.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.tokenEdit.setEnabled(True)
            if not result.ok:
                InfoBar.error(
                    self.tr("VerificationFailedTitle"), localize_http_error(result),
                    parent=self.window(),
                )
                return
            if plaza.is_admin:
                qconfig.set(cfg().exploreToken, token)
                InfoBar.success(
                    self.tr("VerifiedTitle"), self.tr("CodeAcceptedTip"),
                    parent=self.window(),
                )
            else:
                InfoBar.warning(
                    self.tr("VerificationFailedTitle"), self.tr("CodeRejectedTip"),
                    parent=self.window(),
                )

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
        self.appearanceGroup = SettingCardGroup(self.tr("AppearanceGroupTitle"), self)

        self.themeCard = OptionsSettingCard(
            cfg().themeMode,
            FIF.BRUSH,
            self.tr("ThemeCardTitle"),
            None,
            texts=[self.tr("FollowSystemLabel"), self.tr("LightLabel"), self.tr("DarkLabel")],
        )

        self.languageCard = OptionsSettingCard(
            cfg().language,
            FIF.LANGUAGE,
            self.tr("LanguageCardTitle"),
            None,
            texts=[self.tr("FollowSystemLabel"), "English", "简体中文"],
        )

        self.appearanceGroup.addSettingCard(self.themeCard)
        self.appearanceGroup.addSettingCard(self.languageCard)
        # Keep the group at its content height so the section below
        # stays adjacent (the group's internal stretch would otherwise
        # absorb all free layout space).
        self.appearanceGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.viewLayout.addWidget(self.appearanceGroup)

        # --- Advanced heading ---
        self.advancedGroup = SettingCardGroup(self.tr("AdvancedGroupTitle"), self)
        self.advancedGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.viewLayout.addWidget(self.advancedGroup)

        # --- Network (collapsed by default) ---
        self.apiGroup = ExpandGroupSettingCard(FIF.WIFI, self.tr("NetworkGroupTitle"), "", self)
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
        self.languageCard.optionChanged.connect(self._on_language_changed)

    def _apply_theme(self, _key) -> None:
        setTheme(qconfig.get(cfg().themeMode))

    def _on_language_changed(self, _key) -> None:
        """Persist the language choice; a restart is needed to take effect."""
        InfoBar.info(
            self.tr("LanguageCardTitle"),
            self.tr("LanguageRestartTip"),
            parent=self.window(),
            duration=4000,
        )
