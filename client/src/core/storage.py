"""Persistent storage for user paintings.

Each painting is stored as a single JSON file in the gallery directory.
The JSON contains all metadata plus a base64-encoded 1:1 PNG preview.
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.core.pic import ArkPic
from src.core.preview import generate_preview
from src.core.rule import ArkPicRule

logger = logging.getLogger(__name__)


@dataclass
class StoredPic:
    """A painting persisted in the gallery.

    The full ArkPicRule (width + height + complete palette) is stored
    alongside the pixels so a painting is fully self-describing.
    """

    id: str = ""
    name: str = ""
    description: str = ""
    last_saved: str = ""
    rule_width: int = 0
    rule_height: int = 0
    rule_colors: list[str] = field(default_factory=list)
    rule_default_color_id: int = 1
    pixels: list[int] = field(default_factory=list)
    preview_png_b64: str = ""

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def to_ark_pic(self) -> tuple[ArkPic, ArkPicRule]:
        """Reconstruct the ArkPic and ArkPicRule from stored data."""
        rule = ArkPicRule(
            self.rule_width, self.rule_height, self.rule_colors,
            default_color_id=self.rule_default_color_id,
        )
        pic = ArkPic(rule)
        pic.fill_flat(self.pixels)
        return pic, rule

    @property
    def preview_png(self) -> bytes:
        return base64.b64decode(self.preview_png_b64) if self.preview_png_b64 else b""

    @classmethod
    def from_ark_pic(
        cls,
        name: str,
        description: str,
        pic: ArkPic,
        rule: ArkPicRule,
        id: str | None = None,
    ) -> "StoredPic":
        """Create a StoredPic from live objects, generating a fresh preview."""
        return cls(
            id=id or uuid4().hex,
            name=name,
            description=description,
            last_saved=datetime.now().isoformat(timespec="seconds"),
            rule_width=rule.width,
            rule_height=rule.height,
            rule_colors=list(rule.colors),
            rule_default_color_id=rule.default_color_id,
            pixels=pic.flat,
            preview_png_b64=base64.b64encode(generate_preview(pic)).decode("ascii"),
        )

    def refresh_preview(self, pic: ArkPic) -> None:
        """Regenerate the preview PNG from *pic*."""
        self.preview_png_b64 = base64.b64encode(generate_preview(pic)).decode("ascii")
        self.last_saved = datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

_GALLERY_DIR: Path | None = None


def set_gallery_dir(path: Path) -> None:
    global _GALLERY_DIR
    _GALLERY_DIR = path
    _GALLERY_DIR.mkdir(parents=True, exist_ok=True)


def _gallery_dir() -> Path:
    if _GALLERY_DIR is None:
        raise RuntimeError("Gallery dir not set. Call set_gallery_dir() first.")
    return _GALLERY_DIR


def _file_path(pic_id: str) -> Path:
    return _gallery_dir() / f"{pic_id}.json"


def save(stored: StoredPic) -> None:
    """Write *stored* to the gallery as JSON."""
    if not stored.id:
        stored.id = uuid4().hex
    stored.last_saved = datetime.now().isoformat(timespec="seconds")
    data = asdict(stored)
    path = _file_path(stored.id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved painting '%s' (%s)", stored.name, stored.id)


def load(pic_id: str) -> StoredPic | None:
    """Load a single painting by id."""
    path = _file_path(pic_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return StoredPic(**data)


def list_all() -> list[StoredPic]:
    """Return all paintings in the gallery, newest first."""
    paintings: list[StoredPic] = []
    for p in _gallery_dir().glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            paintings.append(StoredPic(**data))
        except Exception:
            logger.warning("Failed to load painting: %s", p)
    paintings.sort(key=lambda s: s.last_saved, reverse=True)
    return paintings


def delete(pic_id: str) -> None:
    """Remove a painting from the gallery."""
    path = _file_path(pic_id)
    if path.exists():
        path.unlink()
        logger.info("Deleted painting %s", pic_id)


# ---------------------------------------------------------------------------
# Export / Import (standalone files)
# ---------------------------------------------------------------------------

def export_to_file(stored: StoredPic, path: Path) -> None:
    """Write a painting to an arbitrary file path."""
    data = asdict(stored)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def import_from_file(path: Path) -> StoredPic:
    """Load a painting from a file, assigning a new gallery id."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = uuid4().hex  # fresh id so it doesn't collide
    return StoredPic(**data)


# ---------------------------------------------------------------------------
# Backup (whole-gallery zip archive)
# ---------------------------------------------------------------------------

def backup_to_zip(path: Path) -> int:
    """Package every gallery JSON file into the zip archive at *path*.

    Returns the number of paintings written.
    """
    count = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in _gallery_dir().glob("*.json"):
            zf.write(p, p.name)
            count += 1
    return count


def restore_from_zip(path: Path) -> int:
    """Extract painting JSON files from the zip archive at *path*.

    Files are written to the gallery directory, replacing any same-named
    file. Directory entries and non-JSON files are skipped, and only the
    file name is used so archive paths cannot escape the gallery.
    Returns the number of paintings restored.
    """
    count = 0
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".json"):
                continue
            with zf.open(info) as src, (_gallery_dir() / name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count
