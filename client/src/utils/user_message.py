"""Localizable message produced by non-GUI layers.

Core tasks and exceptions never emit natural-language UI text directly;
they report a stable message code with formatting parameters. The GUI
layer translates ``code`` with ``params``; ``technical_detail`` carries
the raw diagnostic text (exception, adb output, screenshot path) that is
kept for logs and as a fallback when no translation exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class UserMessage:
    """A user-facing message described by a stable ``code`` and ``params``."""

    code: str
    params: Mapping[str, object] = field(default_factory=dict)
    technical_detail: str = ""
