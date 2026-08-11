"""Application localization: locale registry and translator management.

The app supports English (source language, no translator installed) and
Simplified Chinese. The configured language value is one of ``system``,
``en`` or ``zh-CN``; ``system`` follows the OS locale at startup.
Translators (Qt base, qfluentwidgets and the app catalog) are installed
before any UI is created and kept alive for the whole process lifetime.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale
from PySide6.QtWidgets import QApplication

from src.utils.user_message import UserMessage

logger = logging.getLogger(__name__)

LANG_SYSTEM = "system"
LANG_EN = "en"
LANG_ZH_CN = "zh-CN"

CONFIG_VALUES = (LANG_SYSTEM, LANG_EN, LANG_ZH_CN)

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "i18n"

_APP_QM_FILES = {
    LANG_EN: "ark_picit_en.qm",
    LANG_ZH_CN: "ark_picit_zh_CN.qm",
}


def fmt(text: str, *args: object) -> str:
    """Substitute ``%1``, ``%2``, ... positional placeholders in *text*."""
    for index, value in enumerate(args, 1):
        text = text.replace(f"%{index}", str(value))
    return text


#: Strong references so the translators are never garbage collected.
_app_translator = None
_qt_translator = None
_fluent_translator = None


def normalize_language(value: str) -> str:
    """Return a valid configured language value, falling back to *system*."""
    return value if value in CONFIG_VALUES else LANG_SYSTEM


def language_from_locale(locale: QLocale) -> str:
    """Map *locale* to a supported app language.

    Simplified Chinese maps to ``zh-CN``; Traditional Chinese and all
    other languages fall back to English.
    """
    if locale.language() == QLocale.Language.Chinese:
        if locale.script() == QLocale.Script.SimplifiedHanScript:
            return LANG_ZH_CN
        return LANG_EN
    return LANG_EN


def resolve_language(language: str) -> str:
    """Return the effective language for the configured *language* value."""
    if language == LANG_EN:
        return LANG_EN
    if language == LANG_ZH_CN:
        return LANG_ZH_CN
    return language_from_locale(QLocale.system())


def qt_locale(language: str) -> QLocale:
    """Return the QLocale corresponding to an effective app language."""
    return QLocale("zh_CN") if language == LANG_ZH_CN else QLocale("en_US")


def install_translators(app: QApplication, language: str) -> None:
    """Install the Qt, qfluentwidgets and app translators for *language*.

    Called before any window is created; English needs no app catalog, so
    the source strings are shown verbatim.
    """
    global _app_translator, _qt_translator, _fluent_translator

    from qfluentwidgets import FluentTranslator

    locale = qt_locale(language)
    QLocale.setDefault(locale)

    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
    if _fluent_translator is not None:
        app.removeTranslator(_fluent_translator)
    if _app_translator is not None:
        app.removeTranslator(_app_translator)

    _qt_translator = _load_qtbase_translator(app, locale)
    if _qt_translator is not None:
        app.installTranslator(_qt_translator)

    _fluent_translator = FluentTranslator(locale, parent=app)
    app.installTranslator(_fluent_translator)

    qm_name = _APP_QM_FILES.get(language)
    _app_translator = None
    if qm_name is not None:
        qm_path = _RESOURCE_DIR / qm_name
        if qm_path.is_file():
            translator = _import_translator(app)
            if translator.load(str(qm_path)):
                _app_translator = translator
                app.installTranslator(_app_translator)
            else:
                logger.warning("Failed to load translation catalog: %s", qm_path)
        else:
            logger.warning("Translation catalog missing: %s", qm_path)


def app_locale_name() -> str:
    """Return the BCP-47 name of the currently active app language."""
    return QLocale().name().replace("_", "-")


#: Structured message codes -> (semantic catalog key, param order for %1..%n).
#: The English text lives in the en translation catalog; the key is the TS source.
_MESSAGE_SOURCES = {
    # In-game task progress and errors
    "task.checking_canvas_page": ("ProgressCheckingCanvasPage", ()),
    "task.adjusting_canvas_zoom": ("ProgressAdjustingCanvasZoom", ()),
    "task.locating_canvas_and_palette": ("ProgressLocatingCanvasPalette", ()),
    "task.reading_canvas_content": ("ProgressReadingCanvasContent", ()),
    "task.generating_verification_screenshot": ("ProgressGeneratingVerification", ()),
    "task.canvas_already_matches": ("CanvasAlreadyMatchesTip", ()),
    "task.selecting_color": ("ProgressSelectingColor", ("color",)),
    "task.painting_cells": ("ProgressPaintingCells", ("count", "color")),
    "task.drawing_complete": ("ProgressDrawingComplete", ()),
    "task.all_colors_painted": ("AllColorsPaintedTip", ()),
    "task.palette_scrolling_up": ("ProgressPaletteScrollingUp", ()),
    "task.palette_scrolling_down": ("ProgressPaletteScrollingDown", ()),
    "task.palette_color_not_found": ("ErrorPaletteColorNotFound", ("color",)),
    "task.already_running": ("ErrorTaskAlreadyRunning", ()),
    "task.no_verified_layout": ("ErrorNoVerifiedLayout", ()),
    "task.not_in_canvas_page": ("ErrorNotInCanvasPage", ()),
    "task.canvas_slider_not_found": ("ErrorCanvasSliderNotFound", ()),
    "task.canvas_anchors_not_found": ("ErrorCanvasAnchorsNotFound", ()),
    "task.invalid_anchor_positions": ("ErrorInvalidAnchorPositions", ()),
    "task.invalid_palette_region": ("ErrorInvalidPaletteRegion", ()),
    # ArkPicCode mismatches (structurally valid code vs current ruleset)
    "code.dimension_mismatch": (
        "ErrorCodeDimensionMismatch", ("code_width", "code_height", "rule_width", "rule_height")
    ),
    "code.rule_hash_mismatch": ("ErrorCodeRuleHashMismatch", ("code_hash", "rule_hash")),
    # Plaza server / network errors
    "too_many_requests": ("ErrorTooManyRequests", ()),
    "payload_too_large": ("ErrorPayloadTooLarge", ()),
    "admin_token_required": ("ErrorAdminTokenRequired", ()),
    "client_token_required": ("ErrorClientTokenRequired", ()),
    "invalid_client_token": ("ErrorInvalidClientToken", ()),
    "invalid_sort": ("ErrorInvalidSort", ()),
    "invalid_order": ("ErrorInvalidOrder", ()),
    "invalid_mode": ("ErrorInvalidMode", ()),
    "already_rated": ("ErrorAlreadyRated", ()),
    "already_reported": ("ErrorAlreadyReported", ()),
    "already_published": ("ErrorAlreadyPublished", ()),
    "artwork_not_found": ("ErrorArtworkNotFound", ()),
    "not_uploading_client": ("ErrorNotUploadingClient", ()),
    "invalid_content": ("ErrorInvalidContent", ()),
    "request_timeout": ("ErrorRequestTimeout", ()),
}


def _mark_message_sources() -> None:
    """Keep the structured message keys in the translation catalogs.

    lupdate only extracts literal arguments, so the keys in
    ``_MESSAGE_SOURCES`` are repeated here as literal ``translate()``
    calls. The function is never executed.
    """
    QCoreApplication.translate("TaskMessage", "ProgressCheckingCanvasPage")
    QCoreApplication.translate("TaskMessage", "ProgressAdjustingCanvasZoom")
    QCoreApplication.translate("TaskMessage", "ProgressLocatingCanvasPalette")
    QCoreApplication.translate("TaskMessage", "ProgressReadingCanvasContent")
    QCoreApplication.translate("TaskMessage", "ProgressGeneratingVerification")
    QCoreApplication.translate("TaskMessage", "CanvasAlreadyMatchesTip")
    QCoreApplication.translate("TaskMessage", "ProgressSelectingColor")
    QCoreApplication.translate("TaskMessage", "ProgressPaintingCells")
    QCoreApplication.translate("TaskMessage", "ProgressDrawingComplete")
    QCoreApplication.translate("TaskMessage", "AllColorsPaintedTip")
    QCoreApplication.translate("TaskMessage", "ProgressPaletteScrollingUp")
    QCoreApplication.translate("TaskMessage", "ProgressPaletteScrollingDown")
    QCoreApplication.translate("TaskMessage", "ErrorPaletteColorNotFound")
    QCoreApplication.translate("TaskMessage", "ErrorTaskAlreadyRunning")
    QCoreApplication.translate("TaskMessage", "ErrorNoVerifiedLayout")
    QCoreApplication.translate("TaskMessage", "ErrorNotInCanvasPage")
    QCoreApplication.translate("TaskMessage", "ErrorCanvasSliderNotFound")
    QCoreApplication.translate("TaskMessage", "ErrorCanvasAnchorsNotFound")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidAnchorPositions")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidPaletteRegion")
    QCoreApplication.translate("TaskMessage", "ErrorCodeDimensionMismatch")
    QCoreApplication.translate("TaskMessage", "ErrorCodeRuleHashMismatch")
    QCoreApplication.translate("TaskMessage", "ErrorTooManyRequests")
    QCoreApplication.translate("TaskMessage", "ErrorPayloadTooLarge")
    QCoreApplication.translate("TaskMessage", "ErrorAdminTokenRequired")
    QCoreApplication.translate("TaskMessage", "ErrorClientTokenRequired")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidClientToken")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidSort")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidOrder")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidMode")
    QCoreApplication.translate("TaskMessage", "ErrorAlreadyRated")
    QCoreApplication.translate("TaskMessage", "ErrorAlreadyReported")
    QCoreApplication.translate("TaskMessage", "ErrorAlreadyPublished")
    QCoreApplication.translate("TaskMessage", "ErrorArtworkNotFound")
    QCoreApplication.translate("TaskMessage", "ErrorNotUploadingClient")
    QCoreApplication.translate("TaskMessage", "ErrorInvalidContent")
    QCoreApplication.translate("TaskMessage", "ErrorRequestTimeout")
    # Mirrors the reason keys in src.utils.path_guard (early startup dialog).
    QCoreApplication.translate("PathGuard", "ReasonDriveRoot")
    QCoreApplication.translate("PathGuard", "ReasonTempDir")
    QCoreApplication.translate("PathGuard", "ReasonSystemDir")
    QCoreApplication.translate("PathGuard", "ReasonNotWritable")


def localize_message(message) -> str:
    """Translate a structured :class:`UserMessage` into display text.

    Falls back to the technical detail (raw diagnostic text), then to the
    message code itself when no source template exists.
    """
    entry = _MESSAGE_SOURCES.get(message.code)
    if entry is None:
        return message.technical_detail or message.code
    key, param_order = entry
    text = QCoreApplication.translate("TaskMessage", key)
    args = tuple(str(message.params.get(name, "")) for name in param_order)
    return fmt(text, *args)


def localize_http_error(result) -> str:
    """Translate a network result with a stable error code into display text.

    Falls back to the server's raw detail message when the code is unknown
    or absent, so foreign servers and legacy responses stay readable.
    """
    code = result.error_code()
    if code:
        return localize_message(UserMessage(code, {}, result.detail()))
    return result.detail()


def _import_translator(app: QApplication):
    from PySide6.QtCore import QTranslator

    return QTranslator(app)


def _load_qtbase_translator(app: QApplication, locale: QLocale):
    """Load Qt's built-in widget translations (e.g. qtbase_zh_CN.qm)."""
    from PySide6.QtCore import QTranslator

    translations_path = Path(
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    )
    path = translations_path / f"qtbase_{locale.name()}.qm"
    if not path.is_file():
        logger.warning("Qt base translation missing: %s", path)
        return None
    translator = QTranslator(app)
    if translator.load(str(path)):
        return translator
    logger.warning("Failed to load Qt base translation: %s", path)
    return None
