"""Stage 3: the model fallback. Ollama is replaced by a fake; no network, no model."""
import json

import pytest

from recall.llm import OllamaFallback, OllamaUnavailable
from recall.models import NoticeText

# real texts from the portal (pages saved 2026-11-11)
COCONUT = NoticeText(
    id="241210_08_NW_KokosnussGetrocknet",
    title="Annam – Trockene Kokosnuss Halbschnitt 350 Gramm",
    link="t",
    pub_date="2025-01-03T11:57:00+01:00",
    sections={
        "product": "Annam – Trockene Kokosnuss Halbschnitt 350 Gramm",
        "recommendation": "Verbraucher können sich die betroffene Ware erstatten lassen oder diese entsorgen.",
        "manufacturer": "Transfood Großhandel",
    },
)


class FakeOllama:
    def __init__(self, answer: dict | str, models=("gemma4:e2b-it-qat",)):
        self.answer = answer
        self.models = models
        self.requests: list[tuple[str, dict | None]] = []

    def __call__(self, path: str, payload: dict | None) -> dict:
        self.requests.append((path, payload))
        if path == "/api/tags":
            return {"models": [{"name": m} for m in self.models]}
        content = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return {"message": {"content": content}}


def fallback(answer, **kwargs) -> tuple[OllamaFallback, FakeOllama]:
    fake = FakeOllama(answer, **kwargs)
    return OllamaFallback.connect(model="gemma4:e2b-it-qat", transport=fake), fake


def test_connect_fails_clearly_when_the_model_is_not_installed():
    with pytest.raises(OllamaUnavailable, match="not installed"):
        OllamaFallback.connect(model="gemma4:e2b-it-qat", transport=FakeOllama({}, models=("llama3:8b",)))


def test_connect_fails_clearly_when_ollama_is_not_running():
    def down(path, payload):
        raise OSError("Connection refused")

    with pytest.raises(OllamaUnavailable, match="not reachable"):
        OllamaFallback.connect(model="gemma4:e2b-it-qat", transport=down)


def test_the_schema_asks_only_for_open_fields_that_have_text_to_look_in():
    ask, fake = fallback({"brand": ["Annam"]})
    ask(COCONUT, ["brand", "batch"])  # no batch, marking or package text: batch is not asked
    _, payload = fake.requests[-1]
    assert list(payload["format"]["properties"]) == ["brand"]
    assert payload["options"]["temperature"] == 0


def test_a_value_found_in_the_notice_is_kept_and_marked_as_model():
    ask, _ = fallback({"brand": ["Annam"]})
    found = ask(COCONUT, ["brand"])
    assert found["brand"].values == ["Annam"]
    assert found["brand"].source == "model"
    assert found["brand"].rule == "model.gemma4:e2b-it-qat"


def test_a_value_the_notice_does_not_contain_is_dropped():
    ask, _ = fallback({"brand": ["Kokosnuss King"], "sellers": ["Lidl"]})
    found = ask(COCONUT, ["brand", "sellers"])
    assert found == {}


def test_a_brand_that_is_the_whole_product_name_is_dropped():
    ask, _ = fallback({"brand": ["Annam – Trockene Kokosnuss Halbschnitt 350 Gramm"]})
    assert ask(COCONUT, ["brand"]) == {}


def test_best_before_answers_become_iso_dates_and_must_be_in_the_text():
    notice = NoticeText(
        id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00",
        sections={"marking": "Charge und Mindesthaltbarkeitsdatum (31.08.2028) finden Sie auf dem Boden der Dose."},
    )
    ask, _ = fallback({"best_before": ["31.08.2028", "01.01.2029"]})
    assert ask(notice, ["best_before"])["best_before"].values == ["2028-08-31"]


def test_sellers_are_spelt_like_the_rules_spell_them():
    notice = NoticeText(
        id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00",
        sections={"more_info": "Die Ware wurde in einzelnen EDEKA-Märkten in Bayern angeboten."},
    )
    ask, _ = fallback({"sellers": ["EDEKA"]})
    assert ask(notice, ["sellers"])["sellers"].values == ["Edeka"]


def test_a_broken_answer_gives_nothing_and_does_not_crash():
    ask, _ = fallback("{not json")
    assert ask(COCONUT, ["brand"]) == {}


# ---- guards against the error types seen in the first full run (2026-11-12) ----

def _notice(**sections) -> NoticeText:
    return NoticeText(id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


@pytest.mark.parametrize("answer", ["31/01/2028", "4337185826788", "GTIN4063367234613", "31.05.2027 bis 02.07.2027"])
def test_dates_and_barcodes_are_not_batch_numbers(answer):
    notice = _notice(batch=f"Chargenangabe: {answer}")
    ask, _ = fallback({"batch": [answer]})
    assert ask(notice, ["batch"]) == {}


def test_a_real_looking_code_is_kept_as_batch():
    notice = _notice(marking="Identitätskennzeichen: DK M277 EU")
    ask, _ = fallback({"batch": ["DK M277 EU"]})
    assert ask(notice, ["batch"])["batch"].values == ["DK M277 EU"]


@pytest.mark.parametrize("answer", ["Türkei", "info@48grup.com", "www.goldq7bitkisel.com, Türkei", "Unbekannt"])
def test_countries_addresses_and_unknown_are_not_manufacturers(answer):
    notice = _notice(manufacturer=f"Hersteller: {answer}")
    ask, _ = fallback({"manufacturer": [answer]})
    assert ask(notice, ["manufacturer"]) == {}


def test_the_company_that_recalls_is_not_a_seller():
    notice = _notice(
        manufacturer="Feinkost Reich GmbH\nIndustriestraße 1\n12345 Ort",
        recommendation="Kunden können das Produkt bei der Feinkost Reich GmbH zurückgeben.",
    )
    ask, _ = fallback({"sellers": ["Feinkost Reich GmbH"]})
    assert ask(notice, ["sellers"]) == {}


def test_a_company_with_a_legal_form_is_not_a_seller_unless_it_is_a_known_shop():
    notice = _notice(more_info="Vertrieben über die Nergiz Großmarkt GmbH und Kaufland Dienstleistung GmbH & Co. KG.")
    ask, _ = fallback({"sellers": ["Nergiz Großmarkt GmbH", "Kaufland Dienstleistung GmbH & Co. KG"]})
    assert ask(notice, ["sellers"])["sellers"].values == ["Kaufland"]


@pytest.mark.parametrize("answer", ["bio", "Bio"])
def test_a_generic_word_is_not_a_brand(answer):
    notice = _notice(product="bio Bread Baking Mix – OATS, 600 Gramm")
    ask, _ = fallback({"brand": [answer]})
    assert ask(notice, ["brand"]) == {}


@pytest.mark.parametrize("answer", ["Schnittkaese", "Bio Basmati Reis", "Pfeffer Schwarz", "Bio Dattelsirup", "Hausmacher Blutwurst"])
def test_a_food_word_is_not_a_brand(answer):
    # real wrong answers of the second full run (2026-11-12); brands are proper names, not food nouns
    notice = _notice(product=f"{answer} und mehr")
    ask, _ = fallback({"brand": [answer]})
    assert ask(notice, ["brand"]) == {}


@pytest.mark.parametrize("answer", ["Kölln", "Snackmaster", "Royal Honey", "Gourmet Celebi"])
def test_proper_names_stay_brands(answer):
    notice = _notice(product=f"{answer} Produkt, 200 Gramm")
    ask, _ = fallback({"brand": [answer]})
    assert ask(notice, ["brand"])["brand"].values == [answer]
