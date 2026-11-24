"""The browser receipt code (recall/site/static/receipt.js) must give the same answers as recall/receipt.py.

Two parts. The first runs on SYNTHETIC input that is part of the repository and always runs (when Node is
installed). The second runs on the real receipts in ~/receipts-lidl (or $RECEIPTS_DIR): every receipt is
parsed by both, every distinct description is turned into a phrase by both, and a fixed sample of lines is
matched against real recall records by both. Real receipts are private and never in git, so that part is
skipped where they are missing (for example on GitHub).
"""
import json
import os
import random
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_match import SPINACH, record
from test_receipt import HAM, MINCE, STRAWBERRY, TEXT, ZAUBERFLEKS, sold_at

from recall import config, receipt
from recall.site import lexicon_json, record_json

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR") or Path.home() / "receipts-lidl")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

RECORDS = [
    sold_at(SPINACH, "Kaufland", first_published="2026-01-08"),
    ZAUBERFLEKS,
    MINCE,
    HAM,
    STRAWBERRY,
    sold_at(record("Bio Basmati Reis", brand=["Golden Sun"], best_before=["2025-03", "2025-01-10..2025-02-01"], notice_id="b1"),
            "Aldi Nord", "Aldi Süd", first_published="2025-01-05"),
    sold_at(record("Mineralwasser still", best_before=["alle"], notice_id="w1"), "Edeka", "Marktkauf", first_published="2026-10-01"),
    sold_at(record("Knoblauch", best_before=["..2027-05-31"], notice_id="k1"), first_published="2026-11-01"),
]
# SYNTHETIC receipt lines, written by hand or by receipt.synthetic_line
DESCRIPTIONS = [
    "Spinat gehackt", "Rinderhackfleisch", "Zauberfl. Schoko", "Pfeffer-Schinkenbr.", "Testartikel-0000000", "Wasser still",
    "Vollk.Bröt. m.Jogh.", "Hähn.-Schnitzel 400g", "SpinatGehackt 1,5%", "Erdbeeren Schokolade", "Erdbeeren Schokolad",
    "Kölln Zauberfleks", "Basmati Reis", "Bio Basmati Reis 1kg", "Mineralw. still 1,5l", "Knobl. 3er Netz", "Fr.Eier a.Bodenh.",
    "Dr. Test", "ÄPFEL ROT,süß", "Crème fraîche 30%", "Zau. Schoko", "", "  ", "12345", "x",
    receipt.synthetic_line(SPINACH, "K-Classic Spinat gehackt, erntefrisch tiefgefroren"),
    receipt.synthetic_line(HAM, "Pfeffer-Schinkenbraten geschnitten"),
]
TEXTS = [
    TEXT,
    "\n".join(line.strip() for line in TEXT.split("\n")),
    TEXT.replace("\n", "\r\n"),
    TEXT.replace("1,29 A", "1,39 A"),
    "Spinat gehackt 1,29\nSUMME 1,29\nRinderhackfleisch\n\n12\nBar 5,00\nREWE Markt GmbH\n07.11.26 09:05",
    "Spinat gehackt\t1,29 A\nzu zahlen 1,29",
    "",
]
STORE_LINES = [[" MWST%       MWST  +   Netto  =  Brutto"], ["Netto Marken-Discount", "x"], ["dm-drogerie markt"], ["HIT", "hit"],
               ["Kaufland und ALDI SÜD"], ["denn's Biomarkt"], ["Pennymarkt"], []]
DATE_TEXTS = ["07.11.2026   16:42   T-ID 000000", "Musterstadt 07.11.26 16:42", "MHD 07.11.2026", "31.13.2026 10:00", ""]
# SYNTHETIC: made-up lines with the misreadings that text recognition produced on pictures of receipt text
OCR_TEXTS = [
    "Spinat gehackt                     1,29 8\nRinderhackfleisch                 3;995\n  0,500 kg x 7,98   EUR/kg\n"
    "     Lidl Plus Rabatt            -=0,40\nZauberfl. Schoko      2,49 x   2    4.98: A\n     Preisvorteil      =0,30\n"
    "Wasser still          0,25 x   6    1,50 BB\nPfand 0,25 EM         0,25 x   6    0,258\nPfandrückgabe      =0:753\n"
    "    -3 x 0,25\nSalat                0,79 =\nBrot  1,19 a\nzu zahlen                         11,36\nMWST% 7 %\n",
    "kein Preis hier\nSumme 12\n\nA  7 %       0,72      10,34      11,06",
    "",
]
SHOPS = ["", "Lidl", "Kaufland", "Aldi", "Aldi Nord", "Edeka"]
DATES = ["", "2024-06-01", "2025-01-12", "2025-01-13", "2025-04-01", "2026-01-15", "2026-01-16", "2026-11-07"]


