"""ean. Every input is a real value of a notice page (pages saved 2026-11-11)."""
import pytest

from recall.models import NoticeText
from recall.rules import ean


def notice(**sections) -> NoticeText:
    return NoticeText(id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


@pytest.mark.parametrize(
    "text, want",
    [
        ("EAN: 4260677731805\nCharge und Mindesthaltbarkeitsdatum finden Sie auf dem Boden der Dose.", ["4260677731805"]),
        ("Artikelnummer: 1546, EAN: 4012346154602", ["4012346154602"]),
        ("EAN-CODE:8006363076203", ["8006363076203"]),
        ("EAN: 8 683672 505190 // Herstellerregistriernummer", ["8683672505190"]),
        ("EAN-Code 7610046002017", ["7610046002017"]),
        ("GTIN-Nummer: 4006950042790 //", ["4006950042790"]),
        ("GTIN 4 068134 162755", ["4068134162755"]),
        ("Artikelnummer: 690280 / EAN: 4006040169871", ["4006040169871"]),
        ("Barcode: 6 923807 807198", ["6923807807198"]),
        ("Barcode-Nummer: 8 719497 398195", ["8719497398195"]),
        ("Strichcode: 4 027900 615116", ["4027900615116"]),
        ("EAN-Codes: 5060193938806 / 5060193935560", ["5060193938806", "5060193935560"]),
    ],
)
def test_labelled_barcodes_are_read_without_spaces(text, want):
    assert ean.extract(notice(marking=text)).values == want


def test_a_number_with_a_wrong_check_digit_is_not_a_barcode():
    # last digit changed from 5 to 6
    assert ean.extract(notice(marking="EAN: 4260677731806")).values == []


def test_the_barcode_may_sit_in_the_batch_field():
    found = ean.extract(notice(batch="GTIN 4305615676876"))
    assert found.values == ["4305615676876"] and found.rule == "ean.labelled"


def test_a_remark_about_the_barcode_is_not_a_barcode():
    assert ean.extract(notice(update_notes="26.10.26.: Die EAN wurde aktualisiert.")).values == []


def test_valid_check_digit():
    assert ean.valid("4012346154602")
    assert not ean.valid("4012346154603")
    assert not ean.valid("12345")
