"""Device-independent image matching helpers."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.auto.base import MatchResult, Point, Region, TemplateNotFoundError

_TEMPLATE_CACHE_SIZE = 16


def load_template(path: str | Path) -> np.ndarray:
    """Load a template image from *path* as BGR, raising TemplateNotFoundError when unreadable.

    Loaded templates are cached with an LRU of :data:`_TEMPLATE_CACHE_SIZE`
    entries, keyed by the resolved absolute path. Callers must not mutate the
    returned array, as it is shared with future cache hits.
    """
    return _load_template_cached(str(Path(path).resolve()))


@lru_cache(maxsize=_TEMPLATE_CACHE_SIZE)
def _load_template_cached(resolved_path: str) -> np.ndarray:
    image = cv2.imread(resolved_path, cv2.IMREAD_COLOR)
    if image is None:
        raise TemplateNotFoundError(f"Cannot read template image: {resolved_path}")
    return image


def match_color(
    screen: np.ndarray,
    color: tuple[int, int, int],
    roi: Region | None = None,
    *,
    window_size: tuple[int, int] = (32, 32),
    tolerance: int = 10,
    coverage: float = 0.95,
) -> MatchResult | None:
    """Locate a solid *color* (BGR) swatch in *screen*, optionally within *roi*.

    The window of *window_size* pixels whose per-channel distance to *color*
    is within *tolerance* for the largest fraction of pixels is returned when
    that fraction reaches *coverage*. Returns None otherwise.
    """
    if screen.size == 0:
        return None
    window_width, window_height = window_size
    if window_width <= 0 or window_height <= 0:
        raise ValueError(f"Invalid window size: {window_size}")
    screen_height, screen_width = screen.shape[:2]
    if roi is not None:
        roi = roi.clamp(screen_width, screen_height)
        if roi.w == 0 or roi.h == 0:
            return None
        screen = screen[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
        screen_height, screen_width = screen.shape[:2]
    if window_width > screen_width or window_height > screen_height:
        return None
    target = np.array(color, dtype=np.int16)
    difference = np.abs(screen.astype(np.int16) - target).max(axis=2)
    mask = (difference <= tolerance).astype(np.float32)
    integral = cv2.integral(mask, sdepth=cv2.CV_32F)
    window_sums = (
        integral[window_height:, window_width:]
        - integral[window_height:, :-window_width]
        - integral[:-window_height, window_width:]
        + integral[:-window_height, :-window_width]
    )
    best_y, best_x = np.unravel_index(np.argmax(window_sums), window_sums.shape)
    best_score = float(window_sums[best_y, best_x] / (window_width * window_height))
    if best_score < coverage:
        return None
    offset_x = roi.x if roi is not None else 0
    offset_y = roi.y if roi is not None else 0
    return MatchResult(
        Point(int(best_x) + offset_x, int(best_y) + offset_y),
        best_score,
        window_width,
        window_height,
    )


def match_template(
    screen: np.ndarray,
    template: np.ndarray,
    roi: Region | None = None,
    *,
    threshold: float = 0.8,
) -> MatchResult | None:
    """Find the best *template* match in *screen*, optionally restricted to *roi*.

    Returns None when the template is larger than the search area, when the
    template has no variance (TM_CCOEFF_NORMED is undefined for constant
    content, e.g. pure black screens), or when the best normalized
    correlation score is below *threshold*.
    """
    if template.size == 0 or screen.size == 0:
        return None
    if float(np.std(template)) < 1e-6:
        return None
    screen_height, screen_width = screen.shape[:2]
    template_height, template_width = template.shape[:2]
    if roi is not None:
        roi = roi.clamp(screen_width, screen_height)
        if roi.w == 0 or roi.h == 0:
            return None
        screen = screen[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
        screen_height, screen_width = screen.shape[:2]
    if template_width > screen_width or template_height > screen_height:
        return None
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_score, _, max_loc = cv2.minMaxLoc(result)
    if not math.isfinite(max_score) or max_score < threshold:
        return None
    offset_x = roi.x if roi is not None else 0
    offset_y = roi.y if roi is not None else 0
    return MatchResult(
        Point(max_loc[0] + offset_x, max_loc[1] + offset_y),
        float(max_score),
        template_width,
        template_height,
    )
