"""Minimal game automation toolkit: devices, matching and a normalized facade.

The package provides a :class:`Device` abstraction (Win32 and adb
implementations), device-independent template matching (:mod:`src.auto.vision`)
and a coordinate-normalized :class:`Automator` facade for business logic.
"""

from src.auto.adb import AdbDevice, list_devices
from src.auto.automator import Automator
from src.auto.base import (
    AutoScale,
    Device,
    DeviceError,
    DeviceKind,
    DeviceNotFoundError,
    MatchResult,
    MatchTimeoutError,
    Point,
    Region,
    TemplateNotFoundError,
)
from src.auto.vision import load_template, match_template
from src.auto.win32 import Win32Device, WindowInfo, list_windows

__all__ = [
    "AdbDevice",
    "AutoScale",
    "Automator",
    "Device",
    "DeviceError",
    "DeviceKind",
    "DeviceNotFoundError",
    "MatchResult",
    "MatchTimeoutError",
    "Point",
    "Region",
    "TemplateNotFoundError",
    "WindowInfo",
    "Win32Device",
    "create_device",
    "list_devices",
    "list_windows",
    "load_template",
    "match_template",
]


def create_device(kind: str, **kwargs) -> Device:
    """Create a device by kind name (``"win32"`` or ``"adb"``)."""
    if kind == DeviceKind.WIN32.value:
        return Win32Device(**kwargs)
    if kind == DeviceKind.ADB.value:
        return AdbDevice(**kwargs)
    raise ValueError(f"Unknown device kind: {kind}")
