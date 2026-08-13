"""Win32 device implementation using the Windows user32/gdi32 APIs via ctypes.

Two operation modes are supported:

- ``post`` (default): background control through ``PostMessage`` message
  injection and ``PrintWindow`` screen capture. The target window may be
  occluded or minimized.
- ``send``: foreground control through ``SendInput`` and ``BitBlt`` capture.
  The target window must be visible, but games usually accept these inputs
  more reliably.

All coordinates are client-area pixels, matching the captured screenshots.
The host process is expected to be DPI aware (PySide6 sets this up by
default) so that pixel values are physical pixels.
"""

from __future__ import annotations

import ctypes
import logging
import math
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from src.auto.base import Device, DeviceError, DeviceKind, DeviceNotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """A discoverable top-level window."""

    hwnd: int
    title: str
    class_name: str
    visible: bool


def list_windows(
    title_regex: str | None = None,
    class_regex: str | None = None,
) -> list[WindowInfo]:
    """Return all visible top-level windows matching the optional regexes."""
    title_pattern = re.compile(title_regex) if title_regex else None
    class_pattern = re.compile(class_regex) if class_regex else None
    found: list[WindowInfo] = []

    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        class_name = class_buffer.value
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = title_buffer.value
        visible = bool(user32.IsWindowVisible(hwnd))
        if title_pattern is not None and not title_pattern.search(title):
            return True
        if class_pattern is not None and not class_pattern.search(class_name):
            return True
        found.append(WindowInfo(hwnd, title, class_name, visible))
        return True

    user32.EnumWindows(EnumWindowsProc(_enum_proc), 0)
    return found

# ---------------------------------------------------------------------------
# Win32 declarations
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

SW_RESTORE = 9
_CURSOR_SETTLE_MS = 0.1  # settle time after parking the cursor before capture

_MAX_DRAG_STEPS = 200
_MIN_DRAG_STEP_DISTANCE = 8  # pixels


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("input", _INPUT_UNION)]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, wintypes.LPRECT]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, wintypes.LPRECT]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, wintypes.LPPOINT]
user32.ClientToScreen.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


def _find_window(title_regex: str | None, class_regex: str | None) -> int:
    """Return the hwnd of the first visible top-level window matching both regexes."""
    matches = list_windows(title_regex, class_regex)
    if not matches:
        raise DeviceNotFoundError(
            f"No window matches title={title_regex!r} class={class_regex!r}"
        )
    return matches[0].hwnd


def _read_bitmap(mem_dc: int, bitmap: int, width: int, height: int) -> np.ndarray:
    """Read a 32-bit BGRX bitmap into a BGR numpy array (top-down)."""
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0  # BI_RGB
    buffer = ctypes.create_string_buffer(width * height * 4)
    rows = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
    if rows != height:
        raise DeviceError(f"GetDIBits returned {rows} of {height} rows")
    image = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    return image[:, :, :3].copy()


