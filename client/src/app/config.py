"""Application configuration backed by qfluentwidgets QConfig (JSON)."""

from pathlib import Path

from qfluentwidgets import (
    ConfigItem,
    EnumSerializer,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    Theme,
    qconfig,
)

from src.app.dist import default_api_server


class AppConfig(QConfig):
    """Holds all persistent user preferences."""

    # Appearance
    themeMode = OptionsConfigItem(
        "Appearance", "ThemeMode", Theme.AUTO,
        OptionsValidator([Theme.LIGHT, Theme.DARK, Theme.AUTO]),
        EnumSerializer(Theme),
    )
    language = OptionsConfigItem(
        "Appearance", "Language", "system",
        OptionsValidator(["system", "en", "zh-CN"]),
        restart=True,
    )

    # API (explore server)
    exploreServerUrl = ConfigItem("API", "ExploreServerUrl", default_api_server())
    exploreToken = ConfigItem("API", "ExploreToken", "")
    exploreClientToken = ConfigItem("API", "ExploreClientToken", "")
    announcementHash = ConfigItem("API", "AnnouncementHash", "")
    networkEnabled = ConfigItem("API", "NetworkEnabled", True)


# ---------------------------------------------------------------------------
# Singleton bootstrap
# ---------------------------------------------------------------------------

_config_instance: AppConfig | None = None


def init_config(config_path: Path) -> AppConfig:
    """Create the singleton AppConfig and load from *config_path*."""
    global _config_instance
    _config_instance = AppConfig()
    _config_instance.file = config_path
    qconfig.load(config_path, _config_instance)
    return _config_instance


def cfg() -> AppConfig:
    """Return the initialized config singleton."""
    global _config_instance
    if _config_instance is None:
        raise RuntimeError("AppConfig not initialized. Call init_config() first.")
    return _config_instance
