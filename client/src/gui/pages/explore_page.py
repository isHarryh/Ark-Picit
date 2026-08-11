"""Explore page: browse plaza artworks as a dense grid of preview cards.

The page has three views (Random / Mine / Admin) implemented as a small
``ExploreView`` class hierarchy; each view configures the filter bar and the
list request, and carries the permissions granted by the server.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    FlowLayout,
    IndeterminateProgressBar,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    isDarkTheme,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.i18n import fmt, localize_http_error
from src.app.network import HttpResult
from src.app.plaza import SORT_OPTIONS, STATUS_COUNT, plaza, sort_label, status_label
from src.core.preview import generate_preview
from src.core.rulesets import decode_any_ruleset
from src.gui.components.base_page import BasePage
from src.gui.dialogs.explore_dialog import ExploreDetailDialog

_PAGE_SIZE = 20
_CARD_WIDTH = 150
_PREVIEW_SIZE = 112


class ExploreView:
    """Base class for an explore list mode.

    Subclasses decide which filter controls are visible and how the list
    request is parameterized; the server replies with permission flags that
    are stored on the instance for the detail dialog.
    """

    mode = "random"

    def __init__(self):
        self.permissions = {"can_feedback": True, "can_edit": False, "can_manage": False}

    def configure_controls(self, page: "ExplorePage") -> None:
        """Toggle the filter bar widgets for this view."""

    def include_status(self, page: "ExplorePage") -> str:
        return ""

    def sort_by(self, page: "ExplorePage") -> str:
        return ""

    def order(self, page: "ExplorePage") -> str:
        return ""


class RandomView(ExploreView):
    """Public random browsing: no filters, no pagination."""

    mode = "random"

    def configure_controls(self, page: "ExplorePage") -> None:
        for check in page.statusChecks:
            check.setVisible(False)
        page.sortCombo.setVisible(False)
        page.orderCombo.setVisible(False)
        page.pageCombo.setVisible(False)


class MineView(ExploreView):
    """The uploading client's own artworks: pagination only."""

    mode = "mine"

    def configure_controls(self, page: "ExplorePage") -> None:
        for check in page.statusChecks:
            check.setVisible(False)
        page.sortCombo.setVisible(False)
        page.orderCombo.setVisible(False)
        page.pageCombo.setVisible(True)


class AdminView(ExploreView):
    """Moderation: full filtering (status, sort, order, pagination)."""

    mode = "admin"

    def configure_controls(self, page: "ExplorePage") -> None:
        for check in page.statusChecks:
            check.setVisible(True)
        page.sortCombo.setVisible(True)
        page.orderCombo.setVisible(True)
        page.pageCombo.setVisible(True)

    def include_status(self, page: "ExplorePage") -> str:
        return ",".join(
            str(i)
            for i, check in enumerate(page.statusChecks)
            if check.isChecked()
        )

    def sort_by(self, page: "ExplorePage") -> str:
        return page.sortCombo.currentData()

    def order(self, page: "ExplorePage") -> str:
        return page.orderCombo.currentData()


