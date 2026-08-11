"""Two-step Smart Create dialog.

Step 1: Choose image source (file or clipboard).
Step 2: Two-column editor — left: crop & sampling controls, right: live preview.
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.i18n import fmt
from src.core.pic import ArkPic
from src.core.quantize import quantize_image, render_preview_bgr
from src.core.rule import ArkPicRule
from src.gui.components.clipboard_helper import get_clipboard_image_bgr
from src.gui.components.image_cropper import ImageCropper


def _bgr_to_qimage(bgr: np.ndarray) -> QImage:
    """Convert BGR uint8 array to QImage."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


class SmartCreateDialog(QDialog):
    """Two-step dialog for image → pixel art conversion."""

    def __init__(self, rule: ArkPicRule, parent=None):
        super().__init__(parent)
        self._rule = rule
        self._source_bgr: np.ndarray | None = None
        self._cropped_bgr: np.ndarray | None = None
        self._result_pic: ArkPic | None = None

        self.setWindowTitle(self.tr("SmartCreateButton"))
        self.setMinimumSize(900, 600)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # --- Title ---
        self.titleLabel = TitleLabel(self.tr("SmartCreateButton"))
        root.addWidget(self.titleLabel)

        # --- Step 1: source selection ---
        self.step1Widget = QWidget()
        s1 = QVBoxLayout(self.step1Widget)
        s1.setContentsMargins(0, 0, 0, 0)
        s1.setSpacing(16)

        s1.addWidget(SubtitleLabel(self.tr("ChooseImageHint")))

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        self.btnFile = PrimaryPushButton(FIF.FOLDER, self.tr("ChooseFileButton"))
        self.btnClipboard = PushButton(FIF.LINK, self.tr("FromClipboardButton"))
        source_row.addStretch()
        source_row.addWidget(self.btnFile)
        source_row.addWidget(self.btnClipboard)
        source_row.addStretch()
        s1.addLayout(source_row)

        self.sourcePreview = QLabel()
        self.sourcePreview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sourcePreview.setMinimumHeight(350)
        self.sourcePreview.setText(
            self.tr("NoImageSelectedTip")
        )
        s1.addWidget(self.sourcePreview, 1)

        s1.addStretch()
        root.addWidget(self.step1Widget)

        # --- Step 2: two-column editor ---
        self.step2Widget = QWidget()
        s2 = QHBoxLayout(self.step2Widget)
        s2.setContentsMargins(0, 0, 0, 0)
        s2.setSpacing(16)

        # Left column: crop + controls
        left = QVBoxLayout()
        left.setSpacing(10)

        left.addWidget(StrongBodyLabel(self.tr("CropTitle")))

        ratio_row = QHBoxLayout()
        ratio_row.addWidget(BodyLabel(self.tr("AspectLabel")))
        self.ratioCombo = ComboBox()
        self.ratioCombo.addItem(
            fmt(self.tr("RuleFormat"), self._rule.width, self._rule.height),
            userData="rule",
        )
        self.ratioCombo.addItem(self.tr("FreeLabel"), userData="free")
        self.ratioCombo.currentIndexChanged.connect(self._on_ratio_changed)
        ratio_row.addWidget(self.ratioCombo)
        ratio_row.addStretch()
        left.addLayout(ratio_row)

        self.cropper = ImageCropper()
        self.cropper.cropChanged.connect(self._on_crop_changed)
        left.addWidget(self.cropper, 1)

        left_col_widget = QWidget()
        left_col_widget.setLayout(left)
        s2.addWidget(left_col_widget, 1)

        # Right column: options + live preview
        right = QVBoxLayout()
        right.setSpacing(10)

        right.addWidget(StrongBodyLabel(self.tr("PreviewTitle")))

        # Sampling and color matching options, one row of two columns
        options = QGridLayout()
        options.setHorizontalSpacing(8)
        options.addWidget(BodyLabel(self.tr("SamplingLabel")), 0, 0)
        self.samplingCombo = ComboBox()
        self.samplingCombo.addItem(self.tr("SamplingNearest"), userData="nearest")
        self.samplingCombo.addItem(self.tr("SamplingBilinear"), userData="bilinear")
        self.samplingCombo.addItem(self.tr("SamplingBicubic"), userData="bicubic")
        self.samplingCombo.setCurrentIndex(1)
        self.samplingCombo.currentIndexChanged.connect(self._on_option_changed)
        options.addWidget(self.samplingCombo, 0, 1)
        options.addWidget(BodyLabel(self.tr("ColorsLabel")), 0, 2)
        self.colorCombo = ComboBox()
        self.colorCombo.addItem(self.tr("ColorRgbLinear"), userData="rgb_linear")
        self.colorCombo.addItem(self.tr("ColorRgbSquared"), userData="rgb_squared")
        self.colorCombo.addItem(self.tr("ColorGrayscale"), userData="grayscale")
        self.colorCombo.addItem(self.tr("ColorVoting"), userData="voting")
        self.colorCombo.setCurrentIndex(1)
        self.colorCombo.currentIndexChanged.connect(self._on_option_changed)
        options.addWidget(self.colorCombo, 0, 3)
        options.setColumnStretch(1, 1)
        options.setColumnStretch(3, 1)
        right.addLayout(options)

        self.quantPreview = QLabel()
        self.quantPreview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.quantPreview.setMinimumHeight(350)
        self.quantPreview.setStyleSheet("background-color: #2b2b2b; border-radius: 4px;")
        right.addWidget(self.quantPreview, 1)

        right_col_widget = QWidget()
        right_col_widget.setLayout(right)
        s2.addWidget(right_col_widget, 1)

        root.addWidget(self.step2Widget)
        self.step2Widget.setVisible(False)

        # --- Bottom action bar ---
        bottom = QHBoxLayout()

        self.btnCancel = PushButton(self.tr("CancelButton"))
        self.btnBack = PushButton(FIF.LEFT_ARROW, self.tr("ChangeImageButton"))
        self.btnConfirm = PrimaryPushButton(FIF.ACCEPT, self.tr("ConfirmButton"))

        bottom.addWidget(self.btnCancel)
        bottom.addStretch()
        bottom.addWidget(self.btnBack)
        bottom.addWidget(self.btnConfirm)

        self.btnBack.setVisible(False)
        self.btnConfirm.setVisible(False)

        root.addLayout(bottom)

        # --- Connections ---
        self.btnCancel.clicked.connect(self.reject)
        self.btnConfirm.clicked.connect(self._on_confirm)
        self.btnBack.clicked.connect(self._go_step1)
        self.btnFile.clicked.connect(self._choose_file)
        self.btnClipboard.clicked.connect(self._from_clipboard)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_step1(self) -> None:
        self.step1Widget.setVisible(True)
        self.step2Widget.setVisible(False)
        self.btnBack.setVisible(False)
        self.btnConfirm.setVisible(False)

    def _go_step2(self) -> None:
        self.step1Widget.setVisible(False)
        self.step2Widget.setVisible(True)
        self.btnBack.setVisible(True)
        self.btnConfirm.setVisible(True)
        self._setup_cropper()

    def _on_confirm(self) -> None:
        self._do_crop()
        self._do_quantize()
        self.accept()

    # ------------------------------------------------------------------
    # Step 1: Image source
    # ------------------------------------------------------------------

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("ChooseImageTitle"), "",
            self.tr("ImageFilter"),
        )
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            InfoBar.error(self.tr("ErrorTitle"), self.tr("ImageLoadFailedTip"),
                          parent=self, duration=3000)
            return
        self._set_source(img)

    def _from_clipboard(self) -> None:
        bgr = get_clipboard_image_bgr()
        if bgr is None:
            InfoBar.warning(self.tr("ClipboardTitle"), self.tr("NoClipboardImageTip"),
                            parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        self._set_source(bgr)

    def _set_source(self, bgr: np.ndarray) -> None:
        self._source_bgr = bgr
        self._cropped_bgr = bgr
        # Show preview (scaled to fit)
        qimg = _bgr_to_qimage(bgr)
        pm = QPixmap.fromImage(qimg)
        scaled = pm.scaled(
            640, 350,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.sourcePreview.setPixmap(scaled)
        # Go to step 2
        self._go_step2()

    # ------------------------------------------------------------------
    # Step 2: Crop + live preview
    # ------------------------------------------------------------------

    def _setup_cropper(self) -> None:
        if self._source_bgr is None:
            return
        qimg = _bgr_to_qimage(self._source_bgr)
        self.cropper.set_image(qimg)
        self.cropper.set_aspect_ratio(self._rule.width / self._rule.height)
        self._update_preview()

    def _on_ratio_changed(self, index: int) -> None:
        key = self.ratioCombo.itemData(index)
        if key == "free":
            self.cropper.set_aspect_ratio(None)
        else:
            self.cropper.set_aspect_ratio(self._rule.width / self._rule.height)
        self._update_preview()

    def _on_crop_changed(self) -> None:
        self._update_preview()

    def _on_option_changed(self) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        """Re-crop and re-quantize, then update the right-side preview."""
        self._do_crop()
        self._do_quantize()

    def _do_crop(self) -> None:
        crop_rect = self.cropper.get_crop_rect()
        if crop_rect.isEmpty() or self._source_bgr is None:
            self._cropped_bgr = self._source_bgr
            return
        x, y = crop_rect.x(), crop_rect.y()
        w, h = max(1, crop_rect.width()), max(1, crop_rect.height())
        self._cropped_bgr = self._source_bgr[y:y + h, x:x + w].copy()

    def _do_quantize(self) -> None:
        if self._cropped_bgr is None:
            return
        self._result_pic = quantize_image(
            self._cropped_bgr,
            self._rule,
            sampling=self.samplingCombo.currentData(),
            color_match=self.colorCombo.currentData(),
        )
        target_pixels = 400
        scale = max(1, target_pixels // max(self._rule.width, self._rule.height))
        preview_bgr = render_preview_bgr(self._result_pic, scale=scale)
        qimg = _bgr_to_qimage(preview_bgr)
        self.quantPreview.setPixmap(QPixmap.fromImage(qimg))

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    @property
    def result_pic(self) -> ArkPic | None:
        return self._result_pic
