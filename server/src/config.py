"""Server configuration loaded from ``config.toml`` in the server data directory.

The config file is required and lives at ``<cwd>/data/arkpicit_server_v1/config.toml``;
the server refuses to start without it. ``load_config`` is called once at startup and
the resulting settings are served through :func:`get_config`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .code import MAX_CONTENT_CHARS
from .models import ALL_STATUSES

DATA_DIR = Path.cwd() / "data" / "arkpicit_server_v1"
CONFIG_FILE = DATA_DIR / "config.toml"

_REQUIRED_FIELDS = ("port", "admin_token", "upload_default_status")


@dataclass(frozen=True)
class ServerConfig:
    """Runtime settings for the plaza server."""

    host: str
    port: int
    admin_token: str
    upload_default_status: int
    max_payload_length: int
    max_page_size: int
    max_rate_credits_per_ip_per_m: int
    max_rate_credits_per_ip_per_h: int


_config: ServerConfig | None = None


def load_config() -> ServerConfig:
    """Load *CONFIG_FILE* into the process-global config; raises on any problem."""
    global _config
    try:
        with CONFIG_FILE.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise RuntimeError(
            f"Config file not found: {CONFIG_FILE}\n"
            f"Create it with the required fields: {', '.join(_REQUIRED_FIELDS)}"
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Invalid TOML in config file: {CONFIG_FILE}\n{exc}") from exc

    missing = [field for field in _REQUIRED_FIELDS if data.get(field) is None]
    if missing:
        raise RuntimeError(
            f"Config file is missing required fields: {', '.join(missing)}"
        )

    admin_token = str(data["admin_token"]).strip()
    if not admin_token:
        raise RuntimeError("admin_token must not be empty")
    status = data["upload_default_status"]
    if status not in ALL_STATUSES:
        raise RuntimeError(f"upload_default_status must be one of {list(ALL_STATUSES)}, got {status!r}")
    port = data["port"]
    if not isinstance(port, int) or isinstance(port, bool):
        raise RuntimeError(f"port must be an integer, got {port!r}")

    _config = ServerConfig(
        host=str(data.get("host", "0.0.0.0")),
        port=port,
        admin_token=admin_token,
        upload_default_status=status,
        max_payload_length=_optional_int(data, "max_payload_length", MAX_CONTENT_CHARS),
        max_page_size=_optional_int(data, "max_page_size", 50),
        max_rate_credits_per_ip_per_m=_optional_int(data, "max_rate_credits_per_ip_per_m", 64),
        max_rate_credits_per_ip_per_h=_optional_int(data, "max_rate_credits_per_ip_per_h", 1024),
    )
    return _config


def _optional_int(data: dict, key: str, default: int) -> int:
    """Return *key* as a positive int, or *default* when the key is absent."""
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError(f"{key} must be a positive integer, got {value!r}")
    return value


def get_config() -> ServerConfig:
    """Return the loaded config, raising if :func:`load_config` was not called."""
    if _config is None:
        raise RuntimeError("Server config not loaded; call load_config() at startup")
    return _config
