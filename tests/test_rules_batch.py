"""Batch numbers. Every input is a real value of the portal's "Chargennummer / Los-Kennzeichnung" field."""
import pytest

from recall.models import NoticeText
from recall.rules import batch


def notice(**sections) -> NoticeText:
    return NoticeText(id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


@pytest.mark.parametrize(
    "text, want",
    [
        ("Chargennummer: 090426", ["090426"]),
        ("Chargennummer 20052026", ["20052026"]),
        ("LOT - 119621", ["119621"]),
        ("Charge: L60471F\nCharge: L60472F", ["L60471F", "L60472F"]),
        ("Los-Nummer KMG/640.", ["KMG/640"]),
        ("Parti NO: 00.00.02", ["00.00.02"]),
        ("Referenznummer: IOT25-50158\nLot-Nummer: 165", ["IOT25-50158", "165"]),
        ("Der Rückruf betrifft die Losnummer L.26113A", ["L.26113A"]),
    ],
)
def test_code_after_a_batch_label(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("ME2552508", ["ME2552508"]),
        ("KHR", ["KHR"]),
        ("14 10 2027", ["14 10 2027"]),
        ("L 0126", ["L 0126"]),
        ("LC5 BD149T", ["LC5 BD149T"]),
        ("L#80 925 TF", ["L#80 925 TF"]),
        ("Charge: ISBJ E16777-A03-24 178 12", ["ISBJ E16777-A03-24 178 12"]),
        ("M-15251 (lose Kilo-Ware)", ["M-15251"]),
        (
            "LB226056 (Die Losnummer befindet sich auf dem Deckelrand, es sind nur die LB und die 6 Ziffern am Anfang zu beachten)",
            ["LB226056"],
        ),
    ],
)
def test_bare_code_keeps_its_inner_spaces(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Chargen: 103150, 104062 und 104731", ["103150", "104062", "104731"]),
        ("Chargen 12 L160426-1 und 13 L160426-1", ["12 L160426-1", "13 L160426-1"]),
        ("Chargennummern:\n26726870625/8ANORC\n27726870625/9ANORC\n28726870625/10ANORC", ["26726870625/8ANORC", "27726870625/9ANORC", "28726870625/10ANORC"]),
        (
            "Chargennummern:\n2405036115; 2403087418;\n2406298332; 24040126115; 2406266821",
            ["2405036115", "2403087418", "2406298332", "24040126115", "2406266821"],
        ),
    ],
)
def test_lists_are_split_into_single_codes(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Karotte Ingwer: P1250221, P2250221\nMango Curry: P1250311, P2250311", ["P1250221", "P2250221", "P1250311", "P2250311"]),
        ("Yerba Mate Tee gruen: 0234,\nYerba Mate Tee weiß: 0144,\nYerba Mate Tee weiß: 0148", ["0234", "0144", "0148"]),
        (
            "VINNOCENCE Chardonnay alkoholfrei: Losnummer L211285B\nVINNOCENCE Merlot alkoholfrei: Losnummer L211285E",
            ["L211285B", "L211285E"],
        ),
        (
            "Netto: L270326B3\nALDI Süd und ALDI Nord: L220326 B3, L230326 N3, L230326 P3, L230326 B3, L240326 N3",
            ["L270326B3", "L220326 B3", "L230326 N3", "L230326 P3", "L230326 B3", "L240326 N3"],
        ),
        (
            "Bio Wildreis Basmati Reis Mix, 600 Gramm: Chargennummer 21452\nBio Wildreis Basmati Reis Mix, 3 Kilogramm: Chargennummer 21453",
            ["21452", "21453"],
        ),
        (
            "Lot- bzw. Chargennummer von loser Ware: Quendel: P-14527, P-14523; Pizza und Pasta: P-20481, P-20446; "
            "Gutes Bauchgefühl: G-30181, G-30231",
            ["P-14527", "P-14523", "P-20481", "P-20446", "G-30181", "G-30231"],
        ),
        (
            "Kümmel ganz öko, Glas\nL001, L002, L003\nKümmel ganz öko, Nachfüllpackung\nL011, L012\n"
            "Kümmel, Großgebinde\nGebinde seit 13.01.2023 im Verkauf",
            ["L001", "L002", "L003", "L011", "L012"],
        ),
    ],
)
def test_product_names_and_pack_sizes_between_the_codes_are_left_out(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("260904 23.10.2026;\n260907 26.10.2026;", ["260904", "260907"]),
        (
            "Lotnummer: L140626V3 MHD: 13.06.2028\nLotnummer: L150626V3/ L150626N3 MHD: 14.06.2028\n"
            "Lotnummer: L240626 14/ L240626D4/ L240626 E4 MHD: 23.06.2028",
            ["L140626V3", "L150626V3", "L150626N3", "L240626 14", "L240626D4", "L240626 E4"],
        ),
        ("L26019, ab Uhrzeit: 14:30 bis einschließlich 16:16", ["L26019"]),
        # here the date is the batch itself
        ("L: 06.12.2026, Uhrzeit 07:15 bis 10:27", ["06.12.2026"]),
    ],
)
def test_dates_and_times_next_to_a_code_are_not_part_of_it(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Chargen 1326.01 bis 1326.14", ["1326.01 bis 1326.14"]),
        ("Charge am Deckelrand, Code LG262 bis LG292", ["LG262 bis LG292"]),
    ],
)
def test_a_range_of_codes_stays_one_value(text, want):
    assert batch.extract(notice(batch=text)).values == want


