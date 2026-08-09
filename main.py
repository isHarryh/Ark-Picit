"""Ark Picit — application entry point.

Run with:  python main.py
"""

import sys
from contextlib import ContextDecorator
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Ensure src/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))


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

with _MutedStdout():
    from qfluentwidgets import FluentTranslator, setTheme


def main():
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

    # Localization
    from src.utils.paths import CONFIG_DIR, GALLERY_DIR, ensure_runtime_dirs
    ensure_runtime_dirs()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Gallery storage
    from src.core import storage
    storage.set_gallery_dir(GALLERY_DIR)

    # Config
    from src.app.config import init_config
    config_path = CONFIG_DIR / "config.json"
    init_config(config_path)

    # Fluent translator
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
    main()
