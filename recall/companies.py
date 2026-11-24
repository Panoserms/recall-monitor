"""Read company names out of a name-and-address block.

Shared by the manufacturer rule and the sellers rule. The portal writes companies as
    [role label:] name line / street line / postcode and town [/ country]
so the name is the first line of each block; a role label or the line after a
postcode starts the next block.
"""
from __future__ import annotations

import re

from . import lexicons
from .textutils import unique

# "Hersteller:", "Inverkehrbringer/ Hergestellt für:", "Deklarierter Hersteller:", "Großhändler:", "Vertrieb Deutschland:"
_LABELLED = re.compile(r"^(?P<label>[^:\n]{3,48}?):\s*(?P<rest>.*)$")
_ROLE_STEMS = (
    "herstell", "hergestellt", "inverkeh", "importeur", "import", "lieferant", "händler", "haendler", "vertrieb",
    "verantwortlich", "abfüller", "abfueller", "verpack", "produzent", "erzeuger", "anbieter", "versender", "probeentnahme",
)
# "Verwaltung/Büro: conneKT 46," is part of an address, not a new company
_ADDRESS_STEMS = ("verwaltung", "büro", "buero", "sitz", "anschrift", "adresse", "mail", "telefon", "tel", "website", "internet", "fax")
# "26197 Großenkneten", "D-22291 Hamburg", "3508 TB Utrecht (NL)", "IT 58022 Follonica (GR)", "Taman City, 51200 Kuala Lumpur"
_POSTCODE = re.compile(r"(?:^|[\s,])(?:[A-Z]{1,2}[- ])?\d{4,5}\s+(?:[A-Z]{2}\s+)?[A-ZÄÖÜ]")
_LEGAL_FORM = re.compile(
    r"\bGmbH\b|\bAG\b|\bKG\b|\bOHG\b|\bGbR\b|\bUG\b|\be\.\s?K\b|\bSE\b|\bB\.?V\.?(?!\w)|\bN\.?V\.?(?!\w)|\bS\.L\.|\bS\.A\."
    r"|\bS\.?r\.?l\.?(?!\w)|\bS\.p\.A\.|\bLtd\b|\bLTD\b|\bInc\b|\bLLC\b|\bStiftung\b|\bŞti\b|\bSti\b|\bSDN BHD\b"
    r"|\bCorporation\b|\bCompany\b|Gesellschaft mit beschr"
)
# "Eine verantwortliche Person in der EU ist nicht angegeben." / "Die Vertriebswege sind nicht bekannt."
_NO_INFORMATION = re.compile(r"(?i)nicht angegeben|nicht bekannt|unbekannt|keine angaben?|liegen nicht vor")
_SENTENCE_VERB = re.compile(r"\b(?:ist|sind|wird|wurde|wurden|werden|kann|können|hat|haben)\b")
_WEB_OR_CODE = re.compile(r"(?i)\bwww\.|https?://|@|^(?:code|nr|no)\b|\b(?:Mah|Bul)\.\s")
_BARE_ROLE = re.compile(
    r"(?i)^(?:Deklarierter\s+)?(?:Hersteller|Inverkehrbringer|Importeur|Lieferant|Händler|Großhändler|Vertrieb|Produzent|Erzeuger)\b\s*:?\s*(?P<rest>.*)$"
)


def _countries() -> set[str]:
    return {row[0].lower() for row in lexicons.load("countries.tsv")}


def _is_sentence(line: str) -> bool:
    return bool(_NO_INFORMATION.search(line)) or (
        len(line.split()) >= 7 and line.rstrip().endswith(".") and bool(_SENTENCE_VERB.search(line))
    )


def _is_name(candidate: str) -> bool:
    if len(candidate) < 2 or not any(ch.isalpha() for ch in candidate):
        return False
    if _WEB_OR_CODE.search(candidate) or candidate.rstrip(".").lower() in _countries():
        return False
    return not _POSTCODE.match(" " + candidate)


def company_names(text: str) -> list[str]:
    names: list[str] = []
    inside_block = False  # True while reading the address lines of a company
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.lower() in {"und", "sowie", "oder"} or _is_sentence(line):
            inside_block = False
            continue
        labelled = _LABELLED.match(line)
        if labelled:
            label = labelled["label"].lower()
            if any(stem in label for stem in _ROLE_STEMS):
                inside_block = False
                line = labelled["rest"].strip()
                if not line:
                    continue
            elif any(stem in label for stem in _ADDRESS_STEMS):
                continue
        elif bare := _BARE_ROLE.match(line):
            inside_block = False
            line = bare["rest"].strip()
            if not line:
                continue
        if inside_block:
            if _POSTCODE.search(line):
                inside_block = False  # the address ends with postcode and town
                continue
            if not _LEGAL_FORM.search(line):
                continue  # street, district, country ...
            # a legal form ("GmbH") inside an address block: a second company without its own postcode line
        first = re.sub(r"^Firma\s+", "", line.split(", ")[0]).strip().rstrip(",;")
        for candidate in re.split(r"\s*//\s*", first):
            if _is_name(candidate):
                names.append(candidate)
        inside_block = not _POSTCODE.search(line)  # "Name, Straße 1, 12345 Ort" on one line is complete
    return unique(names)
