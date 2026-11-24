"""Stage 5: match recalled products against your own product list.

Score (0-100), explained in the `reason` of every match:
    EAN       the barcode on your pack is one the notice lists               -> 100
    name      how many of your product's words the recall names, and back    (compounds split, see normalise.py)
    brand     same brand -> name * 0.6 + 40
              brand not named in the notice -> name * 0.85
              another brand -> at most 50, never an alert
    level     >= 80 "match", >= 65 "possible"; below that nothing is reported.
The weights and thresholds were set by hand on the test cases in tests/test_match.py,
not tuned on labelled data (there is no gold set for matching).

For every match, check_identifiers() compares the batch, best-before date and EAN you
wrote down with the ones the notice lists, or says which ones to look for on the pack.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from .models import Record
from .normalise import brand_key, split_compound, tokens
from .textutils import find_dates

MATCH, POSSIBLE = 80.0, 65.0
COLUMNS = ("name", "brand", "ean", "batch", "best_before", "note")


class MyProduct(BaseModel):
    row: int  # line in the product list, 1 = first product
    name: str
    brand: str = ""
    ean: str = ""
    batch: str = ""
    best_before: str = ""
    note: str = ""


class Match(BaseModel):
    product: MyProduct
    notice_id: str
    title: str
    link: str
    recall_name: str
    score: float
    reason: str
    identifiers: dict = Field(default_factory=dict)

    @property
    def level(self) -> Literal["match", "possible"]:
        return level_of(self.score)


def level_of(score: float) -> str:
    return "match" if score >= MATCH else "possible" if score >= POSSIBLE else "none"


# ---------------------------------------------------------------- product list

def load_products(path: Path) -> list[MyProduct]:
    """Your product list: a CSV with the columns name and brand; ean, batch, best_before and note are optional.
    Commas or semicolons (as a German spreadsheet saves it) both work."""
    text = path.read_text(encoding="utf-8-sig")
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    products = []
    for number, row in enumerate(csv.DictReader(text.splitlines(), delimiter=delimiter), start=1):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if row.get("name"):
            products.append(MyProduct(row=number, **{c: row.get(c, "") for c in COLUMNS}))
    return products


def save_products(path: Path, products: list[MyProduct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for product in products:
            writer.writerow({c: getattr(product, c) for c in COLUMNS})


# ------------------------------------------------------------------- names

def _same(a: str, b: str) -> bool:
    """Two folded words for the same thing: equal, an inflected form ("rind"/"rinder"), or a small typo."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 4 and long_.startswith(short) and len(long_) - len(short) <= 3:
        return True
    return min(len(a), len(b)) >= 5 and fuzz.ratio(a, b) >= 88


def _found(word: str, others: list[str]) -> float:
    """1 if the other name has the word (or a part of it), 0.5 if it has only the head of the compound."""
    pool = set(others) | {part for other in others for part in split_compound(other)}
    if any(_same(word, other) for other in pool):
        return 1.0
    parts = split_compound(word)
    if parts and any(_same(parts[1], other) for other in pool):
        return 1.0 if any(_same(parts[0], other) for other in pool) else 0.5
    return 0.0


def name_score(mine: list[str], theirs: list[str]) -> tuple[float, list[str]]:
    """(0-100, your words the recall shares). Three quarters: how much of your name the recall has;
    one quarter: how much of the recall's name yours has."""
    if not mine or not theirs:
        return 0.0, []
    found = [_found(word, theirs) for word in mine]
    back = mean(_found(word, mine) for word in theirs)
    return 100 * (0.75 * mean(found) + 0.25 * back), [w for w, f in zip(mine, found) if f]


def _without(words: list[str], remove: set[str]) -> list[str]:
    return [w for w in words if w not in remove]


# ------------------------------------------------------------------- brands

def _contains(words: list[str], part: list[str]) -> bool:
    return bool(part) and any(words[i : i + len(part)] == part for i in range(len(words) - len(part) + 1))


def brand_status(product: MyProduct, record: Record) -> tuple[str, str]:
    """("same" | "different" | "unknown", the recall's brand or company that decided it)."""
    if not product.brand.strip():
        return "unknown", ""
    key = brand_key(product.brand)
    for brand in record.values("brand"):
        theirs = brand_key(brand)
        if key == theirs or (len(key) >= 4 and (key in theirs or theirs in key)):
            return "same", brand
    mine = tokens(product.brand)
    for text in [record.title, *record.values("product_name")]:
        if _contains(tokens(text), mine):
            return "same", product.brand
    for company in record.values("manufacturer"):
        if len(key) >= 4 and key in brand_key(company):
            return "same", company
    if record.values("brand"):
        return "different", ", ".join(record.values("brand"))
    return "unknown", ""


# -------------------------------------------------------------------- match

