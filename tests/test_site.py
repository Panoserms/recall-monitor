"""The public website build: static pages, the official text in full, nothing external, no removed notices."""
import json
import re

import pytest
from conftest import RAW
from test_extract import SALAMI, _loaded

from recall import extract, site


@pytest.fixture
def built(conn, feed_bytes, page_bytes, nlp, tmp_path):
    _loaded(conn, feed_bytes)
    extract.run(conn, RAW, nlp=nlp)  # every notice of the real feed of 2026-11-11, the salami one with its page
    out = tmp_path / "public"
    counts = site.build(conn, RAW, out, settings={"base_path": "/recall-monitor/"})
    return conn, out, counts


def test_every_current_recall_gets_a_page(built):
    conn, out, counts = built
    active = conn.execute("SELECT COUNT(*) FROM notices WHERE active = 1").fetchone()[0]
    assert counts["recalls"] == active
    assert len(list((out / "recall").glob("*.html"))) == active
    assert (out / "index.html").exists() and (out / "products.html").exists() and (out / "about.html").exists()


def test_recall_page_shows_the_official_text_in_full(built):
    _, out, _ = built
    html = (out / "recall" / f"{SALAMI}.html").read_text(encoding="utf-8")
    assert "The official notice" in html
    assert "Weitere Informationen" in html and "STEC" in html  # only on the page, not in the feed
    assert "lebensmittelwarnung.de" in html


def test_data_for_the_browser_matcher(built):
    _, out, counts = built
    data = json.loads((out / "data" / "recalls.json").read_text(encoding="utf-8"))
    assert len(data["recalls"]) == counts["recalls"]
    first = data["recalls"][0]
    assert {"id", "title", "product_name", "brand", "batch", "best_before", "ean", "what_to_do"} <= set(first)
    lexicon = json.loads((out / "data" / "lexicon.json").read_text(encoding="utf-8"))
    assert "kaese" in lexicon["food_words"] and lexicon["brand_aliases"]


def test_nothing_is_loaded_from_other_servers(built):
    _, out, _ = built
    for path in [*out.glob("*.html"), *out.glob("static/*.css"), *out.glob("static/*.js")]:
        text = path.read_text(encoding="utf-8")
        # links (<a href>) to other sites are fine; loading anything (src, stylesheet, url(), fetch) is not
        assert not re.search(r'(?:src|srcset)="https?://', text), path.name
        assert not re.search(r'<link[^>]+href="https?://', text), path.name
        assert not re.search(r"url\(\s*['\"]?https?://", text), path.name
        assert "googleapis" not in text and "gstatic" not in text, path.name


def test_removed_notices_are_not_built(conn, feed_bytes, page_bytes, nlp, tmp_path):
    _loaded(conn, feed_bytes)
    extract.run(conn, RAW, nlp=nlp, only=[SALAMI])
    conn.execute("UPDATE notices SET active = 0 WHERE id = ?", (SALAMI,))
    out = tmp_path / "public"
    site.build(conn, RAW, out)
    assert not (out / "recall" / f"{SALAMI}.html").exists()
    assert SALAMI not in (out / "data" / "recalls.json").read_text(encoding="utf-8")


def test_public_build_needs_an_impressum(conn, tmp_path):
    with pytest.raises(site.NotReady, match="Impressum"):
        site.build(conn, RAW, tmp_path / "public", settings={"impressum": {"name": "", "address": []}}, public=True)
    assert not (tmp_path / "public").exists()


def test_impressum_appears_when_filled_in(conn, feed_bytes, tmp_path):
    _loaded(conn, feed_bytes, page_version=None)
    settings = {"impressum": {"name": "Erika Mustermann", "address": ["Musterstraße 1", "12345 Musterstadt"], "email": ""}}
    out = tmp_path / "public"
    site.build(conn, RAW, out, settings=settings, public=True)
    about = (out / "about.html").read_text(encoding="utf-8")
    assert "Impressum" in about and "Erika Mustermann" in about and "12345 Musterstadt" in about


def test_public_site_strips_model_sourced_fields(conn, feed_bytes, page_bytes, nlp, tmp_path):
    _loaded(conn, feed_bytes)
    extract.run(conn, RAW, nlp=nlp, only=[SALAMI])
    conn.execute(
        "UPDATE fields SET value = ?, source = 'model', rule = 'model.gemma4' WHERE notice_id = ? AND field = 'brand'",
        ('["InventedBrand"]', SALAMI),
    )
    out = tmp_path / "public"
    site.build(conn, RAW, out)
    html = (out / "recall" / f"{SALAMI}.html").read_text(encoding="utf-8")
    recalls_json = (out / "data" / "recalls.json").read_text(encoding="utf-8")
    assert "src--model" not in html and "InventedBrand" not in html
    assert "InventedBrand" not in recalls_json



