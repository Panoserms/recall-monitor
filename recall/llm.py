"""Stage 3: the local model, only for fields the rules left open.

The model (Gemma via Ollama) gets the few sections of the notice where the field could
be written, and a JSON schema that allows nothing but those fields. Its answer is
trusted only where it can be found again in those sections: a value that is not in the
notice is dropped, so the model can point at text but cannot invent it.
Switch it off with `recall extract --no-llm`.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable

from . import config
from .companies import _LEGAL_FORM, _is_name
from .models import FieldValue, NoticeText
from .parse import LABELS
from .rules import ean
from .rules.sellers import _as_known_shop, _is_channel_word
from .textutils import SIZE, UNKNOWN, find_dates, one_line, unique

Transport = Callable[[str, "dict | None"], dict]


class OllamaUnavailable(Exception):
    """Ollama is not running or the model is not installed."""


def urllib_transport(path: str, payload: dict | None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(config.OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


# field -> (sections the value may be written in, what the model is told to look for)
_FIELDS: dict[str, tuple[tuple[str, ...], str]] = {
    "product_name": (("title", "product"), "name of the recalled product, without pack size"),
    "brand": (("title", "product", "marking"), "brand name printed on the product; not the full product name"),
    "manufacturer": (("manufacturer",), "company that made or distributes the product"),
    "batch": (("batch", "marking", "package", "best_before"), "batch or lot numbers (Charge, Los, Lot), exactly as printed"),
    "best_before": (("best_before", "batch", "marking", "package"), "best-before or use-by dates (MHD), exactly as printed"),
    "sellers": (("sold_via", "recommendation", "more_info", "update_notes"), "names of shops or chains that sold the product"),
}
_GERMAN_LABEL = {name: label for label, name in LABELS.items()} | {"title": "Titel"}

# The examples are made up for the prompt; none is taken from a real notice.
SYSTEM = (
    "You read German food recall notices. For each field, copy the value exactly as it is written in the notice. "
    "Never translate, complete or guess. If the notice does not state a value, give an empty list.\n"
    "brand: the proper name of a brand on the pack, e.g. 'Sonnhof' in 'Sonnhof Apfelmus, 700 Gramm'. "
    "A food word is never a brand ('Apfelmus', 'Reis', 'Käse'); 'Apfelmus, 700 Gramm' has no brand.\n"
    "batch: codes after Charge, Los or Lot. Dates and EAN/GTIN barcodes are never batch numbers.\n"
    "sellers: shops or supermarket chains where customers bought the product. "
    "The manufacturer, importer or the company asking for returns is not a seller."
)


def _norm(text: str) -> str:
    text = text.casefold().replace("„", '"').replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _context(notice: NoticeText, sections: tuple[str, ...]) -> str:
    texts = {**notice.sections, "title": notice.title}
    return "\n".join(f"{_GERMAN_LABEL.get(s, s)}: {texts[s]}" for s in sections if texts.get(s, "").strip())


_GENERIC_BRANDS = {
    "bio", "öko", "oeko", "eco", "organic", "natur", "naturland", "bio naturland", "bioland", "demeter",
    "premium", "classic", "original",
}


def _is_batch(value: str) -> bool:
    """Guard: the first full run (2026-11-12) put dates and barcodes into batch."""
    if not any(ch.isdigit() for ch in value) or len(value) > 30 or len(value.split()) > 4:
        return False
    if re.search(r"(?i)\b(?:EAN|GTIN)", value) or ean.valid(re.sub(r"\D", "", value)):
        return False
    return not find_dates(value, short_years=True)


def _is_company(value: str) -> bool:
    """Guard: the first full run gave a country, an e-mail address and "Unbekannt" as manufacturer."""
    return not UNKNOWN.match(value) and _is_name(value)


def _is_seller(value: str, notice: NoticeText) -> bool:
    """Guard: the first full run named the recalling company (from the contact sentence) as seller."""
    if all(_is_channel_word(word) for word in value.split()):
        return False
    if _as_known_shop(value):
        return True
    makers = _norm(notice.sections.get("manufacturer", "") + "\n" + notice.sections.get("contact", ""))
    return _norm(value) not in makers and not _LEGAL_FORM.search(value)


def _has_food_word(value: str) -> bool:
    """"Bio Basmati Reis", "Schnittkaese" (head kaese): a common food noun, not a proper name."""
    from .normalise import _food_words, split_compound, tokens

    return any(word in _food_words() or split_compound(word) for word in tokens(value))


def _is_brand(value: str, notice: NoticeText) -> bool:
    """Guard: the second full run gave food words ("Schnittkaese", "Pfeffer Schwarz") as brands."""
    raw_lines = [notice.title, notice.sections.get("product", ""), *notice.sections.get("product", "").split("\n")]
    whole = set()
    for t in raw_lines:
        cleaned = _norm(SIZE.sub(" ", t)).strip(" ,")
        whole.add(cleaned)
        whole.add(_norm(re.sub(r"\([^)]*\)", " ", SIZE.sub(" ", t))).strip(" ,"))
        whole.add(_norm(re.sub(r"^\d{5,}\s*[-–]\s*|\bbio\b", " ", SIZE.sub(" ", t), flags=re.I)).strip(" ,"))
    return (
        len(value) <= 40
        and _norm(value) not in whole
        and _norm(value) not in _GENERIC_BRANDS
        and not _has_food_word(value)
    )


def _checked(field: str, answers: list[str], notice: NoticeText, context: str) -> list[str]:
    """The answers that can be found in the notice text and pass the field's guard; the rest is dropped."""
    kept: list[str] = []
    in_context = _norm(context)
    for answer in answers:
        value = answer.strip() if isinstance(answer, str) else ""
        if not value:
            continue
        if field == "best_before":  # compare as dates: "31.08.2028" in the answer, "(31.08.2028)" in the text
            context_dates = {d.iso for d in find_dates(context, short_years=True)}
            kept += [d.iso for d in find_dates(value, short_years=True) if d.iso in context_dates]
            continue
        if _norm(value) not in in_context:
            continue
        if field == "batch" and _is_batch(value):
            kept.append(value)
        elif field == "manufacturer" and _is_company(value):
            kept.append(value)
        elif field == "sellers" and _is_seller(value, notice):
            kept.append(_as_known_shop(value) or value)
        elif field == "brand" and _is_brand(value, notice):
            kept.append(value)
        elif field == "product_name":
            kept.append(value)
    return unique(kept)


