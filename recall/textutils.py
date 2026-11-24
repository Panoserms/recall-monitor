"""Small text tools shared by several rules: dates, pack sizes, list helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass

MONTHS = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mrz": 3, "april": 4, "apr": 4,
    "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9,
    "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))

# The date spellings seen in real notices, most specific first.
_DATE = re.compile(
    rf"""
      (?P<ymd>   (?<!\d) (?P<y1>20\d{{2}}) [/.-] (?P<m1>\d{{1,2}}) [/.-] (?P<d1>\d{{1,2}}) (?!\d) )   # 2027/09/12
    | (?P<dmy>   (?<![\d.]) (?P<d2>\d{{1,2}}) (?P<sep>[./-]) (?P<m2>\d{{1,2}}) (?P=sep) (?P<y2>\d{{4}}|\d{{2}}) (?!\d) )  # 01.03.2028, 05/05/2030, 04-06-2027
    | (?P<dname> (?<!\d) (?P<d3>\d{{1,2}}) \.\s* (?P<m3>{_MONTH}) \.?\s+ (?P<y3>20\d{{2}}) )          # 14. Oktober 2026
    | (?P<my>    (?<![\d./-]) (?P<m4>\d{{1,2}}) [./-] (?P<y4>20\d{{2}}) (?!\d) )                      # 07.2028, 12/2028, 10-2027
    | (?P<mname> (?<![A-Za-zÄÖÜäöüß]) (?P<m5>{_MONTH}) \.?\s*/?\s* (?P<y5>20\d{{2}}) )                # März/2028
    | (?P<myy>   (?<![\d./-]) (?P<m6>\d{{1,2}}) / (?P<y6>\d{{2}}) (?![\d./-]) )                       # 7/26
    """,
    re.X | re.I,
)


@dataclass(frozen=True)
class DateMatch:
    start: int
    end: int
    iso: str  # "2028-03-01", or "2028-03" when only month and year are given
    text: str


def _iso(year: int, month: int, day: int | None) -> str | None:
    if year < 100:
        year += 2000
    if not (2000 <= year <= 2099 and 1 <= month <= 12):
        return None
    if day is None:
        return f"{year:04d}-{month:02d}"
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def find_dates(text: str, *, short_years: bool = False) -> list[DateMatch]:
    """All dates in the text, in order. `short_years` also reads "7/26" as July 2026;
    only safe inside a best-before field, where a slash cannot be part of a batch code."""
    found = []
    for m in _DATE.finditer(text):
        if m.group("ymd"):
            iso = _iso(int(m["y1"]), int(m["m1"]), int(m["d1"]))
        elif m.group("dmy"):
            iso = _iso(int(m["y2"]), int(m["m2"]), int(m["d2"]))
        elif m.group("dname"):
            iso = _iso(int(m["y3"]), MONTHS[m["m3"].lower()], int(m["d3"]))
        elif m.group("my"):
            iso = _iso(int(m["y4"]), int(m["m4"]), None)
        elif m.group("mname"):
            iso = _iso(int(m["y5"]), MONTHS[m["m5"].lower()], None)
        else:
            iso = _iso(int(m["y6"]), int(m["m6"]), None) if short_years and int(m["y6"]) >= 20 else None
        if iso:
            found.append(DateMatch(m.start(), m.end(), iso, m.group(0)))
    return found


def is_date(token: str) -> bool:
    found = find_dates(token)
    return len(found) == 1 and found[0].start == 0 and found[0].end == len(token)


# Pack sizes: "160 Gramm", "12x800 Gramm", "1,5 l", "500 g", "2 Kilogramm", "6 x 0,33 Liter", "50 Gramm/60 Kapseln"
UNIT = (
    r"(?:Kilogramm|Milligramm|Gramm|Milliliter|Zentiliter|Liter|Unzen|Stück|Stueck|Stk\.?|Packungen|Portionen|"
    r"Aufgussbeutel|Teebeutel|Beutel|Kapseln|Tabletten|packets|oz|kg|mg|gr|g|ml|cl|l)"
)
_ONE_SIZE = rf"(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*{UNIT}(?![\w-])\.?"
SIZE = re.compile(rf"(?<![\w.,/#-])(?:{_ONE_SIZE})(?:\s*(?:/|á|à|je)\s*{_ONE_SIZE})*", re.I)


def strip_sizes(text: str) -> str:
    return SIZE.sub(" ", text)


def unique(items: list[str]) -> list[str]:
    """The items in their first order, without repeats and without empty ones."""
    seen: dict[str, None] = {}
    for item in items:
        if item and item not in seen:
            seen[item] = None
    return list(seen)


def one_line(text: str, limit: int = 300) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


UNKNOWN = re.compile(r"(?i)^(?:nicht bekannt|unbekannt|nicht angegeben|keine(?: angaben?)?|k\.\s?a\.|-+|–)\.?$")