def test_receipt_page_and_its_reading_libraries_are_served_from_the_site(built):
    _, out, _ = built
    html = (out / "receipt.html").read_text(encoding="utf-8")
    assert "Check a receipt" in html and "Nothing is uploaded" in html
    assert 'href="receipt.html"' in (out / "index.html").read_text(encoding="utf-8")  # in the navigation
    for path in ("static/receipt.js", "static/receipt-page.js", "static/vendor/pdfjs/pdf.min.mjs", "static/vendor/pdfjs/pdf.worker.min.mjs",
                 "static/vendor/tesseract/tesseract.min.js", "static/vendor/tesseract/worker.min.js",
                 "static/vendor/tesseract/core/tesseract-core-simd-lstm.wasm.js", "static/vendor/tesseract/core/tesseract-core-lstm.wasm.js",
                 "static/vendor/tesseract/lang/deu.traineddata.gz"):
        assert (out / path).is_file(), path
    page_js = (out / "static" / "receipt-page.js").read_text(encoding="utf-8")
    # the libraries' own defaults point to a CDN; the page must always give local paths instead
    for setting in ("workerPath:", "corePath:", "langPath:", "workerSrc ="):
        assert setting in page_js
    assert "http://" not in page_js and "https://" not in page_js


def test_example_receipt_is_marked_as_made_up_and_matches_a_current_recall(built):
    conn, out, _ = built
    from recall import receipt
    from recall.web.data import _load_records

    text = (out / "data" / "example_receipt.txt").read_text(encoding="utf-8")
    assert text.startswith("*** MADE-UP EXAMPLE, NOT A REAL RECEIPT ***")
    parsed = receipt.parse(text)
    assert parsed["layout"] == "lidl" and parsed["sums_match"] is True and parsed["store"] == "Lidl"
    assert receipt.match_receipt(parsed, _load_records(conn))


def test_shops_are_shown_by_name_without_logos_and_the_site_says_it_is_independent(built, tmp_path):
    conn, _, _ = built
    ids = [r["id"] for r in conn.execute("SELECT id FROM notices WHERE active = 1 ORDER BY id LIMIT 3")]
    for notice_id, sellers in zip(ids, ('["Lidl"]', '["Kaufland", "Edeka", "Aldi Nord"]', "[]")):
        conn.execute("UPDATE fields SET value = ?, source = 'rule' WHERE notice_id = ? AND field = 'sellers'", (sellers, notice_id))
    out = tmp_path / "shops"
    site.build(conn, RAW, out)
    single, several, none = ((out / "recall" / f"{i}.html").read_text(encoding="utf-8") for i in ids)
    assert 'notice__head notice__head--single shop-band shop--lidl"' in single and "shops--single" in single
    assert "shop-band" not in several and several.count('class="shop-chip') == 3 and 'class="shop-chip shop--aldi-nord"' in several
    assert "shop-band" not in none and "Shop not named in the notice" in none
    for html in (single, several, none):
        official = html[html.index('class="official__text"'):]
        assert "shop-chip" not in official and "shop--" not in official  # the notice itself is never restyled
        for chip in re.findall(r'<span class="shop-chip[^>]*>(.*?)</span>', html):
            assert "<img" not in chip and "<svg" not in chip
    for page in ("index.html", "about.html", "receipt.html"):
        assert "not affiliated with any shop" in (out / page).read_text(encoding="utf-8")
    assert "Independent of every shop" in (out / "about.html").read_text(encoding="utf-8")
    assert ".shop--lidl" in (out / "static" / "shops.css").read_text(encoding="utf-8")


def test_motion_moves_only_transform_and_opacity_and_respects_reduced_motion(built):
    _, out, _ = built
    motion = (out / "static" / "motion.js").read_text(encoding="utf-8")
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in motion
    for keyframes in re.findall(r"\.animate\(\s*(\[[^\]]*\])", motion):  # every keyframe list in the file
        assert set(re.findall(r"(\w+):", keyframes)) <= {"opacity", "transform"}, keyframes
    css = (out / "static" / "site.css").read_text(encoding="utf-8") + (out / "static" / "style.css").read_text(encoding="utf-8")
    for block in re.findall(r"@keyframes [\w-]+ \{(.*?)\}\s*\}?", css, re.S):
        assert not re.search(r"\b(?:top|left|right|bottom|width|height|margin|padding)\s*:", block), block
    assert "@view-transition { navigation: none; }" in css  # no page transition with reduced motion
    receipt = (out / "receipt.html").read_text(encoding="utf-8")
    assert "<video muted loop playsinline" in receipt and "autoplay" not in receipt  # motion.js starts it only on screen
    assert "data-story-toggle" in receipt and 'role="status"' in receipt
    for name in ("receipt-story.webm", "receipt-story.mp4", "receipt-story-poster.png"):
        assert (out / "static" / "media" / name).stat().st_size < 1_500_000
