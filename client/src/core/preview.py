"""Generate 1:1 PNG preview images from ArkPic paintings.

Since all pixels always have a valid color (no empty pixels), the preview
is fully opaque.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.core.color import hex_to_rgb
from src.core.pic import ArkPic


def generate_preview(pic: ArkPic) -> bytes:
    """Render a 1:1 (native resolution) PNG of *pic*.

    Returns PNG file bytes. The image is fully opaque (no transparency).
    """
    w, h = pic.rule.width, pic.rule.height
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    flat = pic.flat
    colors = pic.rule.colors

    for y in range(h):
        for x in range(w):
            cid = flat[y * w + x]
            r, g, b = hex_to_rgb(colors[cid - 1])
            rgba[y, x] = [r, g, b, 255]

    # OpenCV expects BGRA
    bgra = rgba[:, :, [2, 1, 0, 3]]
    ok, buf = cv2.imencode(".png", bgra)
    if not ok:
        raise RuntimeError("Failed to encode PNG preview")
    return buf.tobytes()
