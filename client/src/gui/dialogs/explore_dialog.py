"""Artwork detail dialog: preview, actions and (admin) status controls."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    InfoBar,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    StrongBodyLabel,
    TitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.network import HttpResult
from src.app.plaza import REASONS, STATUS_LABELS, plaza
from src.app.signal_bus import signalBus
from src.core import storage
from src.core.preview import generate_preview
from src.core.rulesets import decode_any_ruleset

_PREVIEW_SIZE = 240


def _fmt_time(value: str) -> str:
    """Format an ISO timestamp as ``YYYY-MM-DD HH:MM`` (local time)."""
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


class ReportReasonDialog(QDialog):
    """Pick a report reason for an artwork."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Report artwork")
        self.setFixedSize(380, 330)

        body = QVBoxLayout(self)
        body.setContentsMargins(24, 16, 24, 16)
        body.setSpacing(10)
        hint = CaptionLabel("Why are you reporting this artwork?", self)
        body.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(10)
        self._radios: list[RadioButton] = []
        for index, reason in enumerate(REASONS):
            radio = RadioButton(reason, self)
            radio.toggled.connect(self._on_toggled)
            self._radios.append(radio)
            grid.addWidget(radio, index // 2, index % 2)
        body.addLayout(grid)
        body.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.reportBtn = PrimaryPushButton("Report")
        self.reportBtn.setEnabled(False)
        self.reportBtn.clicked.connect(self.accept)
        self.cancelBtn = PushButton("Cancel")
        self.cancelBtn.clicked.connect(self.reject)
        buttons.addWidget(self.reportBtn)
        buttons.addWidget(self.cancelBtn)
        body.addLayout(buttons)

    def _on_toggled(self) -> None:
        self.reportBtn.setEnabled(any(r.isChecked() for r in self._radios))

    def selected_reason(self) -> str:
        return next(radio.text() for radio in self._radios if radio.isChecked())


class ExploreDetailDialog(QDialog):
    """Shows one artwork with actions gated by the server-granted permissions."""

    def __init__(self, dto: dict, permissions: dict | None = None, parent=None):
        super().__init__(parent)
        self.dto = dto
        self.content = dto["content"]
        self.permissions = permissions or {
            "can_feedback": True,
            "can_edit": False,
            "can_manage": False,
        }
        self.removed = False
        self.setWindowTitle("Artwork")
        self.setFixedSize(820, 480)
        self._build_ui()
        self._refresh_rating_state()
        self._refresh_report_state()
        self._apply_permissions()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        body = QHBoxLayout()
        body.setSpacing(28)

        # Left: preview with a compact size caption below it (no stylesheet).
        self.previewFrame = QFrame(self)
        self.previewFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.previewFrame.setFixedSize(_PREVIEW_SIZE + 32, _PREVIEW_SIZE + 52)
        frame_layout = QVBoxLayout(self.previewFrame)
        frame_layout.setContentsMargins(16, 14, 16, 12)
        frame_layout.setSpacing(6)
        self.previewLabel = QLabel()
        self.previewLabel.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self.previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.previewLabel)
        self.sizeLabel = CaptionLabel("")
        self.sizeLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.sizeLabel)
        body.addWidget(self.previewFrame)
        self._load_preview()

        # Right: title, description and metadata above the action rows.
        right = QVBoxLayout()
        right.setSpacing(10)

        self.nameLabel = TitleLabel(self.dto.get("name") or "Untitled")
        right.addWidget(self.nameLabel)

        description = (self.dto.get("description") or "").strip()
        self.descLabel = BodyLabel(description if description else "No description")
        self.descLabel.setWordWrap(True)
        right.addWidget(self.descLabel)

        # Metadata strip: votes and timestamps are admin-only.
        self.metaLabel = CaptionLabel("")
        self.metaLabel.setWordWrap(True)
        right.addWidget(self.metaLabel)
        right.addStretch()

        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        right.addWidget(divider)

        # Row 1 — saving (always visible)
        self.saveRow = QWidget()
        save_layout = QHBoxLayout(self.saveRow)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_layout.setSpacing(8)
        self.importBtn = PrimaryPushButton(FIF.EDIT, "Import to Canvas")
        self.copyBtn = PushButton(FIF.DOWNLOAD, "Copy to Gallery")
        self.importBtn.clicked.connect(self._on_import)
        self.copyBtn.clicked.connect(self._on_copy)
        save_layout.addWidget(self.importBtn)
        save_layout.addWidget(self.copyBtn)
        save_layout.addStretch()
        right.addWidget(self.saveRow)

        # Row 2 — feedback (can_feedback)
        self.feedbackRow = QWidget()
        feedback_layout = QHBoxLayout(self.feedbackRow)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        feedback_layout.setSpacing(8)
        self.likeBtn = PushButton(FIF.CARE_UP_SOLID, "Thumbs Up")
        self.dislikeBtn = PushButton(FIF.CARE_DOWN_SOLID, "Thumbs Down")
        self.reportBtn = PushButton(FIF.FLAG, "Report")
        self.likeBtn.clicked.connect(lambda: self._on_rate(1))
        self.dislikeBtn.clicked.connect(lambda: self._on_rate(0))
        self.reportBtn.clicked.connect(self._on_report)
        feedback_layout.addWidget(self.likeBtn)
        feedback_layout.addWidget(self.dislikeBtn)
        feedback_layout.addWidget(self.reportBtn)
        feedback_layout.addStretch()
        right.addWidget(self.feedbackRow)

        # Row 3 — edit/delete (can_edit)
        self.removeRow = QWidget()
        remove_layout = QHBoxLayout(self.removeRow)
        remove_layout.setContentsMargins(0, 0, 0, 0)
        self.removeBtn = PushButton(FIF.DELETE, "Remove from Plaza")
        self.removeBtn.setToolTip("Delete this artwork from the plaza")
        self.removeBtn.clicked.connect(self._on_remove)
        remove_layout.addWidget(self.removeBtn)
        remove_layout.addStretch()
        right.addWidget(self.removeRow)

        # Row 4 — management (can_manage)
        self.adminPanel = QWidget()
        admin_row = QHBoxLayout(self.adminPanel)
        admin_row.setContentsMargins(0, 0, 0, 0)
        admin_row.setSpacing(8)
        admin_row.addWidget(StrongBodyLabel("Status:"))
        self.statusCombo = ComboBox(self)
        for i, label in enumerate(STATUS_LABELS):
            self.statusCombo.addItem(label, userData=i)
        self.statusCombo.setFixedWidth(150)
        admin_row.addWidget(self.statusCombo)
        self.setStatusBtn = PushButton(FIF.ACCEPT, "Set Status")
        self.setStatusBtn.clicked.connect(self._on_audit)
        admin_row.addWidget(self.setStatusBtn)
        admin_row.addStretch()
        right.addWidget(self.adminPanel)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # Bottom: close button.
        self.closeBtn = PushButton(FIF.CLOSE, "Close")
        self.closeBtn.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.closeBtn)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_preview(self) -> None:
        decoded = decode_any_ruleset(self.content)
        if decoded is None:
            return
        png = generate_preview(decoded.pic)
        image = QImage.fromData(png)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            _PREVIEW_SIZE, _PREVIEW_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.previewLabel.setPixmap(pixmap)

    def _refresh_rating_state(self) -> None:
        value = plaza.rating_value(self.content)
        if value is not None:
            self.likeBtn.setEnabled(False)
            self.dislikeBtn.setEnabled(False)
            if value:
                self.likeBtn.setText("Rated: Thumbs Up")
            else:
                self.dislikeBtn.setText("Rated: Thumbs Down")

    def _refresh_report_state(self) -> None:
        self.reportBtn.setEnabled(not plaza.is_reported(self.content))

    def _apply_permissions(self) -> None:
        """Show/hide action rows and admin metadata according to the view rights."""
        feedback = self.permissions.get("can_feedback", True)
        can_edit = self.permissions.get("can_edit", False)
        can_manage = self.permissions.get("can_manage", False)

        self.removeRow.setVisible(can_edit)
        self.feedbackRow.setVisible(feedback)
        self.adminPanel.setVisible(can_manage)

        self.sizeLabel.setText(
            f"Size {self.dto.get('width')}x{self.dto.get('height')}"
        )
        parts = []
        if can_edit or can_manage:
            parts.append(f"Created {_fmt_time(self.dto.get('created_at', ''))}")
            parts.append(f"Updated {_fmt_time(self.dto.get('updated_at', ''))}")
            parts.append(
                f"Thumbs up {self.dto.get('up_votes', 0)}  ·  "
                f"Thumbs down {self.dto.get('down_votes', 0)}  ·  "
                f"Reports {self.dto.get('reports_count', 0)}"
            )
        self.metaLabel.setText(" · ".join(parts))
        if can_manage:
            current = plaza.admin_change(self.content) or self.dto.get("status", 0)
            index = self.statusCombo.findData(current)
            self.statusCombo.setCurrentIndex(max(0, index))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_import(self) -> None:
        self.accept()
        signalBus.importCode.emit(self.content)

    def _on_copy(self) -> None:
        decoded = decode_any_ruleset(self.content)
        if decoded is None:
            InfoBar.error(
                "Copy failed", "This artwork uses an unknown ruleset.",
                parent=self, duration=3000,
            )
            return
        stored = storage.StoredPic.from_ark_pic(
            decoded.name or self.dto.get("name") or "Untitled",
            decoded.description or "",
            decoded.pic,
            decoded.pic.rule,
        )
        storage.save(stored)
        signalBus.paintingSaved.emit()
        InfoBar.success(
            "Copied", "Artwork saved to your gallery.",
            parent=self, duration=2000,
        )

    def _on_rate(self, value: int) -> None:
        self.likeBtn.setEnabled(False)
        self.dislikeBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            if result.ok:
                plaza.mark_rated(self.content, value)
                if value:
                    self.likeBtn.setText("Rated: Thumbs Up")
                else:
                    self.dislikeBtn.setText("Rated: Thumbs Down")
                InfoBar.success(
                    "Thank you", "Your rating was recorded.",
                    parent=self, duration=2000,
                )
            else:
                self._refresh_rating_state()
                InfoBar.error(
                    "Rating failed", result.detail(),
                    parent=self, duration=3000,
                )

        plaza.rate(self.content, value, on_done)

    def _on_report(self) -> None:
        dialog = ReportReasonDialog(self)
        if not dialog.exec():
            return
        reason = dialog.selected_reason()
        self.reportBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            if result.ok:
                plaza.mark_reported(self.content)
                InfoBar.success(
                    "Reported", "The moderation team has been notified.",
                    parent=self, duration=2500,
                )
            else:
                self._refresh_report_state()
                InfoBar.error(
                    "Report failed", result.detail(),
                    parent=self, duration=3000,
                )

        plaza.report(self.content, reason, on_done)

    def _on_remove(self) -> None:
        """Delete this artwork from the plaza (uploader only)."""
        box = MessageBox(
            "Remove artwork?",
            "Remove this artwork from the plaza permanently?",
            self,
        )
        box.yesButton.setText("Remove")
        box.cancelButton.setText("Cancel")
        if not box.exec():
            return
        self.removeBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.removeBtn.setEnabled(True)
            if result.ok:
                self.removed = True
                InfoBar.success(
                    "Removed", "The artwork is no longer on the plaza.",
                    parent=self, duration=2500,
                )
                self.accept()
            else:
                InfoBar.error(
                    "Remove failed", result.detail(),
                    parent=self, duration=3000,
                )

        plaza.unpublish(self.content, on_done)

    def _on_audit(self) -> None:
        new_status = self.statusCombo.currentData()
        self.setStatusBtn.setEnabled(False)

        def on_done(result: HttpResult) -> None:
            self.setStatusBtn.setEnabled(True)
            if result.ok:
                plaza.record_admin_change(self.content, new_status)
                self.dto["status"] = new_status
                InfoBar.success(
                    "Status updated",
                    f"Artwork status is now: {STATUS_LABELS[new_status]}",
                    parent=self, duration=2500,
                )
            else:
                InfoBar.error(
                    "Update failed", result.detail(),
                    parent=self, duration=3000,
                )

        plaza.audit(self.content, new_status, on_done)
