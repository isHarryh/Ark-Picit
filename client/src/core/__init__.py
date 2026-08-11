"""Core module: ArkPic painting model and helpers."""

from src.core.code import CodeError, CodeMismatchError, DecodedPic, decode, encode
from src.core.color import (
    hex_to_bgr,
    hex_to_rgb,
    normalize_hex,
    rgb_to_hex,
)
from src.core.pic import ArkPic
from src.core.rule import MAX_COLORS, MAX_SIZE, ArkPicRule, rule_hash
from src.core.rulesets import ALL_RULESETS, RuleCN2026Aug

__all__ = [
    "ArkPic",
    "ArkPicRule",
    "CodeError",
    "CodeMismatchError",
    "DecodedPic",
    "MAX_COLORS",
    "MAX_SIZE",
    "rule_hash",
    "encode",
    "decode",
    "normalize_hex",
    "hex_to_rgb",
    "rgb_to_hex",
    "hex_to_bgr",
    "RuleCN2026Aug",
    "ALL_RULESETS",
]
