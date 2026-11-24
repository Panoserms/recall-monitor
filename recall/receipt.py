"""Receipts: from the text of a shop receipt to "this purchase may be recalled".

    parse        item lines of a Lidl digital receipt (the only layout with real samples; other text
                 falls back to "one product per line" and says so)
    words        a receipt description cut into words, each marked if it was abbreviated or cut off
    phrase       the description as a product phrase: abbreviations spelt out from a hand-checked lexicon
    match_line   one receipt line against one recall, with the existing matcher (match.py)
    narrow       reasons why a match is less likely: the notice names other shops only, or the dates rule it out

A receipt carries no batch, best-before date or barcode, so a receipt match never says "affected".
It says "possible match, check your pack" and shows the codes to look for.

This file is the reference. recall/site/static/receipt.js is its line-by-line port for the browser;
tests/test_receipt_parity.py sends the same input through both and requires equal answers.
"""
from __future__ import annotations

import random
import re
from datetime import date, timedelta
from functools import lru_cache

from . import lexicons
from .match import MyProduct, match_product
from .models import Record
from .normalise import fold, split_compound, tokens

POSSIBLE = 74.0  # a receipt line alerts from this score on (see the trade-off in scripts/receipt_eval.py)
CUT_AT = 20  # Lidl prints at most 20 characters of a description; a second, older cut is at 15
MIN_PREFIX = 4  # an abbreviated word needs this many letters before it may stand for a longer word
GRACE_DAYS = 7  # bought this long after the recall was published: the recalled packs were off the shelf
EVAL_SEED, EVAL_SIZE = 20261117, 100


# ------------------------------------------------------------------ parsing

_NUM = r"-?[0-9]+,[0-9]{2}"
_ITEM = re.compile(
    r"^(?P<d>\S.*?)\s+(?:(?P<u>[0-9]+,[0-9]{2})\s+x\s+(?P<q>[0-9]+)\s+)?(?P<t>" + _NUM + r")\s+(?P<tax>[A-Z])\s*$"
)
_DISCOUNT = re.compile(r"^\s*(?P<d>\S.*?)\s+(?P<t>-[0-9]+,[0-9]{2})\s*$")
_WEIGHT = re.compile(r"^\s*(?P<kg>[0-9]+,[0-9]{3})\s*kg\s+x\s+(?P<ppk>[0-9]+,[0-9]{2})\s+EUR/kg\s*$")
_RETURN = re.compile(r"^\s*(?P<q>-?[0-9]+)\s+x\s+(?P<u>[0-9]+,[0-9]{2})\s*$")
_TOTAL = re.compile(r"^\s*zu zahlen\s+(?P<t>-?[0-9.]+,[0-9]{2})\s*$", re.I)
_WHEN = re.compile(r"(?<![0-9])([0-9]{2})\.([0-9]{2})\.([0-9]{4}|[0-9]{2})\s+([0-9]{2}):([0-9]{2})(?![0-9])")
_ARTICLE_NUMBER = re.compile(r"[-' ]+[0-9]{6,}\s*$")  # "Trinkflasche-0451849": Lidl's number for non-food articles
_RULE_LINE = re.compile(r"^[-=_*¦| ]+$")
_TAX_TABLE = re.compile(r"(?i)MWST|Brutto")  # "MWST% MWST + Netto = Brutto": the column "Netto" is not the shop Netto

# Fallback for text that is not in the Lidl layout: one product per line, price columns cut off.
_PRICE_TAIL = re.compile(r"(?:\s+(?:[0-9]+\s*x\s*)?-?[0-9]+[.,][0-9]{2}(?:\s*(?:€|EUR))?(?:\s+[A-Z0-9])?)+\s*$")
_NOT_A_PRODUCT = re.compile(
    r"(?i)^\s*(?:summe|zwischensumme|gesamt|total|zu zahlen|mwst|ust|steuer|netto|brutto|bar\b|rückgeld|"
    r"kreditkarte|karte|girocard|ec-|visa|mastercard|pfand|leergut|rabatt|eur\b|datum|uhrzeit|beleg|bon-|kasse|tel\b|"
    r"www\.|vielen dank|danke)"
)