def _capture_window(hwnd: int, *, try_print: bool) -> np.ndarray:
    """Capture the client area of *hwnd* as a BGR image.

    With *try_print* the window is rendered through ``PrintWindow`` first and
    ``BitBlt`` is used as a fallback when the result is completely black.
    """
    window_rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
        raise DeviceError(f"GetWindowRect failed: error {ctypes.get_last_error()}")
    window_width = window_rect.right - window_rect.left
    window_height = window_rect.bottom - window_rect.top

    client_rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
        raise DeviceError(f"GetClientRect failed: error {ctypes.get_last_error()}")
    client_width = client_rect.right
    client_height = client_rect.bottom
    if client_width <= 0 or client_height <= 0:
        raise DeviceError(f"Window has an empty client area: {client_width}x{client_height}")

    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise DeviceError(f"ClientToScreen failed: error {ctypes.get_last_error()}")
    offset_x = origin.x - window_rect.left
    offset_y = origin.y - window_rect.top

    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        raise DeviceError(f"GetWindowDC failed: error {ctypes.get_last_error()}")
    try:
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, window_width, window_height)
        if not mem_dc or not bitmap:
            raise DeviceError("Failed to create compatible DC/bitmap")
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
        try:
            if try_print:
                user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
            else:
                gdi32.BitBlt(mem_dc, 0, 0, window_width, window_height, hwnd_dc, 0, 0, SRCCOPY)
            image = _read_bitmap(mem_dc, bitmap, window_width, window_height)
        finally:
            gdi32.SelectObject(mem_dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
    finally:
        user32.ReleaseDC(hwnd, hwnd_dc)

    client = image[offset_y : offset_y + client_height, offset_x : offset_x + client_width]
    if client.std() == 0 and try_print:
        logger.warning("PrintWindow produced a blank capture, falling back to BitBlt")
        return _capture_window(hwnd, try_print=False)
    return client.copy()


def _make_lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def _drag_steps(x1: int, y1: int, x2: int, y2: int, duration_ms: int, steps: int | None) -> int:
    """Return the interpolation step count for a drag."""
    if steps is not None:
        return max(1, steps)
    distance = int(math.hypot(x2 - x1, y2 - y1))
    return min(_MAX_DRAG_STEPS, max(1, distance // _MIN_DRAG_STEP_DISTANCE))


def _set_cursor_pos(hwnd: int, x: int, y: int) -> None:
    """Move the real cursor to client point (x, y), retrying transient failures.

    Games that read ``GetCursorPos`` follow the real cursor, so it must sit
    on the exact pixel that a posted or sent click/drag targets.
    SetCursorPos can briefly fail while the desktop changes input state; a
    FALSE return without a set error means the cursor already sits on the
    target, which is success.
    """
    point = wintypes.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise DeviceError(f"ClientToScreen failed: error {ctypes.get_last_error()}")
    last_error = 0
    for _ in range(5):
        if user32.SetCursorPos(point.x, point.y):
            return
        last_error = ctypes.get_last_error()
        if last_error == 0:
            return  # the cursor already sits at the target
        time.sleep(0.05)
    raise DeviceError(f"SetCursorPos failed: error {last_error}")


def _bring_to_foreground(hwnd: int) -> None:
    """Restore and activate the window so it can receive real input."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def _post_click(hwnd: int, x: int, y: int, hold_ms: int = 0) -> None:
    _set_cursor_pos(hwnd, x, y)
    lparam = _make_lparam(x, y)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    if hold_ms > 0:
        time.sleep(hold_ms / 1000)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def _post_drag(
    hwnd: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int,
    steps: int | None,
) -> None:
    steps = _drag_steps(x1, y1, x2, y2, duration_ms, steps)
    _set_cursor_pos(hwnd, x1, y1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _make_lparam(x1, y1))
    interval = duration_ms / steps / 1000
    for index in range(1, steps + 1):
        x = x1 + (x2 - x1) * index // steps
        y = y1 + (y2 - y1) * index // steps
        _set_cursor_pos(hwnd, x, y)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, _make_lparam(x, y))
        time.sleep(interval)
    _set_cursor_pos(hwnd, x2, y2)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _make_lparam(x2, y2))


def _send_mouse_event(flags: int) -> None:
    event = INPUT()
    event.type = INPUT_MOUSE
    event.input.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        raise DeviceError(f"SendInput failed: error {ctypes.get_last_error()}")


def _send_click(hwnd: int, x: int, y: int, hold_ms: int = 0) -> None:
    _set_cursor_pos(hwnd, x, y)
    _send_mouse_event(MOUSEEVENTF_LEFTDOWN)
    time.sleep(max(0.03, hold_ms / 1000))
    _send_mouse_event(MOUSEEVENTF_LEFTUP)


def _send_drag(
    hwnd: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int,
    steps: int | None,
) -> None:
    steps = _drag_steps(x1, y1, x2, y2, duration_ms, steps)
    _set_cursor_pos(hwnd, x1, y1)
    _send_mouse_event(MOUSEEVENTF_LEFTDOWN)
    interval = duration_ms / steps / 1000
    for index in range(1, steps + 1):
        x = x1 + (x2 - x1) * index // steps
        y = y1 + (y2 - y1) * index // steps
        _set_cursor_pos(hwnd, x, y)
        time.sleep(interval)
    _set_cursor_pos(hwnd, x2, y2)
    _send_mouse_event(MOUSEEVENTF_LEFTUP)


class Win32Device(Device):
    """Control a Windows window in ``post`` (background) or ``send`` (foreground) mode."""

    kind: ClassVar[DeviceKind] = DeviceKind.WIN32

    def __init__(
        self,
        title_regex: str | None = None,
        class_regex: str | None = None,
        *,
        mode: Literal["post", "send"] = "post",
        connect: bool = True,
    ):
        if title_regex is None and class_regex is None:
            raise ValueError("Provide at least one of title_regex or class_regex")
        if mode not in ("post", "send"):
            raise ValueError(f"Invalid mode: {mode!r}")
        self._mode = mode
        self._screen_size: tuple[int, int] | None = None
        self._hwnd = _find_window(title_regex, class_regex) if connect else 0
        logger.info(
            "Win32 device ready: mode=%s hwnd=%s",
            mode,
            hex(self._hwnd) if self._hwnd else "not connected",
        )

    def _check_connected(self) -> int:
        if not self._hwnd:
            raise DeviceError("Win32 device is not connected")
        if not user32.IsWindow(self._hwnd):
            raise DeviceError(f"Window handle {self._hwnd:#x} is no longer valid")
        return self._hwnd

    def screen_size(self) -> tuple[int, int]:
        """Return the client area size of the target window."""
        if self._screen_size is None:
            rect = wintypes.RECT()
            if not user32.GetClientRect(self._check_connected(), ctypes.byref(rect)):
                raise DeviceError(f"GetClientRect failed: error {ctypes.get_last_error()}")
            self._screen_size = (rect.right, rect.bottom)
        return self._screen_size

    def screenshot(self) -> np.ndarray:
        """Bring the window to the foreground, park the cursor, then capture its client area.

        The window is activated first; the real cursor is moved to the
        client bottom-right corner and the capture waits :data:`_CURSOR_SETTLE_MS`
        so hover states do not distort the image.
        """
        hwnd = self._check_connected()
        _bring_to_foreground(hwnd)
        width, height = self.screen_size()
        # Park the real cursor at the client bottom-right corner so hover
        # states do not distort the upcoming screenshot.
        _set_cursor_pos(hwnd, width - 1, height - 1)
        time.sleep(_CURSOR_SETTLE_MS)
        return _capture_window(hwnd, try_print=self._mode == "post")

    def click(self, x: int, y: int, *, hold_ms: int = 0) -> None:
        """Bring the window to the foreground, then click at client coordinates (x, y).

        *hold_ms* keeps the button pressed for that long before releasing.
        """
        hwnd = self._check_connected()
        _bring_to_foreground(hwnd)
        if self._mode == "post":
            _post_click(hwnd, x, y, hold_ms)
        else:
            _send_click(hwnd, x, y, hold_ms)

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
        """Bring the window to the foreground, then drag between two client-coordinate points."""
        hwnd = self._check_connected()
        _bring_to_foreground(hwnd)
        if self._mode == "post":
            _post_drag(hwnd, x1, y1, x2, y2, duration_ms, steps)
        else:
            _send_drag(hwnd, x1, y1, x2, y2, duration_ms, steps)

    def close(self) -> None:
        """Release the window handle."""
        self._hwnd = 0
