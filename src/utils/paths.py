"""Centralized path definitions for the application."""

from pathlib import Path

# Project root (where main.py lives)
APP_DIR = Path(__file__).resolve().parent.parent.parent

# Runtime data (created on demand, not tracked by git)
CONFIG_DIR = APP_DIR / "config"
CACHE_DIR = APP_DIR / "cache"
GALLERY_DIR = APP_DIR / "gallery"
SCREENSHOT_DIR = APP_DIR / "screenshots"

# Assets
ASSETS_DIR = APP_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"


def ensure_runtime_dirs() -> None:
    """Create runtime directories if they don't exist."""
    for d in (CONFIG_DIR, CACHE_DIR, GALLERY_DIR, SCREENSHOT_DIR):
        d.mkdir(parents=True, exist_ok=True)
