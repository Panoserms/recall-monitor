"""Field: batch - the batch (lot) numbers the recall is limited to.

Batch numbers have no common shape ("090426", "L 0126", "LC5 BD149T", "KMG/640"), so the
rules do not look for one. They read the field token by token, drop what is clearly not
a code (words, pack sizes, best-before dates, times) and keep the rest.
Values are the codes as printed, or "alle" when every batch is affected.
"""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText
from ..textutils import SIZE, UNKNOWN, find_dates, is_date, one_line, unique

# Words that announce a batch number:
#   "Chargennummer: 090426", "LOT - 119621", "Los-Nummer KMG/640.", "Parti NO: 00.00.02", "L: 06.12.2026"
_LABEL = re.compile(
    r"(?i)^(?:chargen?(?:-?(?:nummern?|nr\.?|bezeichnung))?|los(?:-?(?:nummern?|kennzeichnung|nr\.?))?"
    r"|lot(?:-?(?:nummern?|no\.?|nr\.?))?|batch(?:-?(?:number|nr\.?))?|psn|parti|number|nummer|no\.?|nr\.?"
    r"|code|codierung(?:en)?|kennzeichnung|referenznummer)[:.\-]?$"
)
_LABEL_L = re.compile(r"^L:$")  # "L:" announces a batch, a bare "L" is part of one ("L 0126")

# Rule batch.all: "alle Chargen"
_ALL = re.compile(r"(?i)^(?:alle|sämtliche)(?:\s+(?:chargen|chargennummern|lose|losnummern|lots))?\.?$")
_ALL_INSIDE = re.compile(
    r"(?i)\b(?:(?:alle|sämtliche)\s+(?:chargen|chargennummern|lose|losnummern)|unabhängig\s+von\s+chargennummer\w*)\b"
)

# A best-before date inside the batch field belongs to the field best_before:
#   "Lotnummer: L140626V3 MHD: 13.06.2028"
_DATE_TEXT = r"\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}[./-]20\d{2}"
_LABELLED_DATE = re.compile(
    rf"(?i)(?:MHD|Mindesthaltbarkeitsdat\w*|mindestens haltbar bis|haltbar bis|Verbrauchsdatum|EXP)\s*:?\s*"
    rf"(?:(?:{_DATE_TEXT})(?:\s*(?:,|/|und)\s*(?=\d{{1,2}}[./]))?)+"
)
_LABELLED_BARCODE = re.compile(
    r"(?i)\b(?:EAN|GTIN|UPC|GLN|Barcode|Strichcode)(?:[- ]?(?:Codes?|Nummern?|Nr\.?))?\s*[:\-]?\s*"
    r"(?:\d(?:[ ]?\d){6,13}(?:\s*[/,;]\s*)?)+"
)
_PRODUCT_CODE = re.compile(r"(?i)^(?:GTIN|EAN|UPC|GLN)[:\-]?\d*$")  # "GTIN4063367234613" names the product, not the batch
_TIME_PHRASE = re.compile(
    r"(?i)\b(?:ab\s+)?Uhrzeit\s*:?\s*\d{1,2}:\d{2}(?:\s*bis(?:\s+einschließlich)?\s*\d{1,2}:\d{2})?"
    r"|\b\d{1,2}:\d{2}\s*Uhr\b"
)
_BARE_CODE_LIST = re.compile(r"^[A-Z]{1,4}\d[\w./-]*(?:\s*[;,]\s*[A-Z]{1,4}\d[\w./-]*)*$")
_SEPARATORS = {",", ";", "(", ")", "|", "und", "sowie", "oder", "bzw."}
_UPPER_WORDS = {
    "ALDI", "LIDL", "REWE", "MHD", "EAN", "GTIN", "UPC", "BIO", "NEU", "EU", "EXP", "UND", "DIE", "DER", "DAS",
    "VON", "BIS", "MIT", "FÜR", "ODER", "PET", "AB", "IM", "AM",
}


def _tokens(line: str) -> list[str]:
    line = _LABELLED_DATE.sub(" ", line)
    line = _LABELLED_BARCODE.sub(" ", line)
    line = _TIME_PHRASE.sub(" ", line)
    line = SIZE.sub(" ", line)  # "600 Gramm" is a pack size
    line = re.sub(r"(?<=[A-Za-zÄÖÜäöüß)]):(?=\S)", ": ", line)  # "Charge:103150" -> "Charge: 103150"
    line = re.sub(r"\s/\s?|/\s", " | ", line)  # "L150626V3/ L150626N3" lists two codes, "KMG/640" is one
    return re.findall(r"[;,()|]|[^\s;,()|]+", line)


_VERBS = {
    "betrifft", "betreffen", "befindet", "befinden", "sind", "ist", "wird", "werden", "wurde", "wurden", "haben",
    "hat", "kann", "können", "lautet", "lauten", "gilt", "gelten", "findet", "finden", "steht", "stehen", "siehe",
}


