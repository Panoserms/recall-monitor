"""Field: best_before - the best-before (or use-by) dates the recall is limited to.

Values are ISO dates ("2028-03-01"), months ("2028-03"), ranges ("2027-05-31..2027-07-02",
open start "..2026-11-17") or "alle" when every date is affected.
"""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText
from ..textutils import UNKNOWN, find_dates, one_line, unique

# Rule best_before.range: two dates joined by "bis" or a dash are the ends of a range.
#   "Mindeshaltbarkeitsdatum: zwischen 31.05.2027 bis einschließlich 02.07.2027"
#   "Mindesthaltbarkeitsdatum von 09/2027 bis 10/2028"
_BETWEEN_RANGE_ENDS = re.compile(r"(?:\s*bis(?:\s+(?:einschließlich|einschl\.|zum))?\s*|[ \t]*[-–—][ \t]*)", re.I)

# Rule best_before.range (open start): "bis" directly before a single date means "up to this date" ...
#   "Mindesthaltbarkeitsdatum bis einschließlich 17.11.2026"
# ... unless it is the usual wording of a best-before date:
#   "Mindestens haltbar bis: 23.02.2028", "Mindestens haltbar bis Ende 04/2028"
_UP_TO = re.compile(r"\bbis(?:\s+(?:einschließlich|einschl\.|zum))?\s*:?\s*$", re.I)
_USUAL_WORDING = re.compile(r"haltbar\s+bis\b[^.;]*$", re.I)

# Rule best_before.all: every best-before date is affected.
#   "alle Mindesthaltbarkeitsdaten", "Mindesthaltbarkeitsdaten: ALLE",
#   "Es werden alle noch gültigen Mindesthaltbarkeitsdaten zurückgerufen."
#   "sämtliche Mindesthalbarkeitsdatum" (the word is often misspelt, so its middle is matched loosely)
_MHD_WORD = r"(?:m\w{3,8}hal\w{0,3}barkeitsdat\w*|haltbarkeitsdat\w*|mhd)"
_ALL = re.compile(
    rf"\b(?:alle[nrs]?|sämtliche[nrs]?)\b[^\n.;:]{{0,30}}?{_MHD_WORD}"
    rf"|{_MHD_WORD}\s*:\s*alle\b"
    r"|\A\s*alle\s*\Z",
    re.I,
)

# Rule best_before.date_in_batch_field: the batch field sometimes carries the dates.
#   "Lotnummer: L140626V3 MHD: 13.06.2028"          (date labelled MHD)
#   "260904 23.10.2026;"                             (batch and date side by side)
#   "12.03.2027 (Chargennummer L CA123)"             (date, then the batch in brackets)
_MHD_LABEL = re.compile(r"(?:MHD|Mindesthaltbarkeitsdat\w*|haltbar bis|Verbrauchsdatum|zu verbrauchen bis|EXP)\s*:?\s*$", re.I)
_BATCH_IN_BRACKETS = re.compile(r"\s*\(\s*(?:Charge|Los|Lot)", re.I)


def _read(text: str) -> list[tuple[int, str]]:
    """(position, value) for every date, range and "alle" in a best-before text."""
    dates = find_dates(text, short_years=True)
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(dates):
        date = dates[i]
        following = dates[i + 1] if i + 1 < len(dates) else None
        if following and _BETWEEN_RANGE_ENDS.fullmatch(text[date.end : following.start]):
            found.append((date.start, f"{date.iso}..{following.iso}"))
            i += 2
            continue
        previous_end = dates[i - 1].end if i else 0
        before = text[previous_end : date.start]
        if _UP_TO.search(before) and not _USUAL_WORDING.search(before):
            found.append((date.start, f"..{date.iso}"))
        else:
            found.append((date.start, date.iso))
        i += 1
    for match in _ALL.finditer(text):
        line_end = text.find("\n", match.end())
        rest_of_line = text[match.end() : line_end if line_end != -1 else len(text)]
        if not find_dates(rest_of_line, short_years=True):  # "alle ... vom 08.04.2027 bis 04.05.2027" is a range
            found.append((match.start(), "alle"))
    return sorted(found)


def _without_dates(text: str) -> str:
    for date in reversed(find_dates(text)):
        text = text[: date.start] + text[date.end :]
    return text


def _in_batch_field(text: str) -> list[str]:
    values = []
    for line in text.split("\n"):
        for date in find_dates(line):
            before = line[: date.start]
            code_before = any(ch.isdigit() for ch in _without_dates(before))
            if _MHD_LABEL.search(before) or code_before or _BATCH_IN_BRACKETS.match(line[date.end :]):
                values.append(date.iso)
    return values


def extract(notice: NoticeText) -> FieldValue:
    text = notice.sections.get("best_before", "").strip()
    if text:
        if UNKNOWN.match(text):
            return FieldValue.empty("best_before.stated_unknown")  # "nicht bekannt"
        values = unique([value for _, value in _read(text)])
        if values:
            if any(".." in v for v in values):
                rule = "best_before.range"
            elif values == ["alle"]:
                rule = "best_before.all"
            else:
                rule = "best_before.dates"  # "Mindesthaltbarkeitsdatum: 01.03.2028, 05.03.2028 und 10.03.2028"
            return FieldValue(values=values, source="rule", rule=rule, evidence=one_line(text))
    batch = notice.sections.get("batch", "")
    values = unique(_in_batch_field(batch))
    if values:
        return FieldValue(values=values, source="rule", rule="best_before.date_in_batch_field", evidence=one_line(batch))
    for name in ("marking", "package"):
        other = notice.sections.get(name, "")
        values = unique([d.iso for line in other.split("\n") for d in find_dates(line) if _MHD_LABEL.search(line[: d.start])])
        if values:
            return FieldValue(values=values, source="rule", rule="best_before.date_in_other_field", evidence=one_line(other))
    return FieldValue.empty()
