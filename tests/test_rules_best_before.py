"""Best-before dates. Every input is a real value of the portal's "Haltbarkeit" field (feed of 2026-11-11)."""
import pytest

from recall.models import NoticeText
from recall.rules import best_before


def notice(**sections) -> NoticeText:
    return NoticeText(id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


@pytest.mark.parametrize(
    "text, want",
    [
        ("Mindesthaltbarkeitsdatum: 01.03.2028, 05.03.2028 und 10.03.2028", ["2028-03-01", "2028-03-05", "2028-03-10"]),
        ("Mindestens haltbar bis: 23.02.2028", ["2028-02-23"]),
        ("Mindesthaltbarkeitsdatum: 05/05/2030", ["2030-05-05"]),
        ("27/03/2027", ["2027-03-27"]),
        ("Mindesthaltbarkeitsdaten:\n- 05/12/2027\n- 08/12/2027\n- 10/02/2028", ["2027-12-05", "2027-12-08", "2028-02-10"]),
        ("Mindesthaltbarkeitsdatum:\n04.11.2026 (L455)\n02.04.2027 (L455)", ["2026-11-04", "2027-04-02"]),
        # year first, as printed on imported goods
        ("Mindesthaltbarkeitsdatum: E2028/1/1", ["2028-01-01"]),
        ("12.09.2027\n(EXP 2027/09/12)", ["2027-09-12"]),
        ("mindestens haltbar bis: 04-06-2027", ["2027-06-04"]),
    ],
)
def test_full_dates_become_iso_dates(text, want):
    assert best_before.extract(notice(best_before=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Mindesthaltbarkeitsdatum 07.2028", ["2028-07"]),
        ("Mindesthaltbarkeitsdatum: 12/2028", ["2028-12"]),
        ("Mindesthaltbarkeitsdatum: EXP 10-2027", ["2027-10"]),
        ("Monat / Jahr: 06.2027", ["2027-06"]),
        ("Mindesthaltbarkeitsdatum: März/2028", ["2028-03"]),
        ("Mindesthaltbarkeitsdatum: 11/2027, 10/2027", ["2027-11", "2027-10"]),
        # "haltbar bis (Ende)" is the usual wording of a best-before date, not a range
        ("Mindestens haltbar bis Ende 04/2028", ["2028-04"]),
        ("Mindestens haltbar bis Ende: 01.2028", ["2028-01"]),
        ("bis Ende 06.2028", ["2028-06"]),
    ],
)
def test_month_and_year_only_keep_month_precision(text, want):
    assert best_before.extract(notice(best_before=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Mindeshaltbarkeitsdatum: zwischen 31.05.2027 bis einschließlich 02.07.2027", ["2027-05-31..2027-07-02"]),
        ("Mindesthaltbarkeitsdatum: alle Mindesthaltbarkeitsdaten vom 08.04.2027 bis 04.05.2027", ["2027-04-08..2027-05-04"]),
        ("Mindesthaltbarkeitsdatum von 09/2027 bis 10/2028", ["2027-09..2028-10"]),
        ("Mindesthaltbarkeitsdatum bis einschließlich 17.11.2026", ["..2026-11-17"]),
        (
            "Holzhauser Alkoholfreies Hefeweizen: Mindesthaltbarkeitsdatum bis 7/26; "
            "Holzhauser Alkoholfreies Helles: Mindesthaltbarkeitsdatum bis 11/26",
            ["..2026-07", "..2026-11"],
        ),
    ],
)
def test_ranges_keep_both_ends(text, want):
    assert best_before.extract(notice(best_before=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("alle Mindesthaltbarkeitsdaten", ["alle"]),
        ("Mindesthaltbarkeitsdaten: ALLE", ["alle"]),
        ("Es werden alle noch gültigen Mindesthaltbarkeitsdaten zurückgerufen.", ["alle"]),
        ("Alle Haltbarkeitsdaten werden vorsorglich zurückgerufen.", ["alle"]),
        ("alle", ["alle"]),
        ("sämtliche Mindesthalbarkeitsdatum", ["alle"]),  # typo in the original
        (
            "30.09.2027 / 30.10.2027 / 30.11.2027 (Aktuell Vertriebs GmbH) /\nalle Mindesthaltbarkeitsdaten (H&B Handelskontor GmbH)",
            ["2027-09-30", "2027-10-30", "2027-11-30", "alle"],
        ),
    ],
)
def test_all_dates_affected_is_reported_as_alle(text, want):
    assert best_before.extract(notice(best_before=text)).values == want


def test_plain_dates_are_marked_as_found_by_a_rule_with_the_text_as_evidence():
    found = best_before.extract(notice(best_before="Mindesthaltbarkeitsdatum: 23.02.2028"))

    assert (found.source, found.rule) == ("rule", "best_before.dates")
    assert found.evidence == "Mindesthaltbarkeitsdatum: 23.02.2028"


def test_notice_saying_the_date_is_unknown_gives_nothing_and_says_so():
    found = best_before.extract(notice(best_before="nicht bekannt"))

    assert (found.values, found.source, found.rule) == ([], "none", "best_before.stated_unknown")


def test_storage_advice_without_a_date_gives_nothing():
    found = best_before.extract(notice(best_before="bei - 18 Grad Celsius ab Abpackdatum 12 Monate haltbar"))

    assert (found.values, found.source, found.rule) == ([], "none", None)


def test_dates_paired_with_batch_numbers_are_read_from_the_batch_field():
    # the salami notice has no "Haltbarkeit" field; batch and date stand side by side
    found = best_before.extract(notice(batch="260904 23.10.2026;\n260907 26.10.2026;"))

    assert found.values == ["2026-10-23", "2026-10-26"]
    assert found.rule == "best_before.date_in_batch_field"


def test_dates_labelled_mhd_inside_the_batch_field_are_read():
    found = best_before.extract(notice(batch="Lotnummer: L140626V3 MHD: 13.06.2028\nLotnummer: L150626V3/ L150626N3 MHD: 14.06.2028"))

    assert found.values == ["2028-06-13", "2028-06-14"]


def test_a_batch_that_is_itself_a_date_is_not_a_best_before_date():
    found = best_before.extract(notice(batch="L: 06.12.2026, Uhrzeit 07:15 bis 10:27"))

    assert found.values == []


def test_dates_labelled_mhd_inside_the_marking_field_are_read():
    found = best_before.extract(
        notice(marking="Produkt: Zaban sweets\nVerpackungseinheit: 500 Gramm,\nMindesthaltbarkeitsdatum: 25.01.2027,\nBarcode: 7302852588587")
    )

    assert (found.values, found.source, found.rule) == (["2027-01-25"], "rule", "best_before.date_in_other_field")

