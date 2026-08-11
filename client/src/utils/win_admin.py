"""Windows administrator privilege detection and elevation."""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def is_admin() -> bool:
    """Return whether the current process runs with administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        logger.warning("Failed to query admin status", exc_info=True)
        return False


def relaunch_as_admin() -> bool:
    """Relaunch the application with administrator privileges via UAC.

    Returns True when the elevated process was spawned (the user accepted
    the UAC prompt); the caller should then exit the current process.
    """
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            parameters = ""
        else:
            executable = sys.executable
            parameters = str(Path(sys.argv[0]).resolve())
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, parameters, None, 1
        )
        return result > 32
    except Exception:
        logger.warning("Failed to relaunch as administrator", exc_info=True)
        return False
