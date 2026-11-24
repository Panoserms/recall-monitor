"""Stage 4: make product names and brands comparable.

    fold         lower case, umlauts spelt out ("Käse" and "Kaese" are written both ways in notices)
    tokens       pack sizes, numbers, punctuation and filler words removed
    split        compounds split at their head with a small food lexicon ("rinderhackfleisch" -> rinder + hackfleisch)
    brand_key    one key for every spelling of a brand ("Gut&Günstig", "GUT & GÜNSTIG", "gut und günstig")
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from . import config, lexicons
from .textutils import SIZE

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e", "á": "a", "à": "a", "ç": "c", "ñ": "n"})
FILLER = {
    "und", "mit", "in", "im", "der", "die", "das", "des", "dem", "den", "aus", "von", "vom", "zum", "zur", "fuer",
    "ohne", "auf", "am", "an", "ein", "eine", "einer", "oder", "sowie", "bzw", "je", "ca", "x", "er", "pack", "packung",
}


def fold(text: str) -> str:
    return text.casefold().translate(_FOLD)


def tokens(text: str) -> list[str]:
    """Content words of a product name, folded, in order."""
    words = re.findall(r"[a-z0-9]+", fold(SIZE.sub(" ", text)))
    return [w for w in words if w not in FILLER and not w.isdigit()]


@lru_cache(maxsize=1)
def _food_words() -> frozenset[str]:
    return frozenset(row[0] for row in lexicons.load("food_words.tsv"))


def _split_once(word: str, words: frozenset[str]) -> tuple[str, str] | None:
    """(modifier, head) at the longest lexicon word the word ends with; both parts at least 3 letters."""
    for i in range(3, len(word) - 2):
        if word[i:] in words:
            return word[:i], word[i:]
    return None


@lru_cache(maxsize=4096)
def split_compound(word: str) -> list[str]:
    """Parts of a compound, outermost first: modifier, head, then the head's own parts. [] = not a compound."""
    words = _food_words()
    split = _split_once(word, words)
    if split is None:
        return []
    modifier, head = split
    if word in words and modifier not in words:
        return []  # a listed word is lexicalised ("himbeeren", "schwein") unless it is two listed words
    return [modifier, head] + split_compound(head)


@lru_cache(maxsize=1)
def _brand_aliases() -> dict[str, str]:
    """key of a spelling -> key of the brand's one name. From lexicons/brands.tsv and data/brand_aliases.csv."""
    rows = [(row[0], row[1]) for row in lexicons.load("brands.tsv") if len(row) > 1]
    if config.BRAND_ALIASES.exists():
        with config.BRAND_ALIASES.open(encoding="utf-8-sig", newline="") as handle:
            rows += [(r.get("canonical", ""), r.get("variant", "")) for r in csv.DictReader(handle)]
    return {_key(variant): _key(canonical) for canonical, variant in rows if canonical and variant}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9!]", "", fold(text).replace("&", "und"))


def brand_key(brand: str) -> str:
    key = _key(brand)
    return _brand_aliases().get(key, key)
