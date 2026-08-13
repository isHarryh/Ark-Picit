"""Runtime device selection for the automation toolkit."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from src.auto import (
    AdbDevice,
    Device,
    DeviceKind,
    DeviceNotFoundError,
    Win32Device,
    WindowInfo,
    find_adb_executable,
    list_devices,
    list_windows,
    probe_emulators,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeviceCandidate:
    """A connectable device found during discovery."""

    kind: DeviceKind
    label: str
    params: dict = field(default_factory=dict)
    score: int = 0


# Independent criteria that each add one point to a window's recommendation score.
_GAME_TITLE_KEYWORDS = ("明日方舟", "arknights")


def _score_window(window: WindowInfo) -> int:
    """Return how strongly *window* looks like the game window (0-4)."""
    score = 0
    if window.class_name == "UnityWndClass":
        score += 1
    lowered = window.title.lower()
    if any(kw in lowered for kw in _GAME_TITLE_KEYWORDS):
        score += 1
    if lowered in _GAME_TITLE_KEYWORDS:
        score += 1
    if window.visible:
        score += 1
    return score


def _discover_all(adb_path: str) -> list[DeviceCandidate]:
    """Return all connectable candidates: visible windows first, then adb devices."""
    candidates: list[DeviceCandidate] = []
    for window in list_windows():
        if not window.title:
            continue
        score = _score_window(window)
        if score < 1:
            continue
        candidates.append(
            DeviceCandidate(
                kind=DeviceKind.WIN32,
                label=window.title,
                params={"title_regex": window.title, "class_regex": window.class_name},
                score=score,
            )
        )
    # Emulators only appear in `adb devices` after an explicit connect, so
    # probe the well-known local ports first, then list the actual states.
    probe_emulators(adb_path)
    for info in list_devices(adb_path):
        label = f"{info.serial} (adb)"
        if info.state != "device":
            label += f" [{info.state}]"
        candidates.append(
            DeviceCandidate(
                kind=DeviceKind.ADB,
                label=label,
                params={"serial": info.serial, "adb_path": adb_path},
            )
        )
    return candidates


def _build_device(candidate: DeviceCandidate) -> Device:
    if candidate.kind is DeviceKind.WIN32:
        return Win32Device(**candidate.params)
    if candidate.kind is DeviceKind.ADB:
        return AdbDevice(**candidate.params)
    raise ValueError(f"Unsupported device kind: {candidate.kind}")


class DeviceManager(QObject):
    """Holds the current device and performs discovery/connection in worker threads."""

    discoveryFinished = Signal(list)  # list[DeviceCandidate]
    discoveryFailed = Signal(str)  # error message
    deviceConnected = Signal(object)  # Device
    deviceConnectionFailed = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._candidates: list[DeviceCandidate] = []
        self._device: Device | None = None
        self._candidate: DeviceCandidate | None = None
        # Auto-discovery: a running emulator's adb is preferred over PATH,
        # so users without adb in PATH can still connect.
        self._adb_path = find_adb_executable() or "adb"
        if self._adb_path == "adb":
            logger.warning("adb not found; device discovery will fail until adb is available")

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def device(self) -> Device | None:
        """Return the currently connected device, or None."""
        return self._device

    @property
    def candidate(self) -> DeviceCandidate | None:
        """Return the candidate the current device was built from, or None."""
        return self._candidate

    @property
    def candidates(self) -> list[DeviceCandidate]:
        """Return the last discovery result."""
        return list(self._candidates)

    def set_adb_path(self, adb_path: str) -> None:
        """Set the adb executable path used for future discoveries."""
        self._adb_path = adb_path

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Scan for connectable devices in a worker thread; emit discoveryFinished.

        The adb executable is re-discovered on every scan so that an
        emulator started after launch is picked up.
        """

        def _work() -> None:
            self._adb_path = find_adb_executable() or "adb"
            try:
                found = _discover_all(self._adb_path)
            except DeviceNotFoundError as exc:
                logger.warning("Device discovery failed: %s", exc)
                self.discoveryFailed.emit(str(exc))
                found = []
            except Exception as exc:
                logger.warning("Device discovery failed: %s", exc)
                found = []
            self._candidates = found
            self.discoveryFinished.emit(found)

        threading.Thread(target=_work, daemon=True).start()

    def connect(self, candidate: DeviceCandidate) -> None:
        """Connect *candidate* in a worker thread; emit deviceConnected on success.

        The connection is verified by taking one screenshot.
        """

        def _work() -> None:
            try:
                device = _build_device(candidate)
                device.screenshot()
                self._device = device
                self._candidate = candidate
                logger.info("Connected device: %s", candidate.label)
                self.deviceConnected.emit(device)
            except Exception as exc:
                logger.warning("Device connection failed: %s", exc)
                message = str(exc) or exc.__class__.__name__
                self.deviceConnectionFailed.emit(message)

        threading.Thread(target=_work, daemon=True).start()

    def disconnect(self) -> None:
        """Close the current device, if any."""
        if self._device is not None:
            self._device.close()
        self._device = None
        self._candidate = None
        logger.info("Device disconnected")


deviceManager = DeviceManager()
