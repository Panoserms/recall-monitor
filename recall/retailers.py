"""Which shop a recalled product came from, and how a page shows it.

    shops(sellers)  how a recall page or list row shows the notice's sellers:
                    "single"  one named seller: a chip with its name, and its colour band if it has a style
                    "several" one chip per seller, neutral page (no band)
                    "none"    "Shop not named in the notice"
    style(name)     the colour style of a retailer from lexicons/retailer_style.json, or None (neutral)

A colour is only used when the retailer publishes it itself (see the file). It is never set behind text unless
the pair reaches WCAG AA, and never if it could be mistaken for a verdict colour (orange = affected,
emerald = not affected). tests/test_retailers.py checks both for every retailer in the file.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .normalise import fold

STYLE_FILE = Path(__file__).resolve().parent / "lexicons" / "retailer_style.json"

# The site's own colours (recall/web/static/style.css), light and dark
INK, INK_DARK = "#13294b", "#e8edf5"
SURFACE, SURFACE_DARK = "#ffffff", "#15233a"
VERDICT_COLOURS = {"affected (light)": "#b83a0b", "affected (dark)": "#f08a4b", "not affected (light)": "#047857",
                   "not affected (dark)": "#3ccf98", "affected wash": "#fbe9dd", "not affected wash": "#dcf2e8"}
AA = 4.5
MIN_DISTANCE = 25.0  # CIE76 colour difference an accent keeps from every verdict colour


# ------------------------------------------------------------------- colour

def _rgb(hex_colour: str) -> tuple[float, float, float]:
    value = hex_colour.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (_linear(c) for c in _rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _lab(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _rgb(hex_colour))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def distance(a: str, b: str) -> float:
    """CIE76 colour difference (about 2.3 is just noticeable; 25 is clearly another colour)."""
    return math.dist(_lab(a), _lab(b))


def mix(colour: str, other: str, share: float) -> str:
    """`share` of `colour` mixed into `other` (sRGB), as #rrggbb."""
    return "#" + "".join(f"{round(255 * (share * a + (1 - share) * b)):02x}" for a, b in zip(_rgb(colour), _rgb(other)))


# -------------------------------------------------------------------- styles

def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


@lru_cache(maxsize=1)
def _file() -> dict:
    return json.loads(STYLE_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def style(name: str) -> dict | None:
    """The colour style of a retailer, or None for the neutral style.
    accent    the declared colour, used for the band and the swatch (decoration only)
    on_accent ink or white, whichever reads better on the accent; None when neither reaches AA (then no text on it)
    tint      the accent mixed into white, for the chip background in light mode (ink on it reaches AA)
    tint_dark the accent mixed into the dark surface, for dark mode"""
    entry = _file()["retailers"].get(name)
    if not entry or not entry.get("accent"):
        return None
    accent = entry["accent"].lower()
    if min(distance(accent, verdict) for verdict in VERDICT_COLOURS.values()) < MIN_DISTANCE:
        return None  # too close to a verdict colour: neutral instead
    on = max((INK, "#ffffff"), key=lambda c: contrast(accent, c))
    tint = next(t for t in (mix(accent, "#ffffff", s) for s in (0.22, 0.16, 0.1, 0.05)) if contrast(INK, t) >= AA)
    tint_dark = next(t for t in (mix(accent, SURFACE_DARK, s) for s in (0.28, 0.2, 0.12, 0.06)) if contrast(INK_DARK, t) >= AA)
    return {
        "name": name, "slug": slug(name), "accent": accent, "on_accent": on if contrast(accent, on) >= AA else None,
        "tint": tint, "tint_dark": tint_dark, "source_url": entry["source_url"], "checked_on": entry["checked_on"],
    }


def styles() -> list[dict]:
    return [s for s in (style(name) for name in _file()["retailers"]) if s]


def shops(sellers: list[str]) -> dict:
    """How a notice's sellers are shown. chips: [{"name", "slug" or ""}] in the notice's order."""
    chips = [{"name": seller, "slug": (style(seller) or {}).get("slug", "")} for seller in sellers]
    if not chips:
        return {"mode": "none", "chips": [], "band": None}
    if len(chips) == 1:
        return {"mode": "single", "chips": chips, "band": style(sellers[0])}
    return {"mode": "several", "chips": chips, "band": None}


def stylesheet() -> str:
    """static/shops.css: one class per styled retailer. Colours are set as custom properties, used by site.css."""
    rules = ["/* Generated by recall build-site from recall/lexicons/retailer_style.json. Do not edit. */"]
    for s in styles():
        rules.append(f".shop--{s['slug']} {{ --shop-accent: {s['accent']}; --shop-tint: {s['tint']}; }}")
        rules.append(f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) .shop--{s['slug']} {{ --shop-tint: {s['tint_dark']}; }} }}")
        rules.append(f":root[data-theme=\"dark\"] .shop--{s['slug']} {{ --shop-tint: {s['tint_dark']}; }}")
    return "\n".join(rules) + "\n"


def browser_json() -> dict:
    """For site.js and receipt-page.js: shop name -> class slug, for styled retailers only."""
    return {s["name"]: s["slug"] for s in styles()}