class OllamaFallback:
    def __init__(self, model: str, transport: Transport):
        self.model = model
        self.transport = transport

    @classmethod
    def connect(cls, model: str = config.OLLAMA_MODEL, transport: Transport = urllib_transport) -> "OllamaFallback":
        try:
            tags = transport("/api/tags", None)
        except OSError as error:
            raise OllamaUnavailable(f"Ollama is not reachable at {config.OLLAMA_URL} ({error})") from error
        names = {m.get("name", "") for m in tags.get("models", [])}
        if model not in names and f"{model}:latest" not in names:
            raise OllamaUnavailable(f"model {model} is not installed (ollama pull {model})")
        return cls(model, transport)

    def __call__(self, notice: NoticeText, open_fields: list[str]) -> dict[str, FieldValue]:
        asked = {}
        for field in open_fields:
            if field in _FIELDS:
                context = _context(notice, _FIELDS[field][0])
                if context:
                    asked[field] = context
        if not asked:
            return {}
        schema = {
            "type": "object",
            "properties": {f: {"type": "array", "items": {"type": "string"}, "description": _FIELDS[f][1]} for f in asked},
            "required": list(asked),
        }
        fields_text = "\n".join(f"- {f}: {_FIELDS[f][1]}" for f in asked)
        notice_text = "\n".join(unique([line for context in asked.values() for line in context.split("\n")]))
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Fields:\n{fields_text}\n\nNotice:\n{notice_text}"},
            ],
        }
        try:
            answer = json.loads(self.transport("/api/chat", payload)["message"]["content"])
        except (OSError, KeyError, ValueError, TypeError):
            return {}
        found = {}
        for field, context in asked.items():
            values = answer.get(field) if isinstance(answer, dict) else None
            if isinstance(values, list):
                kept = _checked(field, values, notice, context)
                if kept:
                    found[field] = FieldValue(values=kept, source="model", rule=f"model.{self.model}", evidence=one_line(context))
        return found
