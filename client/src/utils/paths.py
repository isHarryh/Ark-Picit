"""Centralized path definitions for the application.

All runtime data is stored under ``<cwd>/data/arkpicit_client_v1/``; the
layout is fixed and not configurable. Bundled assets live relative to this
module.
"""

import time
from pathlib import Path

# Client bundle root (where client/src lives), used for read-only assets
APP_DIR = Path(__file__).resolve().parent.parent.parent

# Runtime data: fixed location under the working directory (cwd)
DATA_DIR = Path.cwd() / "data" / "arkpicit_client_v1"
CONFIG_DIR = DATA_DIR / "config"
CACHE_DIR = DATA_DIR / "cache"
GALLERY_DIR = DATA_DIR / "gallery"
SCREENSHOT_DIR = DATA_DIR / "screenshots"

# Assets
ASSETS_DIR = APP_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"


def ensure_runtime_dirs() -> None:
    """Create runtime directories if they don't exist."""
    for d in (CONFIG_DIR, CACHE_DIR, GALLERY_DIR, SCREENSHOT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def cleanup_old_screenshots(max_files: int = 10, max_age_days: int = 7) -> int:
    """Delete stale screenshot PNGs, keeping the most recent ones.

    Files older than *max_age_days* are removed first; if more than
    *max_files* remain, the oldest files are deleted until the limit is
    met. Returns the number of deleted files.
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_days * 86400

    def _pngs() -> list[Path]:
        return sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)

    removed = 0
    for p in _pngs():
        if p.stat().st_mtime < cutoff:
            try:
                p.unlink()
            except OSError:
                continue
            removed += 1

    remaining = _pngs()
    for p in remaining[: max(0, len(remaining) - max_files)]:
        try:
            p.unlink()
        except OSError:
            continue
        removed += 1
    return removed
