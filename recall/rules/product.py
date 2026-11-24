"""Field: product_name - what is recalled, without pack size, brand note or article number."""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText
from ..textutils import SIZE, one_line, unique

# "..., Marke: Chtoura Garden"   "... der Marke Suntat"   "– Marke Più Amore a Tavola"   'der Marke "BOY BAWANG"'
_BRAND_NOTE = re.compile(r"[\s,–-]*\b(?:der\s+)?Marken?\b(?!-)\s*:?\s*[^,\n;]*")
_ARTICLE_NUMBER = re.compile(r"^\d{5,}\s*[-–]\s*")  # "00024629 - GUACAMOLE-MIX 55 Gramm BIO"
_LABEL_LINE = re.compile(r"(?i)^(?:Marke|Produktart|Hersteller|EAN|GTIN|Artikelnummer|Art\.?-?Nr\.?|Charge|MHD|Inhalt|Verpackung)\s*:")
_SUMMARY_LINE = re.compile(r"(?i)^(?:verschiedene|diverse|mehrere|folgende|alle)\b")  # "Verschiedene Sorten MINI BRIE, 150 Gramm"
_PACKAGING_ONLY = re.compile(r"(?i)^(?:(?:PET|Behälter|Glas|Dose|Beutel|Packung|Flasche|Becher|Tüte|Eimer|Karton|Schale|Netz|lose|im|in|der)\s*)+$")
_OUTER_QUOTES = re.compile(r'^[„"“\']\s*([^"„“”\']+)\s*["“”\']$')
_COMMA_SPLIT = re.compile(r"(?<!\d),|,(?!\d)")  # split on commas, but never inside "0,5 Liter"
_TITLE_REMARK = re.compile(r"\s*\((?:Update|Aktualisierung|Korrektur)[^)]*\)\s*$")  # "(Update zu Kaufland)"
_VERB = re.compile(r"\b(?:ist|sind|wird|wurde|wurden|werden|kann|können|hat|haben|wiederholt|finden|betrifft|betreffen)\b")


def _is_running_text(line: str) -> bool:
    """A sentence rather than a product name: "Update vom 14. Oktober 2026: Die Kaufland ... wiederholt den ... Rückruf ..." """
    return len(line.split()) > 12 and bool(_VERB.search(line))


def clean_name(text: str) -> str:
    """One product name without brand note, pack size and article number.
    "Sumach gemahlen, 200 Gramm der Marke Ikleel Algabal (ME TRADE INTL)" -> "Sumach gemahlen" """
    text = _BRAND_NOTE.sub("", text).strip()
    if m := _OUTER_QUOTES.match(text):
        text = m.group(1).strip()
    text = _ARTICLE_NUMBER.sub("", text.strip())
    parts: list[str] = []
    for part in _COMMA_SPLIT.split(text):
        without_size = SIZE.sub(" ", part)
        had_size = without_size != part
        tidy = re.sub(r"\s+", " ", without_size).strip(" -–;:")
        if tidy and tidy.lower() != "und" and not (had_size and _PACKAGING_ONLY.match(tidy)):
            parts.append(tidy)
    out = ""
    for part in parts:
        if not out:
            out = part
        elif part.lower().startswith("und "):
            out = f"{out} {part}"
        else:
            out = f"{out}, {part}"
    return out


def _split_products(line: str) -> list[str]:
    """Several products written into one line.
    "Rueter Apfel-Birnen-Saft, Rueter Apfelpunsch alkoholfrei, Rueter Birnensaft"   (same first word after every comma)
    "Wurzener Weiße Bohnen, 500 Gramm und Wurzener Weiße Bohnen, 10 Kilogramm"      (same first word after "und")
    '„Treets Salted Peanuts Vegan 200 Gramm" und „K-Classic Choc it bunte Erdnüsse 300 Gramm"' (each product in quotes)"""
    if line[:1] in '„"“':
        quoted = [p.strip() for p in re.split(r'(?<=[""”])\s+und\s+(?=[„"“])', line) if p.strip()]
        if len(quoted) > 1:
            return quoted
    first_word = line.split()[0] if line.split() else ""
    if len(first_word) >= 3:
        for separator in (r",\s+", r"\s+und\s+"):
            pieces = [p.strip() for p in re.split(separator, line) if p.strip()]
            if len(pieces) > 1 and all(p.split()[0] == first_word for p in pieces):
                if ":" in line and not all(":" in p for p in pieces):
                    continue  # "ALDI Süd und ALDI Nord: Bio Beerenmischung" is one product with a shop prefix
                return pieces
    return [line]


def _clean_title(title: str) -> str:
    return clean_name(_TITLE_REMARK.sub("", title))


def extract(notice: NoticeText) -> FieldValue:
    text = notice.sections.get("product", "").strip()
    title = notice.title.strip()
    lines = [line.strip() for chunk in text.split("\n") for line in chunk.split(";") if line.strip()]
    for index, line in enumerate(lines):  # everything from the first sentence on is description, not a list of names
        if _is_running_text(line):
            lines = lines[:index]
            break
    lines = [line for line in lines if not _LABEL_LINE.match(line)]
    if len(lines) > 1:
        lines = [line for line in lines if not _SUMMARY_LINE.match(line)] or lines
    names = unique([clean_name(piece) for line in lines for piece in _split_products(line)])

    if not names:
        # Rule product.from_title: the product field has no usable name, the title has.
        #   title "BEBA- und ALFAMINO-Produkte (Update zu Kaufland)" -> "BEBA- und ALFAMINO-Produkte"
        name = _clean_title(title)
        if not name:
            return FieldValue.empty()
        source = "structured" if name == title else "rule"
        return FieldValue(values=[name], source=source, rule="product.title" if name == title else "product.from_title", evidence=title)

    if len(names) > 1:
        # Rule product.list: one product per line, or several in one line.
        #   "Brie Mini Nuss 150 Gramm, Marke: Eberle Spezialitäten / Brie Mini Schnittlauch 150 Gramm, ..."
        return FieldValue(values=names, source="rule", rule="product.list", evidence=one_line(text))

    name = names[0]
    short = _clean_title(title)
    if short and name != short and re.match(re.escape(short) + r"(?:,| \(| \|)", name):
        # the title is the authority's own short form: "Gefrorene Austern, 226 Gramm" for
        # "Gefrorene Austern, 226 Gramm, Surasang Frozen oysters (I:Q:F:) Huitre Congelee"
        name = short
    if name == text:
        return FieldValue(values=[name], source="structured", rule="product.field", evidence=text)  # "Wasabi rice crackers"
    if name == title:
        return FieldValue(values=[name], source="structured", rule="product.title", evidence=title)  # "Kalmar Fangarme"
    # Rule product.name: pack size and brand note removed.   "ja! Schweine Mini Schnitzel, 400 Gramm" -> "ja! Schweine Mini Schnitzel"
    return FieldValue(values=[name], source="rule", rule="product.name", evidence=one_line(text))
