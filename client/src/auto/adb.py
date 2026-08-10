"""Android device implementation driven by the adb command-line tool."""

from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import cv2
import numpy as np

from src.auto.base import Device, DeviceError, DeviceKind, DeviceNotFoundError

logger = logging.getLogger(__name__)

_ADB_CMD_TIMEOUT_S = 30
_ADB_CONNECT_TIMEOUT_S = 5
# Well-known local adb ports of common emulators: LDPlayer (5555+), MEmu
# (21503), Nox (62001), MuMu 6 (7555), MuMu 12 (16384), BlueStacks/Genymotion (5555).
_EMULATOR_ADB_PORTS = (5555, 5556, 5557, 5558, 5559, 7555, 16384, 21503, 62001)


@dataclass(frozen=True, slots=True)
class AdbDeviceInfo:
    """A device reported by ``adb devices``."""

    serial: str
    state: str  # "device", "unauthorized", "offline", ...


@dataclass(frozen=True, slots=True)
class _EmulatorRule:
    """How to locate the adb binary of a running emulator.

    The process keywords and adb candidate paths mirror the emulator
    discovery of MaaAssistantArknights (AGPL-3.0) and MaaFramework
    (LGPL-3.0).
    """

    name: str
    keywords: tuple[str, ...]  # process-name substrings (lowercase)
    adb_rel_paths: tuple[str, ...]  # relative adb paths from the process directory


_EMULATOR_RULES = (
    _EmulatorRule(
        "MuMu 12",
        ("mumuplayer.exe", "mumunxdevice.exe"),
        (
            r"..\..\..\nx_main\adb.exe",
            r"..\vmonitor\bin\adb_server.exe",
            r"..\..\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
            r"adb.exe",
        ),
    ),
    _EmulatorRule(
        "MuMu 6",
        ("nemuplayer.exe",),
        (
            r"vmonitor\bin\adb_server.exe",
            r"MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
            r"adb.exe",
        ),
    ),
    _EmulatorRule("LDPlayer", ("dnplayer.exe",), (r"adb.exe",)),
    _EmulatorRule(
        "BlueStacks",
        ("hd-player.exe",),
        (r"HD-Adb.exe", r"Engine\ProgramFiles\HD-Adb.exe"),
    ),
    _EmulatorRule("Nox", ("nox",), (r"nox_adb.exe",)),
    _EmulatorRule("MEmu", ("memu",), (r"adb.exe",)),
    _EmulatorRule("AVD", ("qemu-system",), (r"..\..\..\platform-tools\adb.exe",)),
)

# ---------------------------------------------------------------------------
# Process enumeration (Windows only)
# ---------------------------------------------------------------------------

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x2


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _kernel32 = None


def _list_processes() -> list[tuple[str, int]]:
    """Return (lowercase process name, pid) pairs via a Toolhelp32 snapshot."""
    if _kernel32 is None:
        return []
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        processes: list[tuple[str, int]] = []
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            processes.append((entry.szExeFile.lower(), entry.th32ProcessID))
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return processes
    finally:
        _kernel32.CloseHandle(snapshot)


def _process_path(pid: int) -> str | None:
    """Return the executable path of *pid*, or None when it is not accessible."""
    if _kernel32 is None:
        return None
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        _kernel32.CloseHandle(handle)


def _match_rule(process_name: str) -> _EmulatorRule | None:
    """Return the emulator rule matching *process_name*, or None."""
    for rule in _EMULATOR_RULES:
        if any(keyword in process_name for keyword in rule.keywords):
            return rule
    return None


def _validate_adb(path: str) -> bool:
    """Return whether *path* is a runnable adb binary (exit code 0 on version)."""
    try:
        result = subprocess.run(
            [path, "version"], capture_output=True, timeout=_ADB_CONNECT_TIMEOUT_S
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_adb_executable() -> str | None:
    """Locate a usable adb executable for this machine, or None.

    Running emulator processes are matched against known emulator rules
    and their adb binary is resolved relative to the process directory;
    the PATH is used as a final fallback. The emulator rule table is
    inspired by MaaAssistantArknights (AGPL-3.0) and MaaFramework
    (LGPL-3.0).
    """
    candidates: list[str] = []
    for name, pid in _list_processes():
        rule = _match_rule(name)
        if rule is None:
            continue
        exe_path = _process_path(pid)
        if not exe_path:
            continue
        base = Path(exe_path).parent
        for rel in rule.adb_rel_paths:
            candidate = base / rel
            if candidate.is_file():
                candidates.append(str(candidate.resolve()))
    for candidate in dict.fromkeys(candidates):
        if _validate_adb(candidate):
            return candidate
    from_path = shutil.which("adb")
    if from_path and _validate_adb(from_path):
        return str(Path(from_path).resolve())
    return None


def _run_adb(adb_path: str, args: list[str], *, timeout: float = _ADB_CMD_TIMEOUT_S) -> bytes:
    """Run an adb command, raising DeviceError on failure."""
    try:
        result = subprocess.run([adb_path, *args], capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DeviceNotFoundError(
            f"adb executable not found: {adb_path}. Install Android platform-tools "
            "or add adb to your PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeviceError(f"adb command timed out: {adb_path} {' '.join(args)}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise DeviceError(f"adb command failed ({result.returncode}): {stderr or 'no error output'}")
    return result.stdout


def list_devices(adb_path: str = "adb") -> list[AdbDeviceInfo]:
    """Return all devices reported by ``adb devices``, in any state."""
    output = _run_adb(adb_path, ["devices"]).decode("utf-8", errors="replace")
    devices: list[AdbDeviceInfo] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("List of devices"):
            continue
        fields = stripped.split()
        if len(fields) >= 2:
            devices.append(AdbDeviceInfo(fields[0], fields[1]))
    return devices


def _probe_port(adb_path: str, port: int) -> str | None:
    """Try to register a local emulator adb port; return its serial on success."""
    serial = f"127.0.0.1:{port}"
    try:
        output = _run_adb(adb_path, ["connect", serial], timeout=_ADB_CONNECT_TIMEOUT_S)
    except DeviceError:
        return None
    # `adb connect` exits 0 even on failure, so judge by the message text.
    if "cannot connect" in output.decode("utf-8", errors="replace").lower():
        return None
    return serial


def probe_emulators(adb_path: str = "adb") -> list[str]:
    """Connect to well-known local emulator adb ports in parallel.

    An emulator only shows up in ``adb devices`` after an explicit
    ``adb connect``, so this registers every common emulator port and
    returns the serials that responded. Failures are silent.
    """
    with ThreadPoolExecutor(max_workers=len(_EMULATOR_ADB_PORTS)) as pool:
        futures = [pool.submit(_probe_port, adb_path, port) for port in _EMULATOR_ADB_PORTS]
        serials = [future.result() for future in as_completed(futures)]
    return [serial for serial in serials if serial is not None]


class AdbDevice(Device):
    """Control an Android device (real or emulator) through the adb tool.

    Coordinates are physical screen pixels as produced by ``screencap``.
    """

    kind: ClassVar[DeviceKind] = DeviceKind.ADB

    def __init__(self, serial: str | None = None, *, adb_path: str = "adb"):
        self._adb_path = adb_path
        self._screen_size: tuple[int, int] | None = None
        serials = [info.serial for info in list_devices(adb_path)]
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
            if serial not in [info.serial for info in list_devices(adb_path)]:
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
