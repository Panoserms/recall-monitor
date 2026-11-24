"""Retailer identity: colours only from the retailer's own declaration, readable, never mistaken for a verdict."""
import json
import re

import pytest

from recall import retailers
from recall.retailers import AA, INK, INK_DARK, MIN_DISTANCE, VERDICT_COLOURS, contrast, distance

DATA = json.loads(retailers.STYLE_FILE.read_text(encoding="utf-8"))
ENTRIES = DATA["retailers"]
STYLED = retailers.styles()


def test_contrast_formula_matches_known_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)  # the classic "just fails AA" grey
    assert distance("#ffffff", "#ffffff") == 0


def test_every_retailer_in_the_file_is_a_shop_of_the_lexicon():
    from recall import lexicons

    shops = {row[0] for row in lexicons.load("retailers.tsv")}
    assert set(ENTRIES) <= shops


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_a_colour_is_used_only_with_its_source_and_date(name):
    entry = ENTRIES[name]
    assert entry["source_url"].startswith("https://") and re.fullmatch(r"\d{4}-\d\d-\d\d", entry["checked_on"])
    if entry.get("accent"):
        assert entry["status"] == "declared on own website"
        assert entry["accent"].lower() in entry["evidence"].lower()  # the value is the one the page declares
    else:
        assert entry["status"] == "not found" and retailers.style(name) is None


@pytest.mark.parametrize("style", STYLED, ids=[s["name"] for s in STYLED])
def test_text_on_retailer_colours_reaches_wcag_aa_in_light_and_dark_mode(style):
    assert contrast(INK, style["tint"]) >= AA  # chip text on the light tint
    assert contrast(INK_DARK, style["tint_dark"]) >= AA  # chip text in dark mode
    if style["on_accent"]:
        assert contrast(style["accent"], style["on_accent"]) >= AA


@pytest.mark.parametrize("style", STYLED, ids=[s["name"] for s in STYLED])
def test_retailer_colours_stay_clearly_apart_from_the_verdict_colours(style):
    for meaning, colour in VERDICT_COLOURS.items():
        assert distance(style["accent"], colour) >= MIN_DISTANCE, meaning


def test_a_colour_too_close_to_a_verdict_colour_falls_back_to_neutral(monkeypatch):
    fake = {**DATA, "retailers": {**ENTRIES, "Lidl": {**ENTRIES["Lidl"], "accent": "#b9400f", "evidence": "#b9400f"}}}
    monkeypatch.setattr(retailers, "_file", lambda: fake)
    retailers.style.cache_clear()
    try:
        assert retailers.style("Lidl") is None
    finally:
        retailers.style.cache_clear()


def test_the_four_shops_with_a_declared_colour_are_styled_and_the_others_neutral():
    assert {s["name"] for s in STYLED} == {"Lidl", "Aldi Nord", "Denns BioMarkt", "Combi"}
    assert retailers.style("Kaufland") is None and retailers.style("Amazon") is None and retailers.style("Langenfeld") is None


def test_one_shop_gets_a_band_several_shops_get_chips_none_gets_a_sentence():
    single = retailers.shops(["Lidl"])
    assert single["mode"] == "single" and single["band"]["slug"] == "lidl"
    assert retailers.shops(["Kaufland"])["band"] is None  # named, but no declared colour: chip only
    several = retailers.shops(["Kaufland", "Edeka", "Aldi Nord"])
    assert several["mode"] == "several" and several["band"] is None
    assert [c["slug"] for c in several["chips"]] == ["", "", "aldi-nord"]
    assert retailers.shops([]) == {"mode": "none", "chips": [], "band": None}


def test_stylesheet_has_one_rule_per_styled_shop_and_nothing_else():
    css = retailers.stylesheet()
    assert css.count("--shop-accent") == len(STYLED)
    assert "url(" not in css and "http" not in css
