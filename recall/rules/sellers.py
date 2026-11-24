"""Field: sellers - the shops that sold the product, when the notice names them."""
from __future__ import annotations

import re

from .. import lexicons
from ..companies import _NO_INFORMATION, _POSTCODE, company_names
from ..models import FieldValue, NoticeText
from ..textutils import one_line

# ------------------------------------------------------------------ lexicon

def _lexicon_hits(text: str) -> list[tuple[int, int, str]]:
    """(start, end, shop) for every retailer spelling in the text; longer spellings win."""
    hits: list[tuple[int, int, str]] = []
    rows = sorted(lexicons.load("retailers.tsv"), key=lambda row: -len(row[1]))
    for row in rows:
        shop, spelling = row[0], row[1]
        exact = len(row) > 2 and row[2] == "exact"
        pattern = r"(?<![\wÄÖÜäöüß])" + re.escape(spelling) + r"(?![\wÄÖÜäöüß])"
        for match in re.finditer(pattern, text, 0 if exact else re.I):
            if not any(match.start() < end and start < match.end() for start, end, _ in hits):
                hits.append((match.start(), match.end(), shop))
    return sorted(hits)


def _as_known_shop(name: str) -> str | None:
    """"Dirk Rossmann GmbH" -> "Rossmann"; None if the name contains no known shop."""
    hits = _lexicon_hits(name)
    return hits[0][2] if hits else None


# ----------------------------------------------------------- compound words

# Rule sellers.compound: a shop name as the first part of a compound.
#   "in die dm-Märkte zurückzubringen"      "in allen „Go Asia“-Filialen"
_SHOP_HEAD = r"-(?:Filial\w*|Märkte\w*|Markt|Stores?|Shops?)\b"
_COMPOUND_QUOTED = re.compile(r"[„\"“‚']([^„“”\"'\n]{2,40})[“”\"']" + _SHOP_HEAD)
_COMPOUND = re.compile(r"(?<![\w-])([A-ZÄÖÜa-zäöü][\w&'.]*)" + _SHOP_HEAD)
_GENERIC_MODIFIERS = {
    "online", "bio", "super", "groß", "gross", "hof", "verbraucher", "wochen", "fach", "getränke", "drogerie",
    "einzelhandels", "internet", "web", "bau", "bauern", "naturkost",
}


def _compounds(text: str) -> list[tuple[int, str]]:
    found = [(m.start(1), m.group(1).strip()) for m in _COMPOUND_QUOTED.finditer(text)]
    for match in _COMPOUND.finditer(text):
        modifier = match.group(1)
        if modifier.lower() not in _GENERIC_MODIFIERS and (modifier[0].isupper() or _as_known_shop(modifier)):
            found.append((match.start(1), modifier))
    return found


# ------------------------------------------------------------- list of shops

_PREPOSITION = re.compile(r"\b(?:über|bei|in|im|von|vom|zwischen|am|an|durch|zum|zur)\b")
_VERB = re.compile(r"\b(?:ist|sind|wird|wurde|wurden|werden|kann|können|hat|haben|erfolgte|liegen)\b")
_QUANTIFIERS = {
    "diverse", "verschiedene", "weitere", "mehrere", "ausgewählte", "ausgewählten", "alle", "allen", "einige", "eigene",
    "eigenen", "eigener", "firmeneigene", "rein", "lokaler", "sowie", "siehe", "vor", "ort",
}


def _is_list(text: str) -> bool:
    """A bare list of shops ("EDEKA, Marktkauf") rather than a sentence."""
    return not (_PREPOSITION.search(text) or _VERB.search(text))


def _is_channel_word(word: str) -> bool:
    lowered = word.lower().strip(".,")
    return (
        not word[:1].isupper()
        or word.endswith("-")
        or lowered in _QUANTIFIERS
        or bool(re.search(r"(?:isch|lich)(?:e|en|er|es)?$", lowered))  # "Asiatische", "Afrikanische"
        or any(row[0] in lowered for row in lexicons.load("channels.tsv"))
    )


def _list_items(text: str) -> list[tuple[int, str]]:
    """Rule sellers.list: the items of a shop list that are names, not sales channels.
    "Edeka (Einzelhandel und Großhandel), Globus, Hamberger Großmarkt, ..." -> "Hamberger Großmarkt" (the others are in the lexicon)"""
    items = []
    without_brackets = re.sub(r"\([^)]*\)", " ", text)
    for line in without_brackets.split("\n"):
        line = line.split(":")[-1]  # "Treets Salted Peanuts Vegan 200 Gramm: Edeka, Globus" -> "Edeka, Globus"
        for item in re.split(r"\s*[,;]\s*|\s+(?:und|sowie|oder)\s+", line):
            item = item.strip()
            words = item.split()
            if not words or any(ch.isdigit() for ch in item) or _lexicon_hits(item):
                continue
            if not all(_is_channel_word(word) for word in words):
                items.append((text.find(item), item))
    return items


# ------------------------------------------------- sentence patterns (spaCy)

_SELLING_VERBS = ["vertrieben", "verkauft", "angeboten", "vertreibt", "verkaufen", "vertreiben", "erworben", "gekauft"]
_matchers: dict[int, object] = {}


