"""Field: reason_text - why the product is recalled, in the words of the notice."""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText


def extract(notice: NoticeText) -> FieldValue:
    # Rule reason_text.more_info: the page field "Weitere Informationen", taken whole.
    #   "In einem Glas des betroffenen Produkts wurden Glassplitter festgestellt."
    # The feed has no such field, so a notice without a saved page has no reason text.
    text = re.sub(r"\s+", " ", notice.sections.get("more_info", "")).strip()
    if not text:
        return FieldValue.empty()
    return FieldValue(values=[text], source="structured", rule="reason_text.more_info", evidence=text)
