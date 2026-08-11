"""Strict checks for the translation catalogs.

Verifies that the committed en/zh-CN TS/QM catalogs are complete, use the
same semantic key sets, keep consistent ``%1`` placeholders and are in sync
with the source code. Run from the repository root:

    uv run python tools/lint_i18n.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "client" / "src"
EXTRA_SOURCES = (ROOT / "client" / "main.py",)
RES = SRC / "resources" / "i18n"
TS_FILES = (RES / "ark_picit_en.ts", RES / "ark_picit_zh_CN.ts")

_PLACEHOLDER_RE = re.compile(r"%[Ln]?\d+|%n")
_NAMED_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


class LintError(Exception):
    """Raised when a catalog check fails."""


def _fail(description: str, *details: str) -> None:
    raise LintError(description + (":\n  " + "\n  ".join(details) if details else ""))


def _tool(name: str) -> str:
    candidate = ROOT / ".venv" / "Scripts" / f"pyside6-{name}.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(f"pyside6-{name}")
    if found:
        return found
    raise LintError(f"pyside6-{name} not found")


def _parse_ts(path: Path):
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise LintError(f"Cannot parse TS file {path}: {exc}") from exc


def _catalog(root) -> dict[str, str]:
    """Map the semantic source key to the translation text."""
    result = {}
    for context in root.findall("context"):
        name = context.findtext("name") or ""
        for message in context.findall("message"):
            source = message.findtext("source") or ""
            key = f"{name}:{source}"
            if message.get("numerus") == "yes":
                translation_elem = message.find("translation")
                forms = message.findall("translation/numerusform")
                if translation_elem is not None and translation_elem.get("type") == "unfinished":
                    translation = ""
                else:
                    translation = "\x01".join(form.text or "" for form in forms)
            else:
                translation = (message.findtext("translation") or "")
            result[key] = translation
    return result


def _check_metadata(root, path: Path, language: str) -> None:
    actual = root.get("language")
    if actual != language:
        _fail(f"{path.name} language must be {language!r}", f"found: {actual}")


def _check_completeness(catalog, path: Path) -> None:
    missing = [key for key, translation in catalog.items() if not translation.strip()]
    if missing:
        _fail(f"Unfinished or empty translations in {path.name}", *missing)


def _check_numerus(catalog, path: Path) -> None:
    errors = []
    for key, translation in catalog.items():
        if "\x01" not in translation:
            continue
        forms = translation.split("\x01")
        if any(not form for form in forms):
            errors.append(f"{key} has an empty plural form")
    if errors:
        _fail(f"Numerus problems in {path.name}", *errors)


def _check_cross_language(en: dict[str, str], zh: dict[str, str]) -> None:
    if set(en) != set(zh):
        _fail(
            "English and zh-CN catalogs must use the same keys",
            "missing in zh-CN: " + ", ".join(sorted(set(en) - set(zh))[:20]),
            "missing in en: " + ", ".join(sorted(set(zh) - set(en))[:20]),
        )
    errors = []
    for key in en:
        en_text, zh_text = en[key], zh[key]
        if "\x01" in en_text or "\x01" in zh_text:
            continue  # numerus catalogs are validated per language
        en_placeholders = sorted(_PLACEHOLDER_RE.findall(en_text))
        zh_placeholders = sorted(_PLACEHOLDER_RE.findall(zh_text))
        if en_placeholders != zh_placeholders:
            errors.append(f"{key}: en {en_placeholders} vs zh {zh_placeholders}")
        for text in (en_text, zh_text):
            if _NAMED_RE.search(text):
                errors.append(f"{key}: Python named placeholder {_NAMED_RE.search(text).group()} in {text!r}")
    if errors:
        _fail("Placeholder mismatch between catalogs", *errors)


def _extract_current_keys() -> set[str]:
    """Run lupdate into a temp TS and return the extracted (context:key) set."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_ts = Path(tmp) / "current_en.ts"
        sources = list(SRC.rglob("*.py")) + list(EXTRA_SOURCES)
        cmd = [
            _tool("lupdate"),
            *(str(p) for p in sources),
            "-ts", str(tmp_ts),
            "-source-language", "en_US",
            "-locations", "none",
            "-silent",
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return set(_catalog(_parse_ts(tmp_ts)).keys())


def _check_sync(committed: set[str]) -> None:
    current = _extract_current_keys()
    missing = sorted(current - committed)
    orphan = sorted(committed - current)
    if missing:
        _fail("Source keys missing from the committed catalogs (run tools/update_i18n.py)", *missing[:20])
    if orphan:
        _fail("Orphan keys in the committed catalogs not found in source", *orphan[:20])


def _check_qm_fresh() -> None:
    """Recompile the QMs and compare bytes with the committed ones."""
    with tempfile.TemporaryDirectory() as tmp:
        for ts in TS_FILES:
            tmp_qm = Path(tmp) / ts.with_suffix(".qm").name
            subprocess.run(
                [_tool("lrelease"), str(ts), "-qm", str(tmp_qm), "-nounfinished", "-silent"],
                check=True, capture_output=True,
            )
            if not ts.with_suffix(".qm").is_file():
                _fail("Committed QM is missing", str(ts.with_suffix(".qm")))
            if ts.with_suffix(".qm").read_bytes() != tmp_qm.read_bytes():
                _fail("Committed QM is stale (run tools/update_i18n.py)", ts.name)


def _check_config_values() -> None:
    import ast

    config = ROOT / "client" / "src" / "app" / "config.py"
    tree = ast.parse(config.read_text(encoding="utf-8"))
    expected = {"system", "en", "zh-CN"}
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            values = {
                el.value
                for el in node.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
            if values == expected:
                return
    _fail("Language config values must be exactly {'system', 'en', 'zh-CN'}")


def main() -> int:
    en_root = _parse_ts(TS_FILES[0])
    zh_root = _parse_ts(TS_FILES[1])
    _check_metadata(en_root, TS_FILES[0], "en_US")
    _check_metadata(zh_root, TS_FILES[1], "zh_CN")
    en = _catalog(en_root)
    zh = _catalog(zh_root)
    _check_completeness(en, TS_FILES[0])
    _check_completeness(zh, TS_FILES[1])
    _check_numerus(en, TS_FILES[0])
    _check_numerus(zh, TS_FILES[1])
    _check_cross_language(en, zh)
    _check_sync(set(en))
    _check_qm_fresh()
    _check_config_values()
    print(f"{TS_FILES[0].name}: {len(en)} keys, {TS_FILES[1].name}: {len(zh)} keys, all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LintError as exc:
        print(f"i18n lint failed: {exc}", file=sys.stderr)
        sys.exit(1)