def _cents(text: str) -> int:
    negative = text.startswith("-")
    digits = text.lstrip("-").replace(".", "").replace(",", "")
    return -int(digits) if negative else int(digits)


def _item(number: int, kind: str, description: str) -> dict:
    return {
        "line_no": number, "kind": kind, "description": description, "nonfood": bool(_ARTICLE_NUMBER.search(description)),
        "quantity": 1, "unit_price": None,
        "weight_kg": None, "price_per_kg": None, "line_total": None, "tax": "", "discount": 0, "discount_names": [],
    }


def find_store(lines: list[str]) -> str:
    """The shop a receipt is from: the first retailer name (lexicons/retailers.tsv) in the given lines, or ""."""
    from .rules.sellers import _lexicon_hits

    for line in lines:
        if _TAX_TABLE.search(line):
            continue
        hits = _lexicon_hits(line)
        if hits:
            return hits[0][2]
    return ""


def find_date(text: str) -> str:
    """The purchase date as 2026-11-07: the first date that is followed by a time ("07.11.2026 16:42"), or ""."""
    for day, month, year, _, _ in _WHEN.findall(text):
        year = int(year) + (2000 if len(year) == 2 else 0)
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31 and 2000 <= year <= 2099:
            return f"{year:04d}-{int(month):02d}-{int(day):02d}"
    return ""