def _run(cases: dict, tmp_path: Path) -> dict:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    static = ROOT / "recall" / "site" / "static"
    run = subprocess.run([NODE, ROOT / "tests" / "js" / "receipt_parity.mjs", static / "match.js", static / "receipt.js", path],
                         capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def _same_number(a, b):
    return a == pytest.approx(b, abs=0.051) if isinstance(a, float) or isinstance(b, float) else a == b


def _assert_same_hit(want, got, label):
    if want is None:
        assert got is None, label
        return
    assert got is not None, label
    assert got["score"] == pytest.approx(want["score"], abs=0.051), label
    assert {k: v for k, v in got.items() if k != "score"} == {k: v for k, v in want.items() if k != "score"}, label


def test_browser_receipt_code_gives_the_same_answers_on_synthetic_input(tmp_path):
    lines = [[d, r, s, w, None, m] for d in DESCRIPTIONS for r in range(len(RECORDS))
             for s, w, m in (("", "", None), ("Lidl", "2026-01-16", None), ("Aldi", "2025-04-01", 65.0))]
    lines += [["Zbfl. Sch.", 1, "", "", "Zauberfleks Schoko", None], ["Zbfl. Sch.", 1, "", "", "Zauberfl. Schok.", None]]
    narrow = [[r, s, w] for r in range(len(RECORDS)) for s in SHOPS for w in DATES]
    receipts = [[t, s, w] for t in range(len(TEXTS)) for s, w in ((None, None), ("Lidl", "2026-01-10"), ("Kaufland", ""))]
    js = _run({"lexicon": lexicon_json(), "records": [record_json(r) for r in RECORDS], "texts": TEXTS,
               "descriptions": DESCRIPTIONS, "store_lines": STORE_LINES, "date_texts": DATE_TEXTS, "ocr_texts": OCR_TEXTS,
               "narrow": narrow, "lines": lines, "receipts": receipts}, tmp_path)

    assert js["parsed"] == [receipt.parse(t) for t in TEXTS]
    assert js["pieces"] == [[list(p) for p in receipt.pieces(d)] for d in DESCRIPTIONS]
    assert js["phrases"] == [receipt.phrase(d) for d in DESCRIPTIONS]
    assert js["stores"] == [receipt.find_store(lines_) for lines_ in STORE_LINES]
    assert js["dates"] == [receipt.find_date(t) for t in DATE_TEXTS]
    assert js["repaired"] == [receipt.repair_ocr(t) for t in OCR_TEXTS]
    assert js["narrowed"] == [receipt.narrow(RECORDS[r], s, w) for r, s, w in narrow]
    python_hits = [receipt.match_line(d, RECORDS[r], s, w, t, receipt.POSSIBLE if m is None else m) for d, r, s, w, t, m in lines]
    assert sum(1 for hit in python_hits if hit) >= 20, "the cases should produce real matches"
    for case, want, got in zip(lines, python_hits, js["lines"]):
        _assert_same_hit(want, got, str(case))
    for (t, s, w), got in zip(receipts, js["receipts"]):
        want = receipt.match_receipt(receipt.parse(TEXTS[t]), RECORDS, s, w)
        assert len(got) == len(want), (t, s, w)
        for a, b in zip(want, got):
            _assert_same_hit(a, b, (t, s, w))


@pytest.mark.skipif(not (RECEIPTS / "clean").is_dir(), reason="the private receipt archive is not on this machine")
def test_browser_receipt_code_gives_the_same_answers_on_the_real_receipts(tmp_path):
    texts = [path.read_text(encoding="utf-8") for path in sorted((RECEIPTS / "clean").glob("*.txt"))]
    parsed = [receipt.parse(t) for t in texts]
    descriptions = sorted({i["description"] for p in parsed for i in p["items"]})
    cases = {"lexicon": lexicon_json(), "records": [], "texts": texts, "descriptions": descriptions}
    lines = []
    if config.DB_PATH.exists():  # real recall records, when the database is on this machine too
        from recall.web.data import _load_records

        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        records = _load_records(conn)
        conn.close()
        cases["records"] = [record_json(r) for r in records]
        sample = random.Random(1).sample(descriptions, 40)
        lines = [[d, r, "Lidl", "2025-06-01", None, 65.0] for d in sample for r in range(len(records))]
        cases["lines"] = lines
    js = _run(cases, tmp_path)

    assert len(texts) >= 500
    assert js["parsed"] == parsed
    assert js["pieces"] == [[list(p) for p in receipt.pieces(d)] for d in descriptions]
    assert js["phrases"] == [receipt.phrase(d) for d in descriptions]
    for case, got in zip(lines, js.get("lines", [])):
        d, r, s, w, t, m = case
        _assert_same_hit(receipt.match_line(d, records[r], s, w, t, m), got, f"{d} x {records[r].id}")
