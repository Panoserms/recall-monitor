"""Field: states - the federal states where the product was on the market."""
from __future__ import annotations

import re

from .. import lexicons
from ..models import FieldValue, NoticeText
from ..textutils import one_line, unique


def extract(notice: NoticeText) -> FieldValue:
    # Rule states.field: the portal's own list, one state per line (page) or comma-separated (feed).
    #   "Betroffene Bundesländer nach derzeitigem Stand: Bremen, Hamburg, Mecklenburg-Vorpommern, Niedersachsen, Schleswig-Holstein"
    text = notice.sections.get("states", "")
    known = {row[0] for row in lexicons.load("states.tsv")}
    found = unique([part.strip() for part in re.split(r"[,;\n]", text) if part.strip() in known])
    if not found:
        return FieldValue.empty()
    return FieldValue(values=found, source="structured", rule="states.field", evidence=one_line(text))
