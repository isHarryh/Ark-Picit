"""Quantize a source image to an ArkPic using a rule's palette.

Sampling modes control how the source is downscaled to the rule size:
``nearest`` (INTER_NEAREST), ``bilinear`` (INTER_LINEAR), ``bicubic``
(INTER_CUBIC) and ``area`` (INTER_AREA, used when reading in-game canvases).

Color matching modes control how each downscaled pixel is snapped to the
palette: linear (L1) or squared (L2) error in RGB space, by grayscale
luminance, or by majority voting (``voting``) which replaces downscaling
entirely: each target pixel polls the exact pixel values in its source
block and wins the most frequent value (ties are averaged).
"""

from __future__ import annotations

import cv2
import numpy as np

from src.core.color import hex_to_rgb
from src.core.pic import ArkPic
from src.core.rule import ArkPicRule

#: Downscale interpolation for each sampling mode.
SAMPLING_INTERP = {
    "nearest": cv2.INTER_NEAREST,
    "bilinear": cv2.INTER_LINEAR,
    "bicubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
}

#: Supported color matching modes (UI labels map to these keys).
COLOR_MATCH_MODES = (
    "rgb_linear",
    "rgb_squared",
    "grayscale",
    "voting",
)

_GRAY_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _build_palette_rgb(colors: list[str]) -> np.ndarray:
    """Return an (N, 3) float32 RGB array."""
    return np.array([hex_to_rgb(c) for c in colors], dtype=np.float32)


def _snap_to_palette(pixels: np.ndarray, palette: np.ndarray, mode: str) -> np.ndarray:
    """Snap each pixel to the nearest palette color using *mode*.

    Args:
        pixels: (H, W, 3) float32 RGB
        palette: (N, 3) float32 RGB
        mode: One of :data:`COLOR_MATCH_MODES` (not ``voting``).

    Returns:
        (H, W) int32 array of 1-based palette indices
    """
    h, w, _ = pixels.shape
    flat = pixels.reshape(-1, 3)  # (H*W, 3)

    if mode == "grayscale":
        gray_pix = flat @ _GRAY_WEIGHTS  # (H*W,)
        gray_pal = palette @ _GRAY_WEIGHTS  # (N,)
        dists = np.abs(gray_pix[:, None] - gray_pal[None, :])
    else:  # rgb_linear / rgb_squared
        diff = flat[:, None, :] - palette[None, :, :]
        dists = np.abs(diff)
        if mode.endswith("squared"):
            dists = dists**2
        dists = dists.sum(axis=2)

    best = np.argmin(dists, axis=1).astype(np.int32)  # 0-based
    return (best + 1).reshape(h, w)  # 1-based


def _voting_downscale(image_rgb: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Majority-vote the exact colors of each target block.

    Each target pixel polls the pixel values of its source block; the most
    frequent value wins, and when several values tie for first place their
    arithmetic mean is used. Pixel values must match exactly to count.
    """
    h, w, _ = image_rgb.shape
    result = np.empty((target_h, target_w, 3), dtype=np.float32)
    for ty in range(target_h):
        y0 = ty * h // target_h
        y1 = max(y0 + 1, (ty + 1) * h // target_h)
        for tx in range(target_w):
            x0 = tx * w // target_w
            x1 = max(x0 + 1, (tx + 1) * w // target_w)
            block = image_rgb[y0:y1, x0:x1].reshape(-1, 3)
            unique, counts = np.unique(block, axis=0, return_counts=True)
            winners = unique[counts == counts.max()]
            result[ty, tx] = winners.mean(axis=0)
    return result


def quantize_image(
    image_bgr: np.ndarray,
    rule: ArkPicRule,
    sampling: str = "nearest",
    color_match: str = "rgb_linear",
) -> ArkPic:
    """Quantize a BGR image to an ArkPic.

    Args:
        image_bgr: Input image in BGR uint8 format (OpenCV convention).
        rule: The rule to use for dimensions and palette.
        sampling: One of :data:`SAMPLING_INTERP` keys. Ignored when
            *color_match* is ``voting``.
        color_match: One of :data:`COLOR_MATCH_MODES`. The ``voting`` mode
            counts exact colors per target block instead of resampling;
            its result is snapped to the palette with RGB squared error.

    Returns:
        An ArkPic with each pixel assigned to the nearest palette color.
    """
    target_w, target_h = rule.width, rule.height

    if color_match == "voting":
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        voted = _voting_downscale(image_rgb, target_w, target_h)
        ids_grid = _snap_to_palette(voted, _build_palette_rgb(rule.colors), "rgb_squared")
    else:
        resized = cv2.resize(
            image_bgr, (target_w, target_h), interpolation=SAMPLING_INTERP[sampling]
        )
        resized_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
        ids_grid = _snap_to_palette(resized_rgb, _build_palette_rgb(rule.colors), color_match)

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
