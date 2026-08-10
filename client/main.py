"""Client entry point: ``run_client()`` launches the GUI.

Also runnable directly: ``python client/main.py``.
"""

from __future__ import annotations

import sys
from contextlib import ContextDecorator
from pathlib import Path

# Make client/src importable as the `src.` package (script directory would
# also work when run directly; this covers import from the root entry point).
_CLIENT_ROOT = Path(__file__).resolve().parent
if str(_CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLIENT_ROOT))


class _BlackHoleStream:
    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return len(text)

    def flush(self):
        self._stream.flush()

    def isatty(self):
        return self._stream.isatty()


class _MutedStdout(ContextDecorator):
    def __enter__(self):
        self._original = sys.stdout
        sys.stdout = _BlackHoleStream(self._original)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        sys.stdout = self._original
        return False


def run_client() -> None:
    """Launch the GUI client: QApplication, storage, config, main window."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # High-DPI (Qt6 handles this automatically, but we set the rounding policy)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Ark Picit")
    app.setApplicationDisplayName("Ark Picit")

    # Ensure the app font carries a valid point size
    font = app.font()
    if font.pointSize() < 1:
        font.setPointSize(9)
        app.setFont(font)

    # Runtime directories live in the working directory
    from src.utils.paths import CONFIG_DIR, GALLERY_DIR, ensure_runtime_dirs
    ensure_runtime_dirs()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Gallery storage
    from src.core import storage
    storage.set_gallery_dir(GALLERY_DIR)

    # Config: importing it first pulls in qfluentwidgets, whose first import
    # prints a promo banner; mute stdout around that import.
    with _MutedStdout():
        from src.app.config import init_config
    config_path = CONFIG_DIR / "config.json"
    init_config(config_path)

    # Fluent translator
    from qfluentwidgets import FluentTranslator, setTheme

    fluent_translator = FluentTranslator()
    app.installTranslator(fluent_translator)

    # Theme
    from qfluentwidgets import qconfig
    from src.app.config import cfg
    theme_val = qconfig.get(cfg().themeMode)
    setTheme(theme_val)

    # Main window
    from src.app.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    run_client()