def match_product(product: MyProduct, record: Record) -> Match | None:
    def found(score: float, recall_name: str, reason: str) -> Match | None:
        if level_of(score) == "none":
            return None
        return Match(
            product=product, notice_id=record.id, title=record.title, link=record.link, recall_name=recall_name,
            score=round(score, 1), reason=reason, identifiers=check_identifiers(product, record),
        )

    my_ean = product.ean.replace(" ", "")
    recalled_eans = record.extras.get("ean", []) if isinstance(record.extras.get("ean"), list) else []
    if my_ean and my_ean in recalled_eans:
        return found(100.0, record.values("product_name")[0] if record.values("product_name") else record.title,
                     f"EAN {my_ean} is listed in the notice")

    remove = set(tokens(product.brand)) | {t for b in record.values("brand") for t in tokens(b)}
    mine = _without(tokens(product.name), remove)
    best = (0.0, [], "")
    for name in [*record.values("product_name"), record.title]:
        score, shared = name_score(mine, _without(tokens(name), remove))
        if score > best[0]:
            best = (score, shared, name)
    score, shared, recall_name = best
    if not score:
        return None
    status, decided_by = brand_status(product, record)
    reason = f"name {score:.0f} (shared: {', '.join(shared)})"
    if status == "same":
        return found(score * 0.6 + 40, recall_name, f"{reason}; same brand: {decided_by}")
    if status == "different":
        return None  # min(score * 0.5, 50) can never reach an alert
    note = "no brand given" if not product.brand.strip() else f"brand {product.brand} not named in the notice"
    return found(score * 0.85, recall_name, f"{reason}; {note}")


# -------------------------------------------------------------- identifiers

def _norm_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _batch_listed(mine: str, recalled: list[str]) -> bool:
    m = _norm_code(mine)
    for code in recalled:
        if code == "alle":
            return True
        if " bis " in code:
            low, high = (_norm_code(c) for c in code.split(" bis ", 1))
            if len(low) == len(high) == len(m) and low <= m <= high:
                return True
            continue
        c = _norm_code(code)
        if m == c or (min(len(m), len(c)) >= 4 and (m in c or c in m)):
            return True
    return False


def _date_listed(mine: str, recalled: list[str]) -> bool:
    for value in recalled:
        if value == "alle":
            return True
        if ".." in value:
            low, high = value.split("..")
            size = min(len(mine), len(low or mine), len(high or mine))
            if (not low or low[:size] <= mine[:size]) and (not high or mine[:size] <= high[:size]):
                return True
        elif mine.startswith(value) or value.startswith(mine):
            return True
    return False


def _show_date(value: str) -> str:
    if value == "alle":
        return "alle"
    if ".." in value:
        low, high = value.split("..")
        return f"bis {_show_date(high)}" if not low else f"{_show_date(low)} – {_show_date(high)}"
    parts = value.split("-")
    return f"{parts[1]}/{parts[0]}" if len(parts) == 2 else f"{parts[2]}.{parts[1]}.{parts[0]}"


def check_identifiers(product: MyProduct, record: Record) -> dict:
    """Is your pack one of the recalled ones? verdict: affected | not_affected | check."""
    batches, dates = record.values("batch"), record.values("best_before")
    eans = record.extras.get("ean", []) if isinstance(record.extras.get("ean"), list) else []
    checks: dict[str, bool] = {}
    if product.ean.strip() and eans:
        checks["ean"] = product.ean.replace(" ", "") in eans
    if product.batch.strip() and batches:
        checks["batch"] = _batch_listed(product.batch, batches)
    mine_dates = find_dates(product.best_before) if product.best_before.strip() else []
    if mine_dates and dates:
        checks["best_before"] = _date_listed(mine_dates[0].iso, dates)
    if checks and all(checks.values()):
        verdict = "affected"
    elif checks and not any(checks.values()):
        verdict = "not_affected"
    else:
        verdict = "check"
    look_for = []
    if batches:
        look_for.append("Charge " + ", ".join(batches))
    if dates:
        look_for.append("MHD " + ", ".join(_show_date(d) for d in dates))
    if eans:
        look_for.append("EAN " + ", ".join(eans))
    return {
        "verdict": verdict,
        "checks": checks,
        "check": " · ".join(look_for) if look_for else "the notice names no batch, date or EAN: every pack counts",
    }


# ---------------------------------------------------------------------- run

def find_matches(products: list[MyProduct], records: list[Record]) -> list[Match]:
    found = [m for p in products for r in records if (m := match_product(p, r))]
    return sorted(found, key=lambda m: (-m.score, m.product.row, m.notice_id))


def save_matches(conn: sqlite3.Connection, matches: list[Match]) -> None:
    conn.execute("BEGIN")
    conn.execute("DELETE FROM matches")
    conn.executemany(
        "INSERT INTO matches (product_row, my_name, my_brand, notice_id, recall_name, score, reason, identifiers)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (m.product.row, m.product.name, m.product.brand, m.notice_id, m.recall_name, m.score, m.reason,
             json.dumps(m.identifiers, ensure_ascii=False))
            for m in matches
        ],
    )
    conn.execute("COMMIT")
