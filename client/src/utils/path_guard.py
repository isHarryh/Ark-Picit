"""Startup path guard: refuse to run from risky install locations.

The checks mirror MaaAssistantArknights' Bootstrapper: running from a
drive root, a temporary directory or a system directory breaks file
persistence and automation, so the client refuses to start there.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping

logger = logging.getLogger(__name__)

RISKY_ROOT = "root"
RISKY_TEMP = "temp"
RISKY_SYSTEM = "system"
RISKY_NOT_WRITABLE = "not-writable"

REASON_TEXT = {
    RISKY_ROOT: "ReasonDriveRoot",
    RISKY_TEMP: "ReasonTempDir",
    RISKY_SYSTEM: "ReasonSystemDir",
    RISKY_NOT_WRITABLE: "ReasonNotWritable",
}

_TEMP_PREFIXES = ("temp", "tmp")


def reason_text(reason: str) -> str:
    """Return the catalog key explaining a risk reason (translate at display)."""
    return REASON_TEXT.get(reason, reason)


def _normalize(path: Path | str) -> str:
    """Return an absolute, separator-trimmed, case-folded path string."""
    return os.path.abspath(os.path.normpath(str(path))).rstrip("\\/").casefold()


def _is_drive_root(current: str) -> bool:
    return len(current) == 2 and current[1] == ":" and current[0].isalpha()


def _is_temp_like(name: str) -> bool:
    return bool(name) and name.casefold().startswith(_TEMP_PREFIXES)


def _temp_dirs(environ: Mapping[str, str]) -> set[str]:
    dirs: set[str] = set()
    for var in ("TEMP", "TMP", "TMPDIR"):
        value = environ.get(var)
        if value:
            dirs.add(_normalize(value))
    try:
        dirs.add(_normalize(tempfile.gettempdir()))
    except OSError:
        pass
    return dirs


def _system_dirs(environ: Mapping[str, str]) -> set[str]:
    dirs: set[str] = set()
    for var in (
        "PROGRAMDATA",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "USERPROFILE",
        "WINDIR",
        "PUBLIC",
        "CommonProgramFiles",
    ):
        value = environ.get(var)
        if value:
            dirs.add(_normalize(value))
    program_files = environ.get("PROGRAMFILES")
    if program_files:
        dirs.add(_normalize(Path(program_files) / "Common Files"))
    windir = environ.get("WINDIR")
    if windir:
        dirs.add(_normalize(Path(windir) / "System32" / "Drivers" / "DriverData"))
    return dirs


def _is_writable(directory: Path) -> bool:
    """Probe whether *directory* allows creating and deleting files."""
    probe = directory / "write_test.tmp"
    try:
        probe.write_text("test", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def risky_location(
    cwd: Path | str,
    environ: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Return ``(True, reason)`` when *cwd* is unsafe to run from.

    Mirrors MAA's startup checks: drive root, temp directories (including
    temp-like directory names), system locations, and a write probe.
    On non-Windows platforms the check is skipped.
    """
    if sys.platform != "win32":
        return False, ""
    env = dict(os.environ) if environ is None else dict(environ)
    current = _normalize(cwd)

    if _is_drive_root(current):
        return True, RISKY_ROOT

    for root in _temp_dirs(env):
        if current == root or current.startswith(root + "\\"):
            return True, RISKY_TEMP

    segments = current.split("\\")
    name = segments[-1] if len(segments) > 1 else current
    parent = segments[-2] if len(segments) > 2 else ""
    if _is_temp_like(name) or _is_temp_like(parent):
        return True, RISKY_TEMP

    if current in _system_dirs(env):
        return True, RISKY_SYSTEM

    if not _is_writable(Path(current)):
        logger.warning("Working directory is not writable: %s", current)
        return True, RISKY_NOT_WRITABLE

    return False, ""
