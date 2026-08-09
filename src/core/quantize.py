"""Quantize a source image to an ArkPic using a rule's palette.

Two sampling modes:
- ``nearest``: pure nearest-neighbor downscale, then snap each pixel.
- ``anti_alias``: area-weighted downscale (blends subpixels), then snap.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.core.color import hex_to_rgb
from src.core.pic import ArkPic
from src.core.rule import ArkPicRule


def _build_palette_rgb(colors: list[str]) -> np.ndarray:
    """Return an (N, 3) float32 RGB array."""
    return np.array([hex_to_rgb(c) for c in colors], dtype=np.float32)


def _snap_to_palette(pixels: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Snap each pixel to the nearest palette color.

    Args:
        pixels: (H, W, 3) float32 RGB
        palette: (N, 3) float32 RGB

    Returns:
        (H, W) int32 array of 1-based palette indices
    """
    h, w, _ = pixels.shape
    flat = pixels.reshape(-1, 3)  # (H*W, 3)
    # Compute squared distances to each palette color
    # Use broadcasting: (H*W, 1, 3) - (1, N, 3) -> (H*W, N, 3) -> sum -> (H*W, N)
    dists = np.sum((flat[:, None, :] - palette[None, :, :]) ** 2, axis=2)
    best = np.argmin(dists, axis=1).astype(np.int32)  # 0-based
    return (best + 1).reshape(h, w)  # 1-based


def quantize_image(
    image_bgr: np.ndarray,
    rule: ArkPicRule,
    anti_alias: bool = True,
) -> ArkPic:
    """Quantize a BGR image to an ArkPic.

    Args:
        image_bgr: Input image in BGR uint8 format (OpenCV convention).
        rule: The rule to use for dimensions and palette.
        anti_alias: If True, use area interpolation for downscaling (smoother).
                     If False, use nearest-neighbor (sharper, more pixelated).

    Returns:
        An ArkPic with each pixel assigned to the nearest palette color.
    """
    target_w, target_h = rule.width, rule.height

    interp = cv2.INTER_AREA if anti_alias else cv2.INTER_NEAREST
    resized = cv2.resize(image_bgr, (target_w, target_h), interpolation=interp)

    # Convert BGR -> RGB
    resized_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)

    palette = _build_palette_rgb(rule.colors)
    ids_grid = _snap_to_palette(resized_rgb, palette)

    pic = ArkPic(rule)
    pic.fill_flat(ids_grid.flatten().tolist())
    return pic


def render_preview_bgr(pic: ArkPic, scale: int = 16) -> np.ndarray:
    """Upscale an ArkPic to a viewable BGR image for display."""
    w, h = pic.rule.width, pic.rule.height
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    flat = pic.flat
    for y in range(h):
        for x in range(w):
            cid = flat[y * w + x]
            r, g, b = hex_to_rgb(pic.rule.colors[cid - 1])
            canvas[y, x] = [b, g, r]

    return cv2.resize(
        canvas, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_NEAREST,
    )
