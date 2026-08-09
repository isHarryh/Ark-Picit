"""Dialogs for viewing a saved screenshot image and confirming the next step."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel
from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel, SwitchButton

from src.core.game_task import CanvasLayout

_DISPLAY_WIDTH = 640
_BLINK_INTERVAL_MS = 400


def _bgr_to_qpixmap(bgr: np.ndarray) -> QPixmap:
    """Convert a BGR uint8 array to a QPixmap."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    image = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class ImageViewerDialog(MessageBoxBase):
    """Show an image with an optional hint, confirming via custom button texts.

    Args:
        image_path: Path to the image file to display.
        title: Heading text shown above the image.
        hint: Guidance text shown below the title.
        confirm_text: Label of the accept button.
        cancel_text: Label of the cancel button.
        parent: Parent widget.
    """

    def __init__(
        self,
        image_path: str,
        title: str = "",
        hint: str = "",
        confirm_text: str = "OK",
        cancel_text: str = "Cancel",
        parent=None,
    ):
        super().__init__(parent)
        self.widget.setMinimumWidth(720)
        self.viewLayout.setSpacing(12)
        if title:
            self.viewLayout.addWidget(SubtitleLabel(title))
        if hint:
            self.viewLayout.addWidget(BodyLabel(hint))

        self.imageLabel = QLabel(self)
        self.imageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imageLabel.setPixmap(self._scaled(QPixmap(image_path)))
        self.viewLayout.addWidget(self.imageLabel)

        self.yesButton.setText(confirm_text)
        self.cancelButton.setText(cancel_text)

    @staticmethod
    def _scaled(pixmap: QPixmap) -> QPixmap:
        """Scale a pixmap down to the display width, keeping the aspect ratio."""
        if pixmap.width() > _DISPLAY_WIDTH:
            return pixmap.scaledToWidth(_DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)
        return pixmap


class RegionVerifyDialog(ImageViewerDialog):
    """Region verification with incremental painting toggle and blinking diff markers.

    Cells of the canvas whose in-game color differs from the painting blink
    in red on the displayed screenshot.

    Args:
        image_path: Path to the verification screenshot.
        layout: The recognized canvas layout (for cell rectangles).
        diff_cells: Set of (row, col) cells that differ from the painting.
        parent: Parent widget.
    """

    def __init__(
        self,
        image_path: str,
        layout: CanvasLayout,
        diff_cells: set[tuple[int, int]],
        parent=None,
    ):
        self._base_pixmap = self._scaled(QPixmap(image_path))
        self._marked_pixmap = self._build_marked_pixmap(image_path, layout, diff_cells)
        self._markers_visible = False
        super().__init__(
            image_path,
            title="Region verification",
            hint="Please confirm the canvas positioning is accurate, then click Start Drawing. "
            "Blinking red cells differ from the painting.",
            confirm_text="Start Drawing",
            cancel_text="Cancel",
            parent=parent,
        )

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        toggle_row.addWidget(BodyLabel("Incremental painting"))
        self.incrementalSwitch = SwitchButton()
        self.incrementalSwitch.setChecked(True)
        toggle_row.addWidget(self.incrementalSwitch)
        toggle_row.addStretch()
        self.viewLayout.addLayout(toggle_row)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(_BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._toggle_markers)
        self._blink_timer.start()

    @property
    def incremental_enabled(self) -> bool:
        """Return whether incremental painting is enabled."""
        return self.incrementalSwitch.isChecked()

    def _build_marked_pixmap(
        self,
        image_path: str,
        layout: CanvasLayout,
        diff_cells: set[tuple[int, int]],
    ) -> QPixmap:
        image = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if image is None:
            return self._base_pixmap
        for row, col in diff_cells:
            rect = layout.cell_region(row, col)
            cv2.rectangle(image, (rect.x, rect.y), (rect.x + rect.w, rect.y + rect.h), (0, 0, 255), 1)
        return self._scaled(_bgr_to_qpixmap(image))

    def _toggle_markers(self) -> None:
        self._markers_visible = not self._markers_visible
        self.imageLabel.setPixmap(self._marked_pixmap if self._markers_visible else self._base_pixmap)

    def accept(self) -> None:
        """Stop blinking before accepting."""
        self._blink_timer.stop()
        super().accept()

    def reject(self) -> None:
        """Stop blinking before rejecting."""
        self._blink_timer.stop()
        super().reject()

    def closeEvent(self, event) -> None:
        """Stop blinking when the dialog closes."""
        self._blink_timer.stop()
        super().closeEvent(event)
