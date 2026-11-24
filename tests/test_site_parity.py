"""The browser matcher (recall/site/static/match.js) must give the same answers as the Python code.

Every product x recall pair below goes through recall/match.py and through match.js (run by Node);
scores, levels, reasons and verdicts must agree. Skipped when Node is not installed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from rapidfuzz import fuzz
from test_match import SPINACH, record

from recall import match, normalise
from recall.site import lexicon_json, record_json
from recall.textutils import find_dates

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

RECORDS = [
    SPINACH,
    record("Rinderhackfleisch", batch=["DE1505453906"], notice_id="r2"),
    record("Schweinehackfleisch", notice_id="r3"),
    record("EDEKA Bio Wildheidelbeeren tiefgefroren", brand=["EDEKA Bio"], best_before=["alle"], notice_id="r4"),
    record("Alnatura Pinienkerne", brand=["Alnatura"], best_before=["2027-05-31..2027-07-02", "..2026-11-17"], notice_id="r5"),
    record("Kölln Zauberfleks Schoko", brand=["Kölln"], batch=["L6165", "LG262 bis LG292"],
           best_before=["2027-04-17", "2027-06"], manufacturer=["Peter Kölln GmbH & Co. KGaA"], notice_id="r6",
           title="Kölln Zauberfleks Schoko - 375 Gramm"),
    record("Dinkel Spaghetti mit Wildkräutern", manufacturer=["Hennererhof"], best_before=["2028-07"], notice_id="r7",
           title="Dinkel Spaghetti mit Wildkräutern, 500 Gramm"),
    record("GUT&GÜNSTIG Himbeeren tiefgefroren", brand=["GUT&GÜNSTIG"], batch=["L050826 DP"], notice_id="r8"),
    record("Weichkäse „Zickenblues“", notice_id="r9"),
]
PRODUCTS = [
    {"name": "Spinat gehackt", "brand": "K Classic", "best_before": "31.10.2027"},
    {"name": "Blattspinat", "brand": "Iglo"},
    {"name": "Spinat"},
    {"name": "Haferflocken", "brand": "K-Classic"},
    {"name": "Gemüse", "brand": "x", "ean": "4337185811425"},
    {"name": "Hackfleisch vom Rind"},
    {"name": "Rinderhackfleisch", "batch": "de 1505453906"},
    {"name": "Himbeeren tiefgefroren", "brand": "Gut & Günstig", "batch": "L050826DP"},
    {"name": "Himbeeren"},
    {"name": "Pinienkerne", "brand": "Alnatura", "best_before": "15.06.2027"},
    {"name": "Pinienkerne", "best_before": "03.07.2027"},
    {"name": "Zauberfleks Schoko", "brand": "Kölln", "batch": "LG270", "best_before": "Juni 2027"},
    {"name": "Zauberfleks", "brand": "Peter Kölln", "best_before": "2027-04-17"},
    {"name": "Spaghetti", "brand": "Barilla"},
    {"name": "Weichkäse", "best_before": "12/2026"},
    {"name": "Käse"},
]
TEXTS = ["K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm", "Royal Honey-The Ultimate Power Source, 12x20 Gramm",
         "Bio Wildreis Basmati Reis Mix, 0,6 und 3 Kilogramm", "Mini Brie mit Nuss", "Weichkäse „Zickenblues“, 6x0,33 l",
         "GUT&GÜNSTIG Crunchy Peanut Ice Cream in der 6x53 Milliliter-Verpackung", "Süßkartoffel-Pommes 750g",
         "Cholin 600 mg, ZeinPharma, 50 Gramm/60 Kapseln", "Bio Brennnessel, Bünting Tee, 20 Aufgussbeutel á 2 Gramm",
         "Root Beer 12 oz je 355 ml", "Reis 5 Kilogramm / 10 Kilogramm Sack", "Tee 40 Teebeutel à 1,75 g"]
WORDS = ["rinderhackfleisch", "weichkaese", "pinienkerne", "himbeeren", "schwein", "bratolivenoel", "kreuzkuemmel",
         "gewuerzmischung", "spinat", "wildheidelbeeren", "kraeutertee", "frischkaese"]
BRANDS = ["Gut&Günstig", "GUT & GÜNSTIG", "gut und günstig", "K Classic", "Kaufland K-Classic", "Zörbiger", "ja!", "REWE Beste Wahl"]
DATE_INPUTS = ["31.10.2027", "31/10/27", "2027-10-31", "10/2027", "10.2027", "Oktober 2027", "3. März 2028", "MHD: 1.2.2028", "07-2028", "abc"]
RATIO_PAIRS = [("himbeeren", "heidelbeeren"), ("rinderhackfleisch", "schweinehackfleisch"), ("spinat", "spinatt"), ("", "")]


def _python_answers(products, records):
    answers = []
    for p, r in PAIRS:
        found = match.match_product(products[p], records[r])
        answers.append(found and {"score": found.score, "level": found.level, "reason": found.reason,
                                  "recall_name": found.recall_name, "identifiers": found.identifiers})
    return answers


PAIRS = [(p, r) for p in range(len(PRODUCTS)) for r in range(len(RECORDS))]


def test_browser_matcher_gives_the_same_answers_as_python(tmp_path):
    products = [match.MyProduct(row=1, **p) for p in PRODUCTS]
    cases = {
        "lexicon": lexicon_json(), "records": [record_json(r) for r in RECORDS], "products": PRODUCTS, "pairs": PAIRS,
        "texts": TEXTS, "words": WORDS, "brands": BRANDS, "date_inputs": DATE_INPUTS, "ratio_pairs": RATIO_PAIRS,
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    run = subprocess.run([NODE, ROOT / "tests" / "js" / "parity.mjs", ROOT / "recall" / "site" / "static" / "match.js", path],
                         capture_output=True, text=True, check=True)
    js = json.loads(run.stdout)

    assert js["tokens"] == [normalise.tokens(t) for t in TEXTS]
    assert js["splits"] == [normalise.split_compound(w) for w in WORDS]
    assert js["brand_keys"] == [normalise.brand_key(b) for b in BRANDS]
    assert js["dates"] == [[d.iso for d in find_dates(t)] for t in DATE_INPUTS]
    assert js["ratios"] == pytest.approx([fuzz.ratio(a, b) for a, b in RATIO_PAIRS])

    python = _python_answers(products, RECORDS)
    assert sum(1 for a in python if a) >= 10, "the cases should produce real matches"
    for (p, r), want, got in zip(PAIRS, python, js["matches"]):
        label = f"{PRODUCTS[p]} x {RECORDS[r].id}"
        if want is None:
            assert got is None, label
            continue
        assert got is not None, label
        assert got["score"] == pytest.approx(want["score"], abs=0.051), label
        assert (got["level"], got["reason"], got["recall_name"]) == (want["level"], want["reason"], want["recall_name"]), label
        assert got["identifiers"] == want["identifiers"], label
