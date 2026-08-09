"""Settings page: theme and about."""

from qfluentwidgets import (
    FluentIcon as FIF,
)
from qfluentwidgets import (
    OptionsSettingCard,
    SettingCardGroup,
    Theme,
    qconfig,
    setTheme,
)

from src.app.config import cfg
from src.gui.components.base_page import BasePage


class SettingsPage(BasePage):
    """Application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        # --- Appearance ---
        self.appearanceGroup = SettingCardGroup("Appearance", self)

        self.themeCard = OptionsSettingCard(
            cfg().themeMode,
            FIF.BRUSH,
            "Theme",
            "Choose application color theme",
            texts=["Light", "Dark", "Use system setting"],
        )

        self.appearanceGroup.addSettingCard(self.themeCard)
        self.viewLayout.addWidget(self.appearanceGroup)

        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.themeCard.optionChanged.connect(self._apply_theme)

    def _apply_theme(self, _key) -> None:
        theme_value = qconfig.get(cfg().themeMode)
        if theme_value == Theme.LIGHT:
            setTheme(Theme.LIGHT)
        elif theme_value == Theme.DARK:
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)
