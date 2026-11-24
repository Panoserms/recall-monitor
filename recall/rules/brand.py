"""Field: brand - the brand printed on the product, when the notice names one."""
from __future__ import annotations

import re

from .. import lexicons
from ..companies import company_names
from ..models import FieldValue, NoticeText
from ..textutils import one_line, unique
from . import product as product_rule

# Rule brand.after_marke: the word "Marke" announces the brand.
#   "Sesampaste (Tahina), Marke: Chtoura Garden, 12x800 Gramm"      "... der Marke Suntat"
#   'Bratolivenöl aus Kreta, Marke "GHORBAN", 750 Milliliter'       "... der Marken Sahra und Hira"
# Not a label: "Netto Marken-Discount" (hyphen follows).
_AFTER_MARKE = re.compile(
    r"\b(?P<explicit>der\s+)?(?P<word>Marken?)\b(?!-)(?P<colon>\s*:)?\s*[\"„“‚']?\s*(?P<name>[^,\n;(\"“”]+)"
)
_MARKE_STOPWORDS = {"sind", "ist", "wird", "wurde", "wurden", "werden", "nicht", "sowie", "oder", "im", "in", "von", "vom"}

_GENERIC_FIRST_WORDS = {
    "bio", "der", "die", "das", "firma", "original", "deutsche", "deutsches", "frische", "feine", "verschiedene",
    "diverse", "mineralwässer", "mineralwasser", "brotaufstriche", "brotaufstrich",
}


def _after_marke(text: str) -> list[str]:
    names = []
    for match in _AFTER_MARKE.finditer(text):
        name = match["name"].strip()
        explicit = bool(match["explicit"] or match["colon"])
        parts = re.split(r"\s+und\s+", name) if match["word"] == "Marken" else [name]
        for part in parts:
            cleaned = part.strip()
            first = cleaned.split()[0].lower() if cleaned.split() else ""
            if not cleaned or first in _MARKE_STOPWORDS:
                continue
            if cleaned[:1].isupper() or (explicit and cleaned[:1].isalpha()):
                names.append(cleaned)
    return unique(names)


def _known_brand_at_start(text: str) -> str | None:
    cleaned = re.sub(r"^(?:Netto|ALDI[^:]*):\s*", "", text.strip()).strip(' "\'„“”‚')
    lowered = cleaned.lower()
    best: tuple[int, str] | None = None
    for canonical, variant in lexicons.load("brands.tsv"):
        if lowered.startswith(variant) and not lowered[len(variant) : len(variant) + 1].isalnum():
            if best is None or len(variant) > best[0]:
                best = (len(variant), canonical)
    return best[1] if best else None


def _shared_start(product_name: str, company: str) -> str | None:
    """The leading words a product name shares with a company name: "Wurzener Weiße Bohnen" / "Wurzener Nahrungsmittel GmbH"."""
    product_words = [w for w in product_name.split() if w.strip(",.;:\"„“”")]
    while product_words and product_words[0].strip(",.;:\"„“”").lower() in _GENERIC_FIRST_WORDS:
        product_words = product_words[1:]
    company_words = company.split()
    shared = []
    for a, b in zip(product_words, company_words):
        ca = a.strip(",.;:\"„“”")
        cb = b.strip(",.;:\"„“”")
        if ca.lower() != cb.lower():
            break
        shared.append(ca)
    if not shared or len(shared[0]) < 3 or shared[0].lower() in _GENERIC_FIRST_WORDS:
        return None
    return " ".join(shared)


def extract(notice: NoticeText) -> FieldValue:
    product = notice.sections.get("product", "")
    marking_marke = "\n".join(
        line for line in notice.sections.get("marking", "").split("\n") if re.match(r"(?i)^\s*Marken?\s*:", line)
    )
    named = _after_marke(product) or _after_marke(notice.title) or _after_marke(marking_marke)
    if named:
        evidence = product if _after_marke(product) else (notice.title if _after_marke(notice.title) else marking_marke)
        return FieldValue(values=named, source="rule", rule="brand.after_marke", evidence=one_line(evidence))

    # Rule brand.lexicon: a known brand opens the product name.   "ja! Schweine Mini Schnitzel, 400 Gramm" -> ja!
    extracted_products = product_rule.extract(notice).values
    starts = [notice.title] + product.split("\n") + extracted_products
    known = unique([b for b in (_known_brand_at_start(s.strip()) for s in starts if s.strip()) if b])
    if known:
        return FieldValue(values=known, source="rule", rule="brand.lexicon", evidence=one_line(product or notice.title))

    # Rule brand.company_name_in_product: the product name starts with the company's own name.
    #   "Wurzener Weiße Bohnen" made by "Wurzener Nahrungsmittel GmbH" -> Wurzener
    candidates = list(starts)
    for line in [notice.title, *product.split("\n")]:
        candidates.extend(m.group(1) for m in re.finditer(r'[„"“]([^„"“”]+)["“”]', line))
        candidates.extend(p.strip() for p in line.split(",") if p.strip())
    for company in company_names(notice.sections.get("manufacturer", "")):
        for start in candidates:
            shared = _shared_start(start.strip(), company)
            if shared:
                return FieldValue(
                    values=[shared], source="rule", rule="brand.company_name_in_product", evidence=f"{one_line(start)} | {company}"
                )
    return FieldValue.empty()