def _is_prose(tokens: list[str]) -> bool:
    """Running text, where a number may be anything: "Der Rückruf betrifft die Losnummer L.26113A".
    In running text only a code that follows a batch label is trusted."""
    small = [t for t in tokens if t.isalpha() and t.islower() and len(t) >= 3 and t not in _SEPARATORS and t != "bis"]
    return len(small) >= 3 or any(t in _VERBS for t in small)


def _is_word(token: str) -> bool:
    """Not part of a code: has no digit and is not a short all-capital piece like "TF" or "KHR"."""
    if any(ch.isdigit() for ch in token):
        return False
    letters = token.strip(".:-")
    return not (letters.isalpha() and letters.isupper() and len(letters) <= 4 and letters not in _UPPER_WORDS)


def _codes(text: str, *, labelled_only: bool) -> list[str]:
    """The batch codes in a text. `labelled_only`: keep only codes that follow a batch label."""
    whole = text.strip()
    codes: list[str] = []
    # a remark in brackets is read on its own: "LB226056 (Die Losnummer befindet sich auf dem Deckelrand, ...)"
    for line in re.split(r"[\n()]", text):
        tokens = _tokens(line)
        need_label = labelled_only or _is_prose(tokens)
        run: list[str] = []
        labelled = False
        pending_range: str | None = None  # first code of "LG262 bis LG292"

        def close_run() -> None:
            nonlocal run, labelled, pending_range
            code = _run_to_code(run, labelled, need_label, whole)
            if code and pending_range:
                codes[-1] = f"{pending_range} bis {code}"
            elif code:
                codes.append(code)
            run, labelled, pending_range = [], False, None

        i = 0
        while i < len(tokens):
            token = tokens[i]
            bare = token.rstrip(".,") if not is_date(token) else token
            if token in _SEPARATORS:
                close_run()
            elif _LABEL.match(token) or _LABEL_L.match(token):
                close_run()
                labelled = True
                if i + 1 < len(tokens) and tokens[i + 1] in {"-", "–", ":"}:  # "LOT - 119621"
                    i += 1
            elif _PRODUCT_CODE.match(token):
                close_run()
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():  # "GTIN 4063367234613"
                    i += 1
            elif token.lower() == "bis" and run and i + 1 < len(tokens) and not _is_word(tokens[i + 1]):
                was_labelled = labelled
                first = _run_to_code(run, labelled, need_label, whole)
                run, labelled, pending_range = [], False, None
                if first:
                    codes.append(first)
                    pending_range, labelled = first, was_labelled
            elif _is_word(token):
                close_run()
            else:
                run.append(bare)
            i += 1
        close_run()
    return codes


def _run_to_code(run: list[str], labelled: bool, need_label: bool, whole: str) -> str | None:
    if not run or (need_label and not labelled):
        return None
    not_dates = [t for t in run if not is_date(t)]
    if any(any(ch.isdigit() for ch in t) for t in not_dates):
        return " ".join(not_dates)  # "260904 23.10.2026" -> "260904": the date is a best-before date
    if not not_dates:
        return " ".join(run) if labelled else None  # "L: 06.12.2026": here the date is the batch
    # capital letters only ("KHR"): a code only if labelled or if it is the whole field
    return " ".join(run) if labelled or " ".join(run) == whole else None


def extract(notice: NoticeText) -> FieldValue:
    text = notice.sections.get("batch", "").strip()
    if text:
        if UNKNOWN.match(text):
            return FieldValue.empty("batch.stated_unknown")  # "nicht bekannt"
        if _ALL.match(text):
            return FieldValue(values=["alle"], source="rule", rule="batch.all", evidence=one_line(text))
        codes = unique(_codes(text, labelled_only=False))
        if codes:
            # Rule batch.codes: "Charge: L60471F" / "Chargen: 103150, 104062 und 104731" / "LC5 BD149T"
            return FieldValue(values=codes, source="rule", rule="batch.codes", evidence=one_line(text))
        if _ALL_INSIDE.search(text):
            return FieldValue(values=["alle"], source="rule", rule="batch.all", evidence=one_line(text))
    # Rule batch.labelled_in_other_field: the batch was typed into another field.
    #   Haltbarkeit: "Mindesthaltbarkeitsdatum: 31.08.2028, Charge:103150"
    for name in ("best_before", "marking", "package"):
        other = notice.sections.get(name, "").strip()
        if not other:
            continue
        bare_list = name == "marking" and bool(_BARE_CODE_LIST.match(other)) and not _PRODUCT_CODE.match(other)
        codes = unique(_codes(other, labelled_only=not bare_list))
        if codes:
            return FieldValue(values=codes, source="rule", rule="batch.labelled_in_other_field", evidence=one_line(other))
        if _ALL_INSIDE.search(other):
            return FieldValue(values=["alle"], source="rule", rule="batch.all", evidence=one_line(other))
    return FieldValue.empty()
