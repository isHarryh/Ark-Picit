"""Predefined ArkPicRule sets shipped with Ark Picit."""

from src.core.rule import ArkPicRule

# 40 colors, 4-per-row grouped by hue family (grayscale, red, pink, beige,
# orange, yellow/green, brown, dark-blue, light-blue, teal/blue).
_CN_2026_AUG_COLORS = [
    # grayscale
    "222222", "B4B4B4", "EAE7DF", "FFFFFF",
    # red
    "D32F36", "9C0A00", "D60C4A", "E6968D",
    # pink / skin
    "FE9875", "F7D0C0", "FCEFEA", "FBF6E8",
    # beige
    "DCD2C8", "E2CEAB", "D56322", "D48C42",
    # orange / yellow
    "F29900", "F9C933", "FCE499", "B3B47A",
    # green
    "C2DA72", "6C6E00", "B19155", "A98F74",
    # brown
    "A38C26", "3F2B12", "74491F", "534658",
    # dark blue / purple
    "2A2446", "394599", "5A459D", "BAA3D7",
    # light blue / grey-blue
    "B6BCDF", "A9ACBE", "63ABB9", "B4D2DC",
    # teal / deep blue
    "91D8E6", "47AEA0", "B6D3C8", "273864",
]

RuleCN2026Aug = ArkPicRule(
    width=24,
    height=24,
    colors=_CN_2026_AUG_COLORS,
    default_color_id=4,  # white (FFFFFF)
)

ALL_RULESETS: dict[str, ArkPicRule] = {
    "CN2026Aug": RuleCN2026Aug,
}
