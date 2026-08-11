"""Update the translation catalogs from the client source code.

Scans the client sources for ``tr()`` / ``QCoreApplication.translate()``
calls (the catalog keys), merges them into the English and zh-CN TS files,
then compiles the QM catalogs. Run from the repository root:

    uv run python tools/update_i18n.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "client" / "src"
EXTRA_SOURCES = (ROOT / "client" / "main.py",)
RES = SRC / "resources" / "i18n"
TS_FILES = (RES / "ark_picit_en.ts", RES / "ark_picit_zh_CN.ts")


def _tool(name: str) -> str:
    """Locate the pyside6-* tool, preferring the project virtualenv."""
    candidate = ROOT / ".venv" / "Scripts" / f"pyside6-{name}.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(f"pyside6-{name}")
    if found:
        return found
    raise SystemExit(f"pyside6-{name} not found; is PySide6 installed?")


def _sources() -> list[str]:
    files = list(SRC.rglob("*.py")) + list(EXTRA_SOURCES)
    return [str(p) for p in files]


def main() -> int:
    lupdate = _tool("lupdate")
    cmd = [
        lupdate,
        *_sources(),
        "-ts", *(str(ts) for ts in TS_FILES),
        "-source-language", "en_US",
        "-locations", "relative",
        "-no-obsolete",
        "-sort-messages",
        "-warnings-are-errors",
    ]
    subprocess.run(cmd, check=True)

    lrelease = _tool("lrelease")
    for ts in TS_FILES:
        qm = ts.with_suffix(".qm")
        subprocess.run(
            [lrelease, str(ts), "-qm", str(qm), "-nounfinished", "-fail-on-invalid"],
            check=True,
        )
    print(f"Updated {', '.join(ts.name for ts in TS_FILES)} and compiled their QMs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
