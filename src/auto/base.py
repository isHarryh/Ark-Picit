"""Shared types, exceptions and the device abstraction for the auto package."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Literal

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Point:
    """A point in the current coordinate space."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Region:
    """An axis-aligned rectangle in the current coordinate space."""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Point:
        """Return the center point of the region."""
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    def random_point(self, ratio: float = 1.0) -> Point:
        """Return a uniformly random point inside the centered *ratio* fraction of the region.

        The centered sub-region is padded by (1 - *ratio*) / 2 on every side;
        *ratio* must be in (0, 1].
        """
        if not 0 < ratio <= 1:
            raise ValueError(f"ratio must be in (0, 1], got {ratio}")
        pad_x = round((1 - ratio) * self.w / 2)
        pad_y = round((1 - ratio) * self.h / 2)
        inner_x = self.x + pad_x
        inner_y = self.y + pad_y
        inner_w = max(1, self.w - 2 * pad_x)
        inner_h = max(1, self.h - 2 * pad_y)
        return Point(
            random.randint(inner_x, inner_x + inner_w - 1),
            random.randint(inner_y, inner_y + inner_h - 1),
        )

    def contains(self, point: Point) -> bool:
        """Return whether *point* lies inside the region (half-open bounds)."""
        return self.x <= point.x < self.x + self.w and self.y <= point.y < self.y + self.h

    def intersect(self, other: Region) -> Region | None:
        """Return the intersection with *other*, or None when they are disjoint."""
        x = max(self.x, other.x)
        y = max(self.y, other.y)
        w = min(self.x + self.w, other.x + other.w) - x
        h = min(self.y + self.h, other.y + other.h) - y
        if w <= 0 or h <= 0:
            return None
        return Region(x, y, w, h)

    def clamp(self, width: int, height: int) -> Region:
        """Return the region clipped to a canvas of *width* by *height*."""
        clipped = self.intersect(Region(0, 0, width, height))
        return clipped if clipped is not None else Region(0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The best template match found in a screenshot."""

    point: Point  # top-left corner of the matched area
    score: float
    width: int
    height: int

    @property
    def center(self) -> Point:
        """Return the center point of the matched area."""
        return Point(self.point.x + self.width // 2, self.point.y + self.height // 2)


# ---------------------------------------------------------------------------
# Coordinate normalization
# ---------------------------------------------------------------------------

ScaleMode = Literal["short", "long"]


class AutoScale:
    """Map between a normalized coordinate space and native device pixels.

    The normalized space fixes the shorter (or longer) side of the screen at
    *target* pixels. Templates are captured directly in the normalized space
    (e.g. at 720p short side), so matching never scales them: instead the
    device screenshot is resized into the normalized space via
    :meth:`screen_normalized`. All user-facing coordinates live in the
    normalized space; the device operates in native pixels.
    """

    def __init__(self, width: int, height: int, *, mode: ScaleMode = "short", target: int = 720):
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid screen size: {width}x{height}")
        if target <= 0:
            raise ValueError(f"Invalid scale target: {target}")
        anchor = min(width, height) if mode == "short" else max(width, height)
        self.factor = anchor / target
        self._mode = mode
        self._target = target
        self._width = width
        self._height = height

    @property
    def normalized_size(self) -> tuple[int, int]:
        """Return the (width, height) of the normalized coordinate space."""
        return self.to_normalized(self._width), self.to_normalized(self._height)

    def __repr__(self) -> str:
        return f"AutoScale(mode={self._mode!r}, target={self._target}, factor={self.factor:g})"

    def to_native(self, value: int | float) -> int:
        """Convert a normalized value to native pixels."""
        return round(value * self.factor)

    def to_normalized(self, value: int) -> int:
        """Convert a native pixel value to the normalized space."""
        return round(value / self.factor)

    def point_native(self, point: Point) -> Point:
        """Convert a normalized point to native coordinates."""
        return Point(self.to_native(point.x), self.to_native(point.y))

    def point_normalized(self, point: Point) -> Point:
        """Convert a native point to normalized coordinates."""
        return Point(self.to_normalized(point.x), self.to_normalized(point.y))

    def region_native(self, region: Region) -> Region:
        """Convert a normalized region to native coordinates."""
        return Region(
            self.to_native(region.x),
            self.to_native(region.y),
            self.to_native(region.w),
            self.to_native(region.h),
        )

    def region_normalized(self, region: Region) -> Region:
        """Convert a native region to normalized coordinates."""
        return Region(
            self.to_normalized(region.x),
            self.to_normalized(region.y),
            self.to_normalized(region.w),
            self.to_normalized(region.h),
        )

    def screen_normalized(self, screen: np.ndarray) -> np.ndarray:
        """Return *screen* resized into the normalized coordinate space.

        The returned image is unchanged when the scaling factor is 1. The
        normalized space is where templates are authored, so templates are
        matched against this resized screenshot without any rescaling.
        """
        height, width = screen.shape[:2]
        target_width = self.to_normalized(width)
        target_height = self.to_normalized(height)
        if (target_width, target_height) == (width, height):
            return screen
        interpolation = cv2.INTER_AREA if self.factor > 1 else cv2.INTER_CUBIC
        return cv2.resize(screen, (target_width, target_height), interpolation=interpolation)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


class DeviceKind(Enum):
    """Supported device types."""

    WIN32 = "win32"
    ADB = "adb"


class Device(ABC):
    """Abstract interface for a controllable screen device.

    All coordinates are native device pixels and match the dimensions of
    :meth:`screenshot`. Implementations are not thread-safe.
    """

    kind: ClassVar[DeviceKind]

    @abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return the (width, height) of the coordinate space, matching screenshots."""

    @abstractmethod
    def screenshot(self) -> np.ndarray:
        """Capture the screen as a BGR image in native resolution."""

    @abstractmethod
    def click(self, x: int, y: int, *, hold_ms: int = 0) -> None:
        """Click at the given native coordinates, holding the button for *hold_ms* milliseconds."""

    @abstractmethod
    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int = 200,
        steps: int | None = None,
    ) -> None:
        """Drag from (x1, y1) to (x2, y2) over *duration_ms* milliseconds.

        *steps* overrides the interpolation step count; None chooses a
        sensible default.
        """

    def close(self) -> None:
        """Release any resources held by the device. Defaults to a no-op."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DeviceError(Exception):
    """Base error for device failures."""


class DeviceNotFoundError(DeviceError):
    """Raised when no matching window or device can be found."""


class TemplateNotFoundError(FileNotFoundError):
    """Raised when a template file is missing or cannot be read."""


class MatchTimeoutError(TimeoutError):
    """Raised when a waiting operation exceeds its timeout."""
