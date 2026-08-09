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
    Win32Device,
    list_devices,
    list_windows,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeviceCandidate:
    """A connectable device found during discovery."""

    kind: DeviceKind
    label: str
    params: dict = field(default_factory=dict)


def _discover_all(adb_path: str) -> list[DeviceCandidate]:
    """Return all connectable candidates: visible windows first, then adb devices."""
    candidates: list[DeviceCandidate] = []
    for window in list_windows():
        if not window.title:
            continue
        candidates.append(
            DeviceCandidate(
                kind=DeviceKind.WIN32,
                label=window.title,
                params={"title_regex": window.title, "class_regex": window.class_name},
            )
        )
    for serial in list_devices(adb_path):
        candidates.append(
            DeviceCandidate(
                kind=DeviceKind.ADB,
                label=f"{serial} (adb)",
                params={"serial": serial},
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
    deviceConnected = Signal(object)  # Device
    deviceConnectionFailed = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._candidates: list[DeviceCandidate] = []
        self._device: Device | None = None
        self._candidate: DeviceCandidate | None = None
        self._adb_path = "adb"

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
        """Scan for connectable devices in a worker thread; emit discoveryFinished."""

        def _work() -> None:
            try:
                found = _discover_all(self._adb_path)
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
