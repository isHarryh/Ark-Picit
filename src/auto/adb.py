"""Android device implementation driven by the adb command-line tool."""

from __future__ import annotations

import logging
import re
import subprocess
from typing import ClassVar

import cv2
import numpy as np

from src.auto.base import Device, DeviceError, DeviceKind, DeviceNotFoundError

logger = logging.getLogger(__name__)

_ADB_CMD_TIMEOUT_S = 30
_DEVICE_LINE = re.compile(r"^([^\s]+)\s+device$")


def _run_adb(adb_path: str, args: list[str], *, timeout: float = _ADB_CMD_TIMEOUT_S) -> bytes:
    """Run an adb command, raising DeviceError on failure."""
    try:
        result = subprocess.run([adb_path, *args], capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DeviceNotFoundError(f"adb executable not found: {adb_path}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DeviceError(f"adb command timed out: {adb_path} {' '.join(args)}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise DeviceError(f"adb command failed ({result.returncode}): {stderr or 'no error output'}")
    return result.stdout


def list_devices(adb_path: str = "adb") -> list[str]:
    """Return the serials of all connected adb devices (device state)."""
    output = _run_adb(adb_path, ["devices"]).decode("utf-8", errors="replace")
    serials: list[str] = []
    for line in output.splitlines():
        match = _DEVICE_LINE.match(line.strip())
        if match:
            serials.append(match.group(1))
    return serials


class AdbDevice(Device):
    """Control an Android device (real or emulator) through the adb tool.

    Coordinates are physical screen pixels as produced by ``screencap``.
    """

    kind: ClassVar[DeviceKind] = DeviceKind.ADB

    def __init__(self, serial: str | None = None, *, adb_path: str = "adb"):
        self._adb_path = adb_path
        self._screen_size: tuple[int, int] | None = None
        serials = list_devices(adb_path)
        if serial is None:
            if not serials:
                raise DeviceNotFoundError("No adb device found")
            if len(serials) > 1:
                raise DeviceNotFoundError(
                    f"Multiple adb devices found ({', '.join(serials)}); specify a serial"
                )
            serial = serials[0]
        if serial not in serials:
            _run_adb(adb_path, ["connect", serial])
            if serial not in list_devices(adb_path):
                raise DeviceNotFoundError(f"Unable to connect to adb device: {serial}")
        self._serial = serial
        logger.info("Connected to adb device %s", self._serial)

    def _shell(self, args: list[str]) -> bytes:
        return _run_adb(self._adb_path, ["-s", self._serial, "shell", *args])

    def screen_size(self) -> tuple[int, int]:
        """Return the physical screen size, derived from the first screenshot."""
        if self._screen_size is None:
            image = self.screenshot()
            self._screen_size = (image.shape[1], image.shape[0])
        return self._screen_size

    def screenshot(self) -> np.ndarray:
        """Capture the device screen as a BGR image via ``screencap``."""
        png = _run_adb(self._adb_path, ["-s", self._serial, "exec-out", "screencap", "-p"])
        image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise DeviceError("Failed to decode screencap output")
        return image

    def click(self, x: int, y: int, *, hold_ms: int = 0) -> None:
        """Tap the screen at (x, y).

        *hold_ms* is ignored; the Android ``input tap`` command has its own
        internal press duration.
        """
        self._shell(["input", "tap", str(x), str(y)])

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
        """Swipe between two points over *duration_ms* milliseconds.

        *steps* is ignored; the Android ``input swipe`` command interpolates
        internally.
        """
        self._shell(
            ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
        )
