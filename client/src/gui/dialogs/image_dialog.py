"""Dialogs for viewing a saved screenshot image and confirming the next step."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    MessageBoxBase,
    SubtitleLabel,
    SwitchButton,
)

from src.app.i18n import fmt
from src.core.tasks import CanvasLayout

_DISPLAY_WIDTH = 640
_BLINK_INTERVAL_MS = 400

# (click delay in ms, catalog key); the default selection is the Normal entry.
_SPEED_OPTIONS = (
    (17, "SpeedVeryFastFormat"),
    (34, "SpeedFastFormat"),
    (67, "SpeedNormalFormat"),
    (100, "SpeedSlowFormat"),
    (167, "SpeedVerySlowFormat"),
)


def _mark_speed_option_sources() -> None:
    """Keep the drawing speed keys in the translation catalogs.

    lupdate only extracts literal arguments, so each key is repeated here
    as a literal ``translate()`` call. Never executed.
    """
    QCoreApplication.translate("RegionVerifyDialog", "SpeedVeryFastFormat")
    QCoreApplication.translate("RegionVerifyDialog", "SpeedFastFormat")
    QCoreApplication.translate("RegionVerifyDialog", "SpeedNormalFormat")
    QCoreApplication.translate("RegionVerifyDialog", "SpeedSlowFormat")
    QCoreApplication.translate("RegionVerifyDialog", "SpeedVerySlowFormat")


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
            title=self.tr("RegionVerifyTitle"),
            hint=self.tr("RegionVerifyTip"),
            confirm_text=self.tr("StartDrawingButton"),
            cancel_text=self.tr("CancelButton"),
            parent=parent,
        )

        self.viewLayout.addWidget(CaptionLabel(self.tr("DrawingOptionsTitle")))

        # Two-column row: incremental toggle and drawing speed, edge-aligned
        self.incrementalSwitch = SwitchButton()
        self.incrementalSwitch.setChecked(True)
        speed_label = BodyLabel(self.tr("DrawingSpeedLabel"))
        self.speedCombo = ComboBox()
        for delay_ms, key in _SPEED_OPTIONS:
            self.speedCombo.addItem(fmt(self.tr(key), delay_ms), userData=delay_ms)
        self.speedCombo.setCurrentIndex(
            next(i for i, (delay_ms, _) in enumerate(_SPEED_OPTIONS) if delay_ms == 67)
        )

        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(8)
        options_grid.addWidget(BodyLabel(self.tr("IncrementalLabel")), 0, 0)
        options_grid.addWidget(self.incrementalSwitch, 0, 1)
        options_grid.addWidget(speed_label, 0, 2)
        options_grid.addWidget(self.speedCombo, 0, 3)
        options_grid.setColumnStretch(1, 1)
        options_grid.setColumnStretch(3, 1)
        self.viewLayout.addLayout(options_grid)

        self.speedWarnLabel = CaptionLabel(self.tr("SpeedWarningTip"))
        self.viewLayout.addWidget(self.speedWarnLabel)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(_BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._toggle_markers)
        self._blink_timer.start()

    @property
    def incremental_enabled(self) -> bool:
        """Return whether incremental painting is enabled."""
        return self.incrementalSwitch.isChecked()

    @property
    def click_delay_ms(self) -> int:
        """Return the pause between cell clicks, in milliseconds."""
        return self.speedCombo.currentData()

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
