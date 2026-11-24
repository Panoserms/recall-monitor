"""date, states, reason_category, reason_text. Inputs are real texts from the portal."""
import pytest

from recall.models import NoticeText
from recall.rules import date, reason_category, reason_text, states


def notice(id="261106_05_SH_Rindfleischsalamiprodukte", pub_date="2026-11-09T09:22:00+01:00", **sections) -> NoticeText:
    return NoticeText(id=id, title=sections.pop("title", "t"), link="t", pub_date=pub_date, sections=sections)


# ---------------------------------------------------------------------- date

def test_date_is_the_first_publication_shown_on_the_page():
    found = date.extract(notice(first_published="06.11.2026", last_updated="09.11.2026"))

    assert (found.values, found.source, found.rule) == (["2026-11-06"], "structured", "date.first_published")


@pytest.mark.parametrize(
    "notice_id, want",
    [
        ("261109_09_NI_Corned_Beef", "2026-11-09"),
        ("20260701_01_ST_Thymiangewuerzmischung", "2026-07-01"),
        ("180621_BY_aerobic_stabilized", "2018-06-21"),
    ],
)
def test_without_a_page_the_date_is_read_from_the_link(notice_id, want):
    found = date.extract(notice(id=notice_id, pub_date="2026-11-10T14:35:00+01:00"))

    assert (found.values, found.source, found.rule) == ([want], "rule", "date.from_link")


def test_without_page_and_dated_link_the_feed_date_is_used():
    found = date.extract(notice(id="n_0123456789ab", pub_date="2026-11-10T14:35:00+01:00"))

    assert (found.values, found.source, found.rule) == (["2026-11-10"], "structured", "date.feed_pubdate")


# -------------------------------------------------------------------- states

def test_states_from_the_feed_are_split_at_commas():
    found = states.extract(notice(states="Bremen, Hamburg, Mecklenburg-Vorpommern, Niedersachsen, Schleswig-Holstein"))

    assert found.values == ["Bremen", "Hamburg", "Mecklenburg-Vorpommern", "Niedersachsen", "Schleswig-Holstein"]
    assert (found.source, found.rule) == ("structured", "states.field")


def test_states_from_the_page_are_split_at_line_breaks():
    found = states.extract(notice(states="Baden-Württemberg\nBayern\nBerlin"))

    assert found.values == ["Baden-Württemberg", "Bayern", "Berlin"]


def test_text_that_is_not_a_federal_state_is_left_out():
    found = states.extract(notice(states="Bayern, Österreich"))

    assert found.values == ["Bayern"]


def test_no_states_field_gives_nothing():
    assert states.extract(notice()).values == []


# ----------------------------------------------------------- reason category

@pytest.mark.parametrize(
    "more_info, want, rule",
    [
        (
            "Es kann nicht ausgeschlossen werden, dass im oben genannten Artikel Salmonellen auftreten können.",
            "salmonella",
            "reason_category.salmonella_in_text",
        ),
        ("Mikrobielle Kontamination mit Listeria monocytogenes", "listeria", "reason_category.listeria_in_text"),
        (
            "Der Rückruf erfolgt vorsorglich, weil in einer Einzeluntersuchung Shigatoxinbildende Escherichia coli (STEC) nachgewiesen wurden.",
            "other",
            "reason_category.other_pathogen",
        ),
        ("Es kann nicht ausgeschlossen werden, dass in dem betroffenen Produkt Noroviren enthalten sind.", "other", "reason_category.other_pathogen"),
    ],
)
def test_pathogen_is_read_from_the_reason_text(more_info, want, rule):
    found = reason_category.extract(notice(reason_official="Krankheitserreger", more_info=more_info))

    assert (found.values, found.source, found.rule) == ([want], "rule", rule)
    assert found.evidence == more_info


@pytest.mark.parametrize(
    "official, want",
    [
        ("Fremdkörper", "foreign_object"),
        ("Allergene", "undeclared_allergen"),
        ("Rückstände und Kontaminanten", "other"),
        ("Gesundheitsschädliche Substanz", "other"),
        ("Sonstige Gründe", "other"),
        # two official reasons: the more specific one wins
        ("Rückstände und Kontaminanten, Fremdkörper", "foreign_object"),
        ("Rückstände und Kontaminanten, Allergene", "undeclared_allergen"),
        ("Gesundheitsschädliche Substanz\nRückstände und Kontaminanten", "other"),
    ],
)
def test_official_reason_is_mapped_to_the_category(official, want):
    found = reason_category.extract(notice(reason_official=official, more_info="Der Höchstwert für Glycidol ist überschritten."))

    assert (found.values, found.source, found.rule) == ([want], "structured", "reason_category.official")


def test_salmonella_named_in_the_text_wins_over_another_official_reason():
    found = reason_category.extract(
        notice(reason_official="Sonstige Gründe", more_info="Im Rahmen einer Eigenuntersuchung wurden Salmonellen nachgewiesen.")
    )

    assert found.values == ["salmonella"]


def test_pathogen_notice_without_reason_text_stays_open():
    # feed only: the feed says "Krankheitserreger" but never names the pathogen
    found = reason_category.extract(notice(reason_official="Krankheitserreger"))

    assert (found.values, found.source, found.rule) == ([], "none", "reason_category.pathogen_not_named")


def test_no_official_reason_and_no_text_gives_nothing():
    found = reason_category.extract(notice())

    assert (found.values, found.source, found.rule) == ([], "none", None)


# --------------------------------------------------------------- reason text

def test_reason_text_is_the_further_information_of_the_page():
    text = "In einem Glas des betroffenen Produkts wurden Glassplitter festgestellt."

    found = reason_text.extract(notice(more_info=text))

    assert (found.values, found.source, found.rule) == ([text], "structured", "reason_text.more_info")


def test_reason_text_spread_over_lines_becomes_one_line():
    found = reason_text.extract(notice(more_info="Daher ist in den betroffenen Gläsern das Allergen\nCashew enthalten."))

    assert found.values == ["Daher ist in den betroffenen Gläsern das Allergen Cashew enthalten."]


def test_without_further_information_there_is_no_reason_text():
    found = reason_text.extract(notice(product="Deutsches Corned Beef, 160 Gramm"))

    assert (found.values, found.source) == ([], "none")