def parse(text: str) -> dict:
    """The receipt as data. layout "lidl": item lines with quantity, weight, discounts and deposits, the
    printed total and whether the lines add up to it. layout "unknown": every line that could be a
    product, nothing else (untested: Lidl is the only chain with real samples)."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").split("\n")]
    start = next((i + 1 for i, line in enumerate(lines) if line.strip() == "EUR"), 0)
    end = next((i for i, line in enumerate(lines) if _TOTAL.match(line)), len(lines))
    total = _cents(_TOTAL.match(lines[end])["t"]) if end < len(lines) else None

    items: list[dict] = []
    unparsed: list[str] = []
    header: list[str] = lines[:start]
    current: dict | None = None
    cents = 0
    for line in lines[start:end]:
        if not line.strip() or _RULE_LINE.match(line):
            continue
        if current is not None and (found := _WEIGHT.match(line)):
            current["weight_kg"] = int(found["kg"].replace(",", "")) / 1000
            current["price_per_kg"] = _cents(found["ppk"]) / 100
            continue
        if current is not None and (found := _RETURN.match(line)):
            current["quantity"], current["unit_price"] = int(found["q"]), _cents(found["u"]) / 100
            continue
        if found := _ITEM.match(line):
            description = found["d"].strip()
            kind = "deposit_return" if description.startswith("Pfandrückgabe") else "deposit" if description.startswith("Pfand") else "product"
            current = _item(len(items) + 1, kind, description)
            current["quantity"] = int(found["q"]) if found["q"] else 1
            current["unit_price"] = _cents(found["u"] or found["t"]) / 100
            current["line_total"] = _cents(found["t"]) / 100
            current["tax"] = found["tax"]
            cents += _cents(found["t"])
            items.append(current)
            continue
        if current is not None and (found := _DISCOUNT.match(line)):
            current["discount"] += _cents(found["t"])  # in cents until the end, so the sum stays exact
            current["discount_names"].append(found["d"].strip())
            cents += _cents(found["t"])
            continue
        (unparsed if current is not None else header).append(line.strip())

    footer = lines[end:]
    if not items:
        return _parse_unknown(lines)
    for item in items:
        item["discount"] = item["discount"] / 100
    names = [name for item in items for name in item["discount_names"]]
    return {
        "layout": "lidl",
        "store": find_store([*header, *names, *footer]),
        "date": find_date(text),
        "total": None if total is None else total / 100,
        "items_sum": cents / 100,
        "sums_match": None if total is None else cents == total,
        "items": items,
        "unparsed": unparsed,
    }


def _parse_unknown(lines: list[str]) -> dict:
    items = []
    for line in lines:
        description = _PRICE_TAIL.sub("", line).strip()
        if len(re.findall(r"[^\W\d_]", description)) < 3 or _NOT_A_PRODUCT.match(description) or _RULE_LINE.match(line):
            continue
        items.append({**_item(len(items) + 1, "product", description), "discount": 0.0})
    text = "\n".join(lines)
    return {
        "layout": "unknown", "store": find_store(lines), "date": find_date(text), "total": None, "items_sum": None,
        "sums_match": None, "items": items, "unparsed": [],
    }


# ------------------------------------------------- text read from a picture

# Text recognition misreads the narrow price column in a few regular ways (seen on synthetic pictures of real
# receipt text, tools/ocr_eval.mjs): the minus as "=" or "-=", the decimal comma as ";", ":" or ".", and the tax
# letter as a digit, sometimes glued to the price ("0,258" for "0,25 B"). These rules repair the end of a line and
# nothing else. Whether the repair was right shows in the sum check: the lines must add up to the printed total.
_OCR_TAIL = re.compile(
    r"(?P<gap>\s+)(?P<minus>[-=–—~]{1,2})?\s?(?P<whole>[0-9]{1,4})\s?[.,;:]\s?(?P<cents>[0-9]{2})(?P<rest>[0-9]?\s*[^\s0-9]?\s?\S{0,2})\s*$"
)


def _ocr_tax(rest: str) -> str:
    """The tax letter behind a price as the picture reader gave it: a digit there is a misread letter (8, 3, 5, 6 for B; 4 for A)."""
    rest = rest.replace(" ", "")
    if not rest:
        return ""
    if re.search(r"[Aa4]", rest):
        return "A"
    if re.search(r"[Bb8356ß]", rest):
        return "B"
    return rest.upper() if re.fullmatch(r"[A-Za-z]", rest) else "X"  # X: there was a letter, but it cannot be read


def repair_ocr(text: str) -> str:
    """Receipt text from text recognition with the price column put right, line by line."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        found = _OCR_TAIL.search(line)
        if found and not line.rstrip().endswith("EUR/kg"):
            tax = _ocr_tax(found["rest"])
            minus = "-" if found["minus"] else ""
            if minus and tax == "X":
                tax = ""  # a discount line has no tax letter; a deposit return ("-0,75 B") has one
            line = f"{line[: found.start()]}  {minus}{found['whole']},{found['cents']}" + (f" {tax}" if tax else "")
        lines.append(line)
    return "\n".join(lines)


# -------------------------------------------------------- description -> phrase

_PIECE = re.compile(r"([^\W\d_]+)(\.?)|([0-9]+(?:[.,][0-9]+)?%?)")
_CAMEL = re.compile(r"(?<=[a-zäöüßéèáàç])(?=[A-ZÄÖÜ])")  # "KerrygoldChed." is two words written without a space


def pieces(description: str) -> list[tuple[str, str]]:
    """(text, cut) in order: the words of a description and the numbers between them.
    cut: "dot" = abbreviated with a full stop ("Vollk."), "end" = last word of a description that fills the
    printed width, so it may be cut off ("Zitronenlimo 0%Zucke"), "num" = a number ("0%", "1,5%"), "" = written out."""
    text = _ARTICLE_NUMBER.sub("", description.strip())
    found: list[tuple[str, str]] = []
    for match in _PIECE.finditer(text):
        if match.group(3):
            found.append((match.group(3), "num"))
            continue
        parts = _CAMEL.split(match.group(1))
        for index, part in enumerate(parts):
            found.append((part, "dot" if match.group(2) and index == len(parts) - 1 else ""))
    full_width = len(description.strip()) >= CUT_AT or len(description.strip()) == 15
    if found and full_width and not found[-1][1] and text.rstrip().endswith(found[-1][0]):
        found[-1] = (found[-1][0], "end")
    return found