class ArtworkCard(QWidget):
    """A single artwork entry: preview, single-line name and optional status."""

    clicked = Signal(object)  # the artwork DTO dict

    def __init__(self, dto: dict, parent=None):
        super().__init__(parent)
        self.dto = dto
        self.setFixedSize(_CARD_WIDTH, 218)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Native hover/pressed feedback via stylesheet pseudo-states.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dark = isDarkTheme()
        hover = "rgba(255, 255, 255, 0.06)" if dark else "rgba(0, 0, 0, 0.05)"
        pressed = "rgba(255, 255, 255, 0.11)" if dark else "rgba(0, 0, 0, 0.09)"
        self.setStyleSheet(
            f"ArtworkCard {{ border-radius: 6px; }}"
            f"ArtworkCard:hover {{ background: {hover}; }}"
            f"ArtworkCard:pressed {{ background: {pressed}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.previewLabel = QLabel()
        self.previewLabel.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self.previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previewLabel.setObjectName("explorePreview")
        self.previewLabel.setStyleSheet(
            "QLabel#explorePreview { border: 1px solid rgba(0, 0, 0, 0.08);"
            " background: rgba(0, 0, 0, 0.03); border-radius: 4px; }"
        )
        layout.addWidget(self.previewLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        # Title: centered on one line and elided when it exceeds the card width.
        name = dto.get("name") or self.tr("UntitledName")
        self.nameLabel = StrongBodyLabel()
        self.nameLabel.setText(
            self.nameLabel.fontMetrics().elidedText(
                name, Qt.TextElideMode.ElideRight, _CARD_WIDTH - 24
            )
        )
        self.nameLabel.setWordWrap(False)
        self.nameLabel.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.nameLabel.setFixedHeight(self.nameLabel.fontMetrics().lineSpacing())
        layout.addWidget(self.nameLabel)

        # Status line (only shown when the server returns a status field,
        # e.g. Mine/Admin modes; Random mode omits it).
        self.statusLabel = CaptionLabel("")
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.statusLabel.setVisible(False)
        layout.addWidget(self.statusLabel)
        self._apply_status()

        layout.addStretch()

    def _apply_status(self) -> None:
        if "status" not in self.dto:
            return
        status = int(self.dto.get("status", 0))
        self.statusLabel.setText(status_label(status))
        self.statusLabel.setVisible(True)

    def set_preview(self, png: bytes) -> None:
        if not png:
            return
        image = QImage.fromData(png)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            _PREVIEW_SIZE, _PREVIEW_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.previewLabel.setPixmap(pixmap)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.dto)
        super().mouseReleaseEvent(event)


class _PreviewLoader(QObject):
    """Decodes ArkPicCode and renders previews off the GUI thread."""

    done = Signal(str, bytes)  # content, preview PNG bytes

    def __init__(self, parent=None):
        super().__init__(parent)

    def load(self, content: str) -> None:
        threading.Thread(target=self._work, args=(content,), daemon=True).start()

    def _work(self, content: str) -> None:
        try:
            decoded = decode_any_ruleset(content)
            png = generate_preview(decoded.pic) if decoded else b""
        except Exception:
            png = b""
        self.done.emit(content, png)


class ExplorePage(BasePage):
    """Dense preview grid with Random / Mine / Admin view switching."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, ArtworkCard] = {}
        self._loader = _PreviewLoader(self)
        self._page = 1
        self._pending = False
        self._cooldown: int | None = None
        self._cooldownTimer = QTimer(self)
        self._cooldownTimer.setInterval(1000)
        self._cooldownTimer.timeout.connect(self._on_cooldown_tick)
        self._views: dict[str, ExploreView] = {
            "random": RandomView(),
            "mine": MineView(),
            "admin": AdminView(),
        }
        self._view: ExploreView = self._views["random"]
        self._build_ui()
        self._connect_signals()
        self._apply_admin_mode()
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        header = QHBoxLayout()
        header.addWidget(TitleLabel(self.tr("ExploreTitle")))
        header.addSpacing(12)
        self.viewCombo = ComboBox(self)
        self.viewCombo.addItem(self.tr("ViewRandom"), userData="random")
        self.viewCombo.addItem(self.tr("ViewMine"), userData="mine")
        # The Admin entry is appended by _apply_admin_mode when available.
        header.addWidget(self.viewCombo)
        header.addSpacing(8)
        self.pageCombo = ComboBox(self)
        header.addWidget(self.pageCombo)
        header.addStretch()
        self.refreshBtn = PushButton(FIF.SYNC, self.tr("RefreshButton"))
        header.addWidget(self.refreshBtn)
        self.viewLayout.addLayout(header)

        # Filter bar (which parts are visible depends on the active view)
        self.filters = QWidget()
        filter_row = QHBoxLayout(self.filters)
        filter_row.setContentsMargins(0, 0, 0, 0)
        self.statusChecks: list[CheckBox] = []
        for status in range(STATUS_COUNT):
            check = CheckBox(status_label(status), self)
            check.setChecked(True)
            self.statusChecks.append(check)
            filter_row.addWidget(check)
        filter_row.addSpacing(8)
        self.sortCombo = ComboBox(self)
        for key in SORT_OPTIONS:
            self.sortCombo.addItem(sort_label(key), userData=key)
        self.sortCombo.setCurrentIndex(0)
        filter_row.addWidget(self.sortCombo)
        self.orderCombo = ComboBox(self)
        self.orderCombo.addItem(self.tr("OrderDescending"), userData="desc")
        self.orderCombo.addItem(self.tr("OrderAscending"), userData="asc")
        filter_row.addWidget(self.orderCombo)
        filter_row.addStretch()
        self.viewLayout.addWidget(self.filters)

        self.progress = IndeterminateProgressBar(self)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        self.viewLayout.addWidget(self.progress)

        self.emptyLabel = SubtitleLabel(self.tr("NoArtworksEmpty"))
        self.viewLayout.addWidget(self.emptyLabel)

        self.flow = FlowLayout()
        self.viewLayout.addLayout(self.flow)
        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.viewCombo.currentIndexChanged.connect(self._on_view_changed)
        for check in self.statusChecks:
            check.stateChanged.connect(self._on_filter_changed)
        self.sortCombo.currentIndexChanged.connect(self._on_filter_changed)
        self.orderCombo.currentIndexChanged.connect(self._on_filter_changed)
        self.pageCombo.currentIndexChanged.connect(self._on_page_selected)
        self.refreshBtn.clicked.connect(self.refresh)
        self._loader.done.connect(self._on_preview_ready)
        plaza.adminChanged.connect(self._on_admin_changed)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _on_admin_changed(self, _admin: bool) -> None:
        self._apply_admin_mode()
        self.refresh()

    def _apply_admin_mode(self) -> None:
        """Add or remove the Admin mode entry based on the verified state."""
        admin_index = self.viewCombo.findData("admin")
        if plaza.is_admin:
            if admin_index < 0:
                self.viewCombo.addItem(self.tr("ViewAdmin"), userData="admin")
        else:
            # Leave the Admin view first; removing the selected entry would
            # make Qt fall back to the Mine entry and switch the view.
            if self._view.mode == "admin":
                self._view = self._views["random"]
                self.viewCombo.setCurrentIndex(self.viewCombo.findData("random"))
            if admin_index >= 0:
                self.viewCombo.removeItem(admin_index)
        self._view.configure_controls(self)

    def _on_view_changed(self, _index: int) -> None:
        self._view = self._views.get(self.viewCombo.currentData(), self._views["random"])
        self._page = 1
        self._view.configure_controls(self)
        self.refresh()

    def _on_filter_changed(self, *_args) -> None:
        self._page = 1
        self.refresh()

    def _on_page_selected(self, _index: int) -> None:
        page = self.pageCombo.currentData()
        if page is not None and page != self._page:
            self._page = page
            self.refresh()

    def _update_page_combo(self, has_next: bool) -> None:
        """Rebuild the page dropdown: current page plus the next when available."""
        self.pageCombo.blockSignals(True)
        self.pageCombo.clear()
        end = self._page + 1 if has_next else self._page
        for page in range(1, end + 1):
            self.pageCombo.addItem(fmt(self.tr("PageFormat"), page), userData=page)
        self.pageCombo.setCurrentIndex(self.pageCombo.findData(self._page))
        self.pageCombo.blockSignals(False)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        if self._pending:
            return
        if self._view.mode != "admin" and not self._can_refresh():
            return
        plaza.clear_admin_changes()
        self._pending = True
        self.progress.setVisible(True)
        self.refreshBtn.setEnabled(False)
        self._start_cooldown()
        view = self._view
        plaza.explore_list(
            view.mode,
            page_size=_PAGE_SIZE,
            page_number=self._page,
            include_status=view.include_status(self),
            sort_by=view.sort_by(self),
            order=view.order(self),
            on_done=self._on_list_result,
        )

    def _start_cooldown(self) -> None:
        """Start the 5s non-admin refresh cooldown, if not already running."""
        if self._view.mode == "admin" or self._cooldown is not None:
            return
        self._cooldown = 5
        self.refreshBtn.setText(fmt(self.tr("RefreshCooldownFormat"), self._cooldown))
        self.viewCombo.setEnabled(False)
        self.pageCombo.setEnabled(False)
        self._cooldownTimer.start(1000)

    def _can_refresh(self) -> bool:
        return self._cooldown is None

    def _on_cooldown_tick(self) -> None:
        self._cooldown -= 1
        if self._cooldown <= 0:
            self._cooldownTimer.stop()
            self._cooldown = None
            self.viewCombo.setEnabled(True)
            self.pageCombo.setEnabled(True)
            if not self._pending:
                self.refreshBtn.setEnabled(True)
            self.refreshBtn.setText(self.tr("RefreshButton"))
            return
        self.refreshBtn.setText(fmt(self.tr("RefreshCooldownFormat"), self._cooldown))

    def _on_list_result(self, result: HttpResult) -> None:
        self._pending = False
        self.progress.setVisible(False)
        self.refreshBtn.setEnabled(self._view.mode == "admin" or self._cooldown is None)
        if not result.ok:
            self.emptyLabel.setText(
                fmt(self.tr("LoadFailedTip"), localize_http_error(result))
            )
            self.emptyLabel.setVisible(True)
            self._clear_cards()
            return

        data = result.data or {}
        self._view.permissions = {
            "can_feedback": data.get("can_feedback", True),
            "can_edit": data.get("can_edit", False),
            "can_manage": data.get("can_manage", False),
        }
        artworks = data.get("artworks", [])
        self.emptyLabel.setText(self.tr("NoArtworksEmpty"))
        self.emptyLabel.setVisible(not artworks)
        self._update_page_combo(len(artworks) == _PAGE_SIZE)
        self._rebuild_cards(artworks)

    def _clear_cards(self) -> None:
        # FlowLayout.takeAt() returns the widget itself (not a QLayoutItem),
        # and removed widgets stay painted until re-parented away.
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item if isinstance(item, QWidget) else (
                item.widget() if item is not None else None
            )
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()

    def _rebuild_cards(self, artworks: list[dict]) -> None:
        self._clear_cards()
        for dto in artworks:
            card = ArtworkCard(dto)
            card.clicked.connect(self._open_detail)
            self.flow.addWidget(card)
            self._cards[dto["content"]] = card
            self._loader.load(dto["content"])

    def _on_preview_ready(self, content: str, png: bytes) -> None:
        card = self._cards.get(content)
        if card is not None:
            card.set_preview(png)

    def _open_detail(self, dto: dict) -> None:
        dialog = ExploreDetailDialog(dto, self._view.permissions, self.window())
        dialog.exec()
        if dialog.removed:
            self.refresh()
