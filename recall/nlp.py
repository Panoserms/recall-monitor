"""The spaCy pipeline, loaded once and only when a rule needs it."""
from __future__ import annotations

from functools import lru_cache

MODEL = "de_core_news_sm"


@lru_cache(maxsize=1)
def get_nlp():
    import spacy

    return spacy.load(MODEL)