def words(description: str) -> list[tuple[str, str]]:
    """The words of a description without the numbers."""
    return [piece for piece in pieces(description) if piece[1] != "num"]


@lru_cache(maxsize=1)
def _abbreviations() -> dict[str, str]:
    """abbreviation without its full stop, folded -> what it stands for ("" = a word that carries no meaning here)."""
    return {fold(row[0]): (row[1] if len(row) > 1 else "") for row in lexicons.load("receipt_abbrev.tsv")}


def phrase(description: str) -> dict:
    """The description as a product phrase.
        text    for the matcher and for the visitor to correct: abbreviations spelt out where the lexicon knows them
        open    folded words that are still abbreviated or possibly cut off; match_line lets them stand
                for a longer word of the recall
        changed True when the lexicon changed something"""
    known = _abbreviations()
    out: list[str] = []
    still_open: list[str] = []
    changed = False
    for word, cut in pieces(description):
        if cut == "num":
            out.append(word)
            continue
        key = fold(word)
        if cut == "dot" and key in known:
            changed = True
            if known[key]:
                out.append(known[key])
            continue
        out.append(word + ("." if cut == "dot" else ""))
        if cut and len(key) >= MIN_PREFIX:
            still_open.append(key)
    return {"text": " ".join(out), "open": still_open, "changed": changed}


# ------------------------------------------------------------------ matching

def _record_words(record: Record) -> list[str]:
    found: list[str] = []
    for name in [*record.values("product_name"), record.title, *record.values("brand")]:
        for word in tokens(name):
            found.append(word)
            found.extend(split_compound(word))
    return found


def complete(text: str, still_open: list[str], record: Record) -> str:
    """Abbreviated words spelt out with the recall's own words: "Schinkenbr." -> "schinkenbraten" when the
    recall names one. Only words of at least MIN_PREFIX letters, and only the first word that fits."""
    if not still_open:
        return text
    pool = _record_words(record)
    out = []
    for word in text.split(" "):
        key = fold(word.rstrip("."))
        if key in still_open:
            longer = next((w for w in pool if w.startswith(key) and len(w) > len(key)), None)
            if longer:
                out.append(longer)
                continue
        out.append(word)
    return " ".join(out)


def _brand_in(line_words: list[str], record: Record) -> str:
    """The recall's brand, if the receipt line spells it out ("Barilla Fusilli")."""
    for brand in record.values("brand"):
        parts = tokens(brand)
        if parts and all(part in line_words for part in parts):
            return brand
    return ""


def same_shop(a: str, b: str) -> bool:
    """"Aldi" on a receipt fits "Aldi Nord" in a notice, and the other way round."""
    a, b = fold(a), fold(b)
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def _last_best_before(values: list[str]) -> str:
    """The latest recalled best-before date as 2027-03-31 / 2027-03, or "" when open ("alle", "2027-05-31..")."""
    latest = ""
    for value in values:
        if value == "alle":
            return ""
        if ".." in value:
            value = value.split("..")[1]
            if not value:
                return ""
        latest = max(latest, value)
    return latest


def narrow(record: Record, store: str = "", purchase_date: str = "") -> list[str]:
    """Why this recall is less likely to concern a purchase. Empty list: nothing speaks against it."""
    reasons = []
    sellers = record.values("sellers")
    if store and sellers and not any(same_shop(store, seller) for seller in sellers):
        reasons.append(f"the notice names other shops only: {', '.join(sellers)}")
    if purchase_date:
        published = str(record.extras.get("first_published") or "") or (record.values("date") or [""])[0]
        if published[:1].isdigit() and len(published) == 10:
            limit = (date.fromisoformat(published) + timedelta(days=GRACE_DAYS)).isoformat()
            if purchase_date > limit:
                reasons.append(f"bought more than {GRACE_DAYS} days after the recall was published ({published})")
        latest = _last_best_before(record.values("best_before"))
        if latest and purchase_date[: len(latest)] > latest:
            reasons.append(f"the recalled packs were past their best-before date ({latest}) when you shopped")
    return reasons


