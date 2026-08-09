"""Gallery page: browse, edit, delete, export saved paintings."""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    HeaderCardWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    TitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.signal_bus import signalBus
from src.core import storage
from src.gui.components.base_page import BasePage
from src.gui.dialogs.rename_dialog import RenameDialog


def _format_saved_time(value: str) -> str:
    """Format an ISO saved-time string in local time as ``YYYY-MM-DD HH:MM:SS``."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class PaintingCard(HeaderCardWidget):
    """A single painting entry in the gallery."""

    def __init__(self, stored: storage.StoredPic, parent=None):
        super().__init__(parent)
        self.stored = stored
        self.setTitle(stored.name or "Untitled")
        self.setFixedHeight(200)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Preview thumbnail (scaled up from 1:1)
        if stored.preview_png:
            img = QImage.fromData(stored.preview_png)
            thumb = QPixmap.fromImage(img).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            preview_label = BodyLabel()
            preview_label.setPixmap(thumb)
            layout.addWidget(preview_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Metadata (vertically centered so rows line up across cards)
        meta = QVBoxLayout()
        meta.addStretch()
        if stored.description:
            meta.addWidget(BodyLabel(f"Description: {stored.description}"))
        meta.addWidget(
            BodyLabel(
                f"Size {stored.rule_width}x{stored.rule_height}, "
                f"Palette {len(stored.rule_colors)} colors"
            )
        )
        meta.addWidget(BodyLabel(_format_saved_time(stored.last_saved)))
        meta.addStretch()
        layout.addLayout(meta, 1)

        # Actions (2x2 grid, vertically centered)
        btns = QGridLayout()
        btns.setSpacing(4)
        open_btn = PrimaryPushButton(FIF.EDIT, "Open")
        export_btn = PushButton(FIF.SHARE, "Code")
        rename_btn = PushButton(FIF.TAG, "Rename")
        delete_btn = PushButton(FIF.DELETE, "Delete")
        open_btn.clicked.connect(lambda: signalBus.editPainting.emit(stored.id))
        export_btn.clicked.connect(lambda: self._show_code(stored))
        rename_btn.clicked.connect(self._rename)
        delete_btn.clicked.connect(lambda: self._delete())
        btns.addWidget(open_btn, 0, 0)
        btns.addWidget(export_btn, 0, 1)
        btns.addWidget(rename_btn, 1, 0)
        btns.addWidget(delete_btn, 1, 1)
        btns_holder = QVBoxLayout()
        btns_holder.addStretch()
        btns_holder.addLayout(btns)
        btns_holder.addStretch()
        layout.addLayout(btns_holder)

        self.viewLayout.addLayout(layout)

    def _show_code(self, stored: storage.StoredPic) -> None:
        from src.core import encode
        from src.gui.dialogs.code_dialog import CodeDialog

        pic, _ = stored.to_ark_pic()
        code = encode(pic, stored.name, stored.description)
        dialog = CodeDialog(code, self.window(), readonly=True)
        dialog.exec()

    def _rename(self) -> None:
        """Edit the name/description, optionally refreshing the saved time."""
        dialog = RenameDialog(self.stored, self.window())
        if not dialog.exec():
            return
        self.stored.name = dialog.new_name
        self.stored.description = dialog.new_description
        if dialog.update_time:
            self.stored.last_saved = datetime.now().isoformat(timespec="seconds")
        storage.save(self.stored)
        signalBus.paintingSaved.emit()

    def _delete(self) -> None:
        box = MessageBox(
            "Delete painting?",
            f"Delete '{self.stored.name}' permanently?",
            self.window(),
        )
        box.yesButton.setText("Delete")
        box.cancelButton.setText("Cancel")
        if not box.exec():
            return
        storage.delete(self.stored.id)
        signalBus.paintingSaved.emit()
        self.setParent(None)
        self.deleteLater()


class GalleryPage(BasePage):
    """Lists all saved paintings as cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self.refresh()

    def _build_ui(self) -> None:
        header = QHBoxLayout()
        header.addWidget(TitleLabel("Gallery"))

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("Search by name or description")
        header.addStretch()
        header.addWidget(self.searchEdit)
        self.refreshBtn = PushButton(FIF.SYNC, "Refresh")
        header.addWidget(self.refreshBtn)
        self.viewLayout.addLayout(header)

        self.emptyListLabel = SubtitleLabel("No paintings yet. Create one!")
        self.viewLayout.addWidget(self.emptyListLabel)

        self.cardsLayout = QVBoxLayout()
        self.cardsLayout.setSpacing(8)
        self.viewLayout.addLayout(self.cardsLayout)
        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.searchEdit.textChanged.connect(self._filter)
        self.refreshBtn.clicked.connect(self.refresh)
        signalBus.paintingSaved.connect(self.refresh)

    def refresh(self) -> None:
        """Reload all paintings from storage."""
        # Clear existing cards
        while self.cardsLayout.count():
            item = self.cardsLayout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        for stored in storage.list_all():
            card = PaintingCard(stored)
            self.cardsLayout.addWidget(card)
        self._filter(self.searchEdit.text())

    def _filter(self, text: str) -> None:
        """Show only cards whose name or description matches *text*, case-insensitively."""
        query = text.strip().lower()
        visible = 0
        for i in range(self.cardsLayout.count()):
            card = self.cardsLayout.itemAt(i).widget()
            if not isinstance(card, PaintingCard):
                continue
            matches = (
                not query
                or query in card.stored.name.lower()
                or query in card.stored.description.lower()
            )
            card.setVisible(matches)
            if matches:
                visible += 1
        if self.cardsLayout.count() == 0:
            self.emptyListLabel.setText("No paintings yet. Create one!")
            self.emptyListLabel.setVisible(True)
        elif visible == 0:
            self.emptyListLabel.setText("No paintings match your search")
            self.emptyListLabel.setVisible(True)
        else:
            self.emptyListLabel.setVisible(False)
