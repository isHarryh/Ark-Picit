"""Read image data from the system clipboard."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def clipboard_has_image() -> bool:
    """Return True if the clipboard currently holds an image."""
    clipboard = QApplication.clipboard()
    return clipboard is not None and not clipboard.image().isNull()


def get_clipboard_image_bgr() -> np.ndarray | None:
    """Return clipboard image as BGR uint8 array, or None if unavailable."""
    clipboard = QApplication.clipboard()
    if clipboard is None:
        return None
    qimg: QImage = clipboard.image()
    if qimg.isNull():
        return None
    return _qimage_to_bgr(qimg)


def _qimage_to_bgr(qimg: QImage) -> np.ndarray:
    """Convert a QImage to an OpenCV BCR uint8 array."""
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4)
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