def match_line(
    description: str, record: Record, store: str = "", purchase_date: str = "", text: str | None = None, minimum: float = POSSIBLE
) -> dict | None:
    """One receipt line against one recall. `text` is the visitor's corrected phrase (default: phrase(description)).

    The product-list matcher reports from 65 on. A receipt line is shorter and has no brand, and at 65 a single
    word ("Erdbeeren") alerts for every longer name that contains it ("Erdbeeren in weißer Schokolade").
    From 74 on, every word of the line is in the recall's name and they cover at least half of it."""
    spoken = phrase(description)
    name = spoken["text"] if text is None else text
    still_open = spoken["open"] if text is None else [fold(w.rstrip(".")) for w in text.split(" ") if w.endswith(".") and len(w) > MIN_PREFIX]
    name = complete(name, still_open, record)
    brand = _brand_in(tokens(name), record)
    found = match_product(MyProduct(row=1, name=name, brand=brand), record)
    if found is None or found.score < minimum:
        return None
    return {
        "notice_id": record.id,
        "title": record.title,
        "recall_name": found.recall_name,
        "score": found.score,
        "reason": found.reason,
        "basis": "name and brand" if brand else "name only",
        "matched_as": name,
        "check": found.identifiers["check"],
        "less_likely": narrow(record, store, purchase_date),
    }


def match_receipt(parsed: dict, records: list[Record], store: str | None = None, purchase_date: str | None = None) -> list[dict]:
    """Every product line of a parsed receipt against every recall; strongest first, less likely ones last."""
    store = parsed.get("store", "") if store is None else store
    purchase_date = parsed.get("date", "") if purchase_date is None else purchase_date
    found = []
    for item in parsed["items"]:
        if item["kind"] != "product" or item.get("nonfood"):
            continue  # deposits, and non-food articles (the recalls here are food recalls)
        for record in records:
            hit = match_line(item["description"], record, store, purchase_date, item.get("text"))
            if hit:
                found.append({"line_no": item["line_no"], "description": item["description"], **hit})
    return sorted(found, key=lambda m: (bool(m["less_likely"]), -m["score"], m["line_no"], m["notice_id"]))


# --------------------------------------------------------------- evaluation

def eval_sample(distinct_descriptions: list[str]) -> list[str]:
    """The descriptions drawn for hand labelling (always the same ones for the same sorted input)."""
    return sorted(random.Random(EVAL_SEED).sample(distinct_descriptions, min(EVAL_SIZE, len(distinct_descriptions))))


def synthetic_line(record: Record, name: str) -> str:
    """SYNTHETIC receipt description for a recalled product, made by rule in the style of a Lidl receipt:
    brand dropped, pack size dropped, the longest words cut to five letters and a full stop until the line
    fits, then cut at 20 characters. Used only to check that the matcher can find a recalled product; it says
    nothing about real purchases and is reported apart from real-data numbers."""
    from .textutils import SIZE

    brand_words = {word for brand in record.values("brand") for word in tokens(brand)}
    kept = [w for w in re.findall(r"[^\W\d_]+", SIZE.sub(" ", name)) if fold(w) not in brand_words]
    while len(" ".join(kept)) > CUT_AT:
        long_words = [i for i, w in enumerate(kept) if len(w) > 7 and not w.endswith(".")]
        if not long_words:
            break
        index = max(long_words, key=lambda i: len(kept[i]))
        kept[index] = kept[index][:5] + "."
    return " ".join(kept)[:CUT_AT].rstrip()
