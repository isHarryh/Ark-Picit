"""Centralized path definitions for the application.

All runtime data is stored under ``<cwd>/data/arkpicit_client_v1/``; the
layout is fixed and not configurable. Bundled assets live relative to this
module.
"""

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