def _dependency_matcher(vocab):
    if id(vocab) not in _matchers:
        from spacy.matcher import DependencyMatcher

        matcher = DependencyMatcher(vocab)
        # verb of selling  ->  preposition "über" / "bei" / "durch"  ->  proper noun
        #   "Das Produkt wurde online über Amazon vertrieben."      "Der Artikel wurde bei Aldi Nord zum Verkauf angeboten."
        matcher.add(
            "SOLD_VIA",
            [[
                {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LOWER": {"IN": _SELLING_VERBS}}},
                {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "prep", "RIGHT_ATTRS": {"POS": "ADP", "LOWER": {"IN": ["über", "bei", "durch"]}}},
                {"LEFT_ID": "prep", "REL_OP": ">", "RIGHT_ID": "shop", "RIGHT_ATTRS": {"POS": "PROPN"}},
            ]],
        )
        _matchers[id(vocab)] = matcher
    return _matchers[id(vocab)]


def shops_by_dependency(doc) -> list[str]:
    """Rule sellers.sentence_pattern (a): a proper noun governed by "über" or "bei" under a verb of selling."""
    shops = []
    for _, (_, _, shop_index) in _dependency_matcher(doc.vocab)(doc):
        start = end = shop_index
        while start > 0 and doc[start - 1].pos_ == "PROPN":
            start -= 1
        while end + 1 < len(doc) and doc[end + 1].pos_ == "PROPN":
            end += 1
        name = doc[start : end + 1].text
        if name not in shops:
            shops.append(name)
    return shops


_GENERIC_HEADS = {"handelsketten", "handelskette", "firma", "firmen", "unternehmen", "unternehmens", "märkte", "märkten"}


def _named_companies(doc) -> list[tuple[int, str]]:
    """Rule sellers.sentence_pattern (b): the name after "Firma", or after "Filialen der / von".
    "im Hofladen der Firma Wilder Wand in Hollenbach"   "in den Filialen der Fleisch- und Wurstwaren Schmalkalden GmbH Thüringen verkauft" """
    found = []
    i = 0
    while i < len(doc):
        token = doc[i]
        start = None
        if token.lower_ == "firma":
            start = i + 1
        elif token.lower_ in {"filialen", "filiale"} and i + 1 < len(doc) and doc[i + 1].lower_ in {"der", "des", "von"}:
            start = i + 2
            if start < len(doc) and doc[start].lower_ in {"der", "des"}:
                start += 1
        if start is not None:
            while start < len(doc) and doc[start].lower_ in _GENERIC_HEADS:
                start += 1
            end = start
            while end < len(doc):
                word = doc[end]
                joins_names = word.lower_ in {"und", "&"} and end + 1 < len(doc) and doc[end + 1].text[:1].isupper() and end > start
                if word.pos_ in {"PUNCT", "ADP", "VERB", "AUX", "NUM"} or not (word.text[:1].isupper() or joins_names):
                    break
                end += 1
            if end > start:
                found.append((doc[start].idx, doc[start:end].text))
                i = end
                continue
        i += 1
    return found


# ------------------------------------------------------------------- extract

def _read(text: str, nlp, *, sales_field: bool) -> tuple[list[str], list[str]]:
    """Shops named in a text, in order of appearance, and the rules that found them."""
    found: list[tuple[int, str, str]] = [(start, shop, "lexicon") for start, _, shop in _lexicon_hits(text)]
    found += [(position, _as_known_shop(name) or name, "compound") for position, name in _compounds(text)]
    if sales_field:
        if _POSTCODE.search(text) or re.search(r"(?m)^[^:\n]{3,48}:\s*$", text):
            # Rule sellers.address: the field holds a company with its address.
            #   "Al Rabie Lebensmittelgeschäft / Eisenbahnstraße 57 / 04315 Leipzig"
            found += [(text.find(name), _as_known_shop(name) or name, "address") for name in company_names(text)]
        elif _is_list(text):
            found += [(position, name, "list") for position, name in _list_items(text)]
    if nlp is not None and not _is_list(text):
        flat = re.sub(r"\s+", " ", text)
        doc = nlp(flat)
        found += [(flat.find(name), _as_known_shop(name) or name, "sentence_pattern") for name in shops_by_dependency(doc)]
        if sales_field:
            found += [(position, _as_known_shop(name) or name, "sentence_pattern") for position, name in _named_companies(doc)]
    shops: list[str] = []
    rules: list[str] = []
    order = {"lexicon": 0, "compound": 1, "address": 2, "list": 3, "sentence_pattern": 4}
    for _, shop, rule in sorted(found, key=lambda item: (item[0], order[item[2]])):
        if shop not in shops:
            shops.append(shop)
            if rule not in rules:
                rules.append(rule)
    return shops, sorted(rules, key=order.get)


def extract(notice: NoticeText, nlp=None) -> FieldValue:
    """`nlp`: a spaCy pipeline for the sentence patterns; without it only lexicon, compound and list rules run."""
    sold_via = notice.sections.get("sold_via", "").strip()
    if sold_via:
        # Rule sellers.lexicon: a known retailer in the page field "Vertrieb über".   "ALDI Nord und ALDI SÜD" -> Aldi Nord, Aldi Süd
        shops, rules = _read(sold_via, nlp, sales_field=True)
        if shops:
            return FieldValue(values=shops, source="rule", rule="sellers." + "+".join(rules), evidence=one_line(sold_via))
        if _NO_INFORMATION.search(sold_via):
            return FieldValue.empty("sellers.stated_unknown")  # "Die Vertriebswege sind nicht bekannt."
        return FieldValue.empty("sellers.no_named_seller")  # "verschiedene Einzelhändler"
    # No sales field: a shop may still be named where the notice says how to return the product.
    for name in ("recommendation", "more_info", "update_notes"):
        text = notice.sections.get(name, "")
        shops, rules = _read(text, nlp, sales_field=False) if text else ([], [])
        if shops:
            return FieldValue(values=shops, source="rule", rule="sellers." + "+".join(rules), evidence=one_line(text))
    return FieldValue.empty()
