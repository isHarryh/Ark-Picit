"""High-level automation facade combining a device with image matching.

The :class:`Automator` operates entirely in a normalized coordinate space
(fixed short or long side, see :class:`AutoScale`): regions, ROIs, templates
and returned points are all normalized, while the underlying device receives
native pixels. Business logic uses this facade as its single entry point.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import numpy as np

from src.auto.base import (
    AutoScale,
    Device,
    DeviceKind,
    MatchResult,
    MatchTimeoutError,
    Point,
    Region,
)
from src.auto.vision import load_template, match_color, match_template
from src.utils.paths import ASSETS_DIR

logger = logging.getLogger(__name__)

TemplateSource = str | Path | np.ndarray
T = TypeVar("T")

_DONE = object()


def _as_template(source: TemplateSource) -> np.ndarray:
    """Load a template from a path, or pass through an already-loaded array."""
    if isinstance(source, np.ndarray):
        return source
    return load_template(source)


def _template_name(template: TemplateSource) -> str:
    return str(template) if not isinstance(template, np.ndarray) else "<loaded template>"


class Automator:
    """Coordinate-normalized facade over a :class:`Device`.

    All regions, ROIs, templates and returned points live in the normalized
    space defined by *scale_target* and *scale_mode*; the device receives
    native pixels. Screenshots are rate-limited by *fps_limit*: calls that
    arrive sooner than the implied interval reuse the previous frame.
    """

    def __init__(
        self,
        device: Device,
        *,
        scale_target: int = 720,
        scale_mode: str = "short",
        fps_limit: float = 10.0,
    ):
        self._device = device
        width, height = device.screen_size()
        self._scale = AutoScale(width, height, mode=scale_mode, target=scale_target)
        self._fps_limit = fps_limit
        self._last_screenshot: np.ndarray | None = None
        self._last_screenshot_time = 0.0
        logger.info(
            "Automator ready: kind=%s size=%dx%d %s",
            self.kind.value,
            width,
            height,
            self._scale,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device(self) -> Device:
        """Return the underlying device."""
        return self._device

    @property
    def kind(self) -> DeviceKind:
        """Return the device kind, for type-specific template or logic selection."""
        return self._device.kind

    @property
    def scale(self) -> AutoScale:
        """Return the normalization mapping in use."""
        return self._scale

    @property
    def screen_size(self) -> tuple[int, int]:
        """Return the (width, height) of the normalized coordinate space."""
        return self._scale.normalized_size

    @property
    def template_dir(self) -> Path:
        """Return the template directory matching the current device kind.

        Templates are authored per normalized-space variant: the Win32
        window uses the 720p short-side set, adb emulators use the 240dpi
        set. Template selection therefore follows the connected device
        automatically.
        """
        subdir = "adb240dpi" if self.kind is DeviceKind.ADB else "win720p"
        return ASSETS_DIR / "images" / subdir

    def template(self, name: str) -> Path:
        """Return the device-specific path of a named template file."""
        return self.template_dir / name

    # ------------------------------------------------------------------
    # Atomic operations
    # ------------------------------------------------------------------

    def screenshot(self) -> np.ndarray:
        """Return a screenshot in native resolution, honoring the fps limit.

        When called sooner than the interval implied by *fps_limit*, the
        previously captured screenshot is returned without touching the
        device (no foreground switch, cursor parking or real capture).
        A non-positive *fps_limit* disables the caching entirely.
        """
        interval = 1.0 / self._fps_limit if self._fps_limit > 0 else 0.0
        now = time.monotonic()
        if self._last_screenshot is not None and now - self._last_screenshot_time < interval:
            return self._last_screenshot
        self._last_screenshot = self._device.screenshot()
        self._last_screenshot_time = now
        return self._last_screenshot

    def click_region(
        self,
        region: Region,
        *,
        random_ratio: float = 0.6,
        hold_ms: int = 0,
    ) -> Point:
        """Click a uniformly random point inside the centered *random_ratio* fraction of *region*.

        Returns the actual normalized point.
        """
        target = self._scale.region_native(region).random_point(random_ratio)
        self._device.click(target.x, target.y, hold_ms=hold_ms)
        return self._scale.point_normalized(target)

    def drag_point(
        self,
        start: Point,
        end: Point,
        *,
        duration_ms: int = 200,
        steps: int | None = None,
    ) -> None:
        """Drag between two exact points without randomization."""
        native_start = self._scale.point_native(start)
        native_end = self._scale.point_native(end)
        self._device.drag(
            native_start.x,
            native_start.y,
            native_end.x,
            native_end.y,
            duration_ms=duration_ms,
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Vision operations
    # ------------------------------------------------------------------

    def _screenshot_normalized(self) -> np.ndarray:
        """Return the latest screenshot resized into the normalized coordinate space."""
        return self._scale.screen_normalized(self.screenshot())

    def find_template(
        self,
        template: TemplateSource,
        roi: Region | None = None,
        *,
        threshold: float = 0.8,
    ) -> MatchResult | None:
        """Match *template* once against the latest screenshot, returning None on no hit.

        The device screenshot is resized into the normalized coordinate space
        and *template* is matched as-is: templates are captured at the
        normalized resolution (e.g. 720p short side), so they are never
        rescaled.
        """
        return match_template(
            self._screenshot_normalized(), _as_template(template), roi, threshold=threshold
        )

    def find_color(
        self,
        color: tuple[int, int, int],
        roi: Region | None = None,
        *,
        window_size: tuple[int, int] = (32, 32),
        tolerance: int = 10,
        coverage: float = 0.95,
    ) -> MatchResult | None:
        """Locate a solid *color* (BGR) swatch on the normalized screenshot.

        Searches a *window_size* window whose pixels are within *tolerance*
        of *color* for at least *coverage* of its area, restricted to *roi*.
        """
        return match_color(
            self._screenshot_normalized(),
            color,
            roi,
            window_size=window_size,
            tolerance=tolerance,
            coverage=coverage,
        )

    def wait_template(
        self,
        template: TemplateSource,
        roi: Region | None = None,
        *,
        threshold: float = 0.8,
        timeout_ms: int = 10000,
        interval_ms: int = 500,
    ) -> MatchResult:
        """Poll until *template* appears, raising MatchTimeoutError on timeout."""
        result = self._wait_until(
            lambda: self.find_template(template, roi, threshold=threshold),
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )
        if result is None:
            raise MatchTimeoutError(
                f"Template not found within {timeout_ms} ms: {_template_name(template)}"
            )
        return result

    def wait_until_gone(
        self,
        template: TemplateSource,
        roi: Region | None = None,
        *,
        threshold: float = 0.8,
        timeout_ms: int = 10000,
        interval_ms: int = 500,
    ) -> None:
        """Poll until *template* disappears, raising MatchTimeoutError on timeout."""
        result = self._wait_until(
            lambda: _DONE if self.find_template(template, roi, threshold=threshold) is None else None,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )
        if result is None:
            raise MatchTimeoutError(
                f"Template still visible after {timeout_ms} ms: {_template_name(template)}"
            )

    def wait_stable(
        self,
        roi: Region | None = None,
        *,
        quiet_ms: int = 500,
        timeout_ms: int = 10000,
        interval_ms: int = 100,
    ) -> None:
        """Wait until the (optionally *roi*-restricted) screen is pixel-identical over *quiet_ms*."""
        native_roi = self._scale.region_native(roi) if roi is not None else None

        def _crop() -> np.ndarray:
            screen = self.screenshot()
            if native_roi is None:
                return screen
            roi_clamped = native_roi.clamp(screen.shape[1], screen.shape[0])
            return screen[roi_clamped.y : roi_clamped.y + roi_clamped.h, roi_clamped.x : roi_clamped.x + roi_clamped.w]

        def _is_stable() -> bool:
            first = _crop()
            time.sleep(quiet_ms / 1000)
            return np.array_equal(first, _crop())

        result = self._wait_until(
            lambda: _DONE if _is_stable() else None,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )
        if result is None:
            raise MatchTimeoutError(f"Screen did not become stable within {timeout_ms} ms")

    # ------------------------------------------------------------------
    # Composite operations
    # ------------------------------------------------------------------

    def click_match(
        self,
        result: MatchResult,
        *,
        random_ratio: float = 0.6,
        hold_ms: int = 0,
    ) -> Point:
        """Click a random point inside the centered *random_ratio* fraction of the match box."""
        box = Region(result.point.x, result.point.y, result.width, result.height)
        return self.click_region(box, random_ratio=random_ratio, hold_ms=hold_ms)

    def click_template(
        self,
        template: TemplateSource,
        roi: Region | None = None,
        *,
        threshold: float = 0.8,
        timeout_ms: int = 10000,
        interval_ms: int = 500,
        random_ratio: float = 0.6,
        hold_ms: int = 0,
    ) -> Point:
        """Wait for *template* to appear, then click a random point in its centered box."""
        result = self.wait_template(
            template,
            roi,
            threshold=threshold,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )
        return self.click_match(result, random_ratio=random_ratio, hold_ms=hold_ms)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _wait_until(
        self,
        probe: Callable[[], T | None],
        *,
        timeout_ms: int,
        interval_ms: int,
    ) -> T | None:
        """Poll *probe* until it returns a non-None value or the timeout elapses."""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            value = probe()
            if value is not None:
                return value
            if time.monotonic() >= deadline:
                return None
            time.sleep(interval_ms / 1000)
