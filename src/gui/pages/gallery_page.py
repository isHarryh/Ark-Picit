"""Gallery page: browse, edit, delete, export saved paintings."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    HeaderCardWidget,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.signal_bus import signalBus
from src.core import storage
from src.gui.components.base_page import BasePage


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
                96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            preview_label = BodyLabel()
            preview_label.setPixmap(thumb)
            layout.addWidget(preview_label)

        # Metadata
        meta = QVBoxLayout()
        meta.addWidget(BodyLabel(f"{stored.rule_width}x{stored.rule_height}"))
        meta.addWidget(BodyLabel(f"{len(stored.rule_colors)} colors"))
        meta.addWidget(BodyLabel(stored.last_saved[:19]))
        if stored.description:
            meta.addWidget(BodyLabel(stored.description))
        meta.addStretch()
        layout.addLayout(meta, 1)

        # Actions
        btns = QVBoxLayout()
        edit_btn = PushButton(FIF.EDIT, "Edit")
        export_btn = PushButton(FIF.SHARE, "Code")
        delete_btn = PushButton(FIF.DELETE, "Delete")
        edit_btn.clicked.connect(lambda: signalBus.editPainting.emit(stored.id))
        export_btn.clicked.connect(lambda: self._show_code(stored))
        delete_btn.clicked.connect(lambda: self._delete())
        btns.addWidget(edit_btn)
        btns.addWidget(export_btn)
        btns.addWidget(delete_btn)
        layout.addLayout(btns)

        self.viewLayout.addLayout(layout)

    def _show_code(self, stored: storage.StoredPic) -> None:
        from src.core import encode
        from src.gui.dialogs.code_dialog import CodeDialog

        pic, _ = stored.to_ark_pic()
        code = encode(pic, stored.name, stored.description)
        dialog = CodeDialog(code, self.window(), readonly=True)
        dialog.exec()

    def _delete(self) -> None:
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

        self.newBtn = PrimaryPushButton(FIF.ADD, "New Painting")
        self.refreshBtn = PushButton(FIF.SYNC, "Refresh")
        header.addStretch()
        header.addWidget(self.newBtn)
        header.addWidget(self.refreshBtn)
        self.viewLayout.addLayout(header)

        self.emptyListLabel = SubtitleLabel("No paintings yet. Create one!")
        self.viewLayout.addWidget(self.emptyListLabel)

        self.cardsLayout = QVBoxLayout()
        self.cardsLayout.setSpacing(8)
        self.viewLayout.addLayout(self.cardsLayout)
        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.newBtn.clicked.connect(lambda: signalBus.newPainting.emit())
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

        paintings = storage.list_all()
        self.emptyListLabel.setVisible(len(paintings) == 0)

        for stored in paintings:
            card = PaintingCard(stored)
            self.cardsLayout.addWidget(card)
