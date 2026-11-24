"""Field: reason_category - salmonella | listeria | foreign_object | undeclared_allergen | other."""
from __future__ import annotations

import re

from .. import lexicons
from ..models import FieldValue, NoticeText
from ..textutils import one_line

# Where a pathogen may be named, most reliable section first.
_SECTIONS = ("more_info", "title", "product", "consequences", "recommendation", "update_notes")


def _first_pathogen(notice: NoticeText, categories: set[str]) -> tuple[str, str] | None:
    """(category, section text) of the first pathogen of the given categories that the notice names."""
    texts = {**notice.sections, "title": notice.title}
    for name in _SECTIONS:
        text = texts.get(name, "")
        best: tuple[int, str] | None = None
        for stem, category in lexicons.load("pathogens.tsv"):
            if category in categories:
                hit = re.search(r"(?<![a-zäöüß])" + re.escape(stem), text.lower())
                if hit and (best is None or hit.start() < best[0]):
                    best = (hit.start(), category)
        if best:
            return best[1], text
    return None


def extract(notice: NoticeText) -> FieldValue:
    official = [part.strip() for part in re.split(r"[,\n]", notice.sections.get("reason_official", "")) if part.strip()]

    # Rules reason_category.salmonella_in_text / listeria_in_text: the notice names the pathogen.
    #   "Im Rahmen einer Eigenuntersuchung wurden Salmonellen nachgewiesen."
    #   "Mikrobielle Kontamination mit Listeria monocytogenes"
    named = _first_pathogen(notice, {"salmonella", "listeria"})
    if named:
        category, text = named
        return FieldValue(values=[category], source="rule", rule=f"reason_category.{category}_in_text", evidence=one_line(text))

    # Rule reason_category.official: the portal's own reason, mapped one to one.
    #   "Grund der Meldung: Fremdkörper" -> foreign_object      "Grund der Meldung: Allergene" -> undeclared_allergen
    if "Fremdkörper" in official:
        return FieldValue(values=["foreign_object"], source="structured", rule="reason_category.official", evidence=", ".join(official))
    if "Allergene" in official:
        return FieldValue(values=["undeclared_allergen"], source="structured", rule="reason_category.official", evidence=", ".join(official))

    if "Krankheitserreger" in official:
        # Rule reason_category.other_pathogen: a pathogen, but neither salmonella nor listeria.
        #   "... weil in einer Einzeluntersuchung Shigatoxinbildende Escherichia coli (STEC) nachgewiesen wurden."
        more_info = notice.sections.get("more_info", "")
        if more_info:
            return FieldValue(values=["other"], source="rule", rule="reason_category.other_pathogen", evidence=one_line(more_info))
        # The feed alone says "Krankheitserreger" and never names the pathogen: leave the field open.
        return FieldValue.empty("reason_category.pathogen_not_named")

    if official:  # "Rückstände und Kontaminanten", "Gesundheitsschädliche Substanz", "Sonstige Gründe", ...
        return FieldValue(values=["other"], source="structured", rule="reason_category.official", evidence=", ".join(official))
    return FieldValue.empty()
