"""Dialog confirming a canvas replacement before applying an import."""

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel
from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel

from src.core.pic import ArkPic
from src.core.quantize import render_preview_bgr

_DISPLAY_WIDTH = 400


def _pic_to_pixmap(pic: ArkPic) -> QPixmap:
    """Render *pic* at a reasonable resolution, capped at the display width."""
    longest = max(pic.rule.width, pic.rule.height)
    scale = max(1, _DISPLAY_WIDTH // longest)
    preview = render_preview_bgr(pic, scale=scale)
    rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    image = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
    pixmap = QPixmap.fromImage(image)
    return pixmap.scaledToWidth(_DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)


class ConfirmImportDialog(MessageBoxBase):
    """Ask for confirmation before replacing the current canvas with an import.

    Args:
        pic: The painting about to be imported, shown as a preview.
        message: Guidance text displayed above the preview.
        parent: Parent widget.
    """

    def __init__(self, pic: ArkPic, message: str, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(520)
        self.viewLayout.setSpacing(12)
        self.viewLayout.addWidget(SubtitleLabel("Confirm import"))
        self.viewLayout.addWidget(BodyLabel(message))

        preview_label = QLabel()
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setPixmap(_pic_to_pixmap(pic))
        self.viewLayout.addWidget(preview_label)

        self.yesButton.setText("Continue")
        self.cancelButton.setText("Cancel")