@pytest.mark.parametrize("text", ["alle", "alle Chargen", "alle Chargennummern"])
def test_all_batches_affected_is_reported_as_alle(text):
    found = batch.extract(notice(batch=text))

    assert (found.values, found.source, found.rule) == (["alle"], "rule", "batch.all")


def test_notice_saying_the_batch_is_unknown_gives_nothing_and_says_so():
    found = batch.extract(notice(batch="nicht bekannt"))

    assert (found.values, found.source, found.rule) == ([], "none", "batch.stated_unknown")


@pytest.mark.parametrize("text", ["GTIN4063367234613", "GTIN 4305615676876", "Gyros Gewürzmischung, EAN 4260347894083"])
def test_a_product_code_is_not_a_batch(text):
    assert batch.extract(notice(batch=text)).values == []


def test_codes_are_marked_as_found_by_a_rule_with_the_text_as_evidence():
    found = batch.extract(notice(batch="Chargennummer: 090426"))

    assert (found.source, found.rule, found.evidence) == ("rule", "batch.codes", "Chargennummer: 090426")


def test_batch_named_inside_the_best_before_field_is_found():
    # real value of "Haltbarkeit": batch and date were typed into the same field
    found = batch.extract(
        notice(
            best_before="Mindesthaltbarkeitsdatum: 31.08.2028, Charge:103150\n"
            "Mindesthaltbarkeitsdatum: 31.12.2028, Charge:104062\n"
            "Mindesthaltbarkeitsdatum: 31.03.2029, Charge:104731"
        )
    )

    assert found.values == ["103150", "104062", "104731"]
    assert found.rule == "batch.labelled_in_other_field"


def test_without_any_batch_text_nothing_is_found():
    found = batch.extract(notice(product="Deutsches Corned Beef, 160 Gramm"))

    assert (found.values, found.source, found.rule) == ([], "none", None)


def test_colon_timestamps_that_are_part_of_batch_codes_are_kept():
    found = batch.extract(notice(batch="Chargen B1 03:08, B1 03:09 und B1 03:10"))

    assert found.values == ["B1 03:08", "B1 03:09", "B1 03:10"]


def test_bare_batch_code_list_in_marking_is_extracted():
    found = batch.extract(notice(marking="E24A0571; E24A3251; E25A0321; E24A0411"))

    assert (found.values, found.rule) == (["E24A0571", "E24A3251", "E25A0321", "E24A0411"], "batch.labelled_in_other_field")


def test_upc_codes_in_batch_field_are_ignored_and_all_batches_in_marking_wins():
    found = batch.extract(
        notice(
            batch="EAN Codes:\nDose: ByHeart Whole Nutrition Infant Formula, 24 oz can, UPC: 5004496800",
            marking="Das Unternehmen ruft alle ByHeart Whole Nutrition Infant Formula Produkte zurück, unabhängig von Chargennummer und Mindesthaltbarkeitsdaten.",
        )
    )

    assert (found.values, found.rule) == (["alle"], "batch.all")

