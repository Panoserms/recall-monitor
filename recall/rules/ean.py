"""Extra identifier: ean - the barcode (EAN / GTIN) printed on the recalled product.

Not one of the evaluated fields, but the surest way to tell whether a pack in your
cupboard is the recalled one. Only labelled numbers with a correct check digit count.
"""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText
from ..textutils import one_line, unique

# Rule ean.labelled: a number after "EAN", "GTIN", "Barcode" or "Strichcode", digits may be grouped by spaces.
#   "EAN: 4260677731805"   "EAN-CODE:8006363076203"   "GTIN-Nummer: 4006950042790"   "Barcode: 6 923807 807198"
_CODE = r"\d(?:[ ]?\d){7,13}"
_LABELLED = re.compile(
    rf"(?i)\b(?:EAN|GTIN|Barcode|Strichcode)(?:[- ]?(?:Codes?|Nummern?|Nr\.?))?(?:\s*\([^)]*\))?\s*[:\-]?\s*"
    rf"({_CODE}(?:\s*(?:[/,;]|und)\s*{_CODE})*)(?!\d)"
)
_DIGITS = re.compile(_CODE)

_SECTIONS = ("marking", "product", "batch", "package", "best_before", "more_info", "update_notes")


def valid(code: str) -> bool:
    """GS1 check digit for EAN-8, UPC-A (12), EAN-13 and GTIN-14."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(d) for d in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def extract(notice: NoticeText) -> FieldValue:
    for name in _SECTIONS:
        text = notice.sections.get(name, "")
        codes = unique(
            [c for m in _LABELLED.finditer(text) for c in (d.replace(" ", "") for d in _DIGITS.findall(m.group(1))) if valid(c)]
        )
        if codes:
            return FieldValue(values=codes, source="rule", rule="ean.labelled", evidence=one_line(text))
    return FieldValue.empty()
