"""Receipts: reading the text of a receipt, spelling out abbreviations, matching lines against recalls.

Every receipt text and receipt line in this file is SYNTHETIC: written by hand in the Lidl layout, with
product names from the test records. Real receipts are private (see tests/fixtures/README.md).
"""
from pathlib import Path

import pytest
from test_match import SPINACH, record

from recall import receipt
from recall.models import FieldValue

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "SYNTHETIC_receipt_lidl_layout.txt"
TEXT = FIXTURE.read_text(encoding="utf-8")
ZAUBERFLEKS = record("Kölln Zauberfleks Schoko", brand=["Kölln"], best_before=["2027-04-17", "2027-06"], notice_id="z1",
                     title="Kölln Zauberfleks Schoko - 375 Gramm")
MINCE = record("Rinderhackfleisch", batch=["DE1505453906"], notice_id="m1")
HAM = record("Pfeffer-Schinkenbraten geschnitten", notice_id="h1")
STRAWBERRY = record("Erdbeeren in weißer Schokolade", notice_id="s1")


def sold_at(rec, *shops, first_published="", best_before=None):
    fields = {**rec.fields, "sellers": FieldValue(values=list(shops), source="rule" if shops else "none")}
    if best_before is not None:
        fields["best_before"] = FieldValue(values=best_before, source="rule")
    return rec.model_copy(update={"fields": fields, "extras": {**rec.extras, "first_published": first_published}})


# ------------------------------------------------------------------ parsing

def test_item_lines_with_quantity_weight_discounts_and_deposits():
    parsed = receipt.parse(TEXT)
    assert parsed["layout"] == "lidl"
    products = [i for i in parsed["items"] if i["kind"] == "product"]
    assert [i["description"] for i in products] == [
        "Spinat gehackt", "Rinderhackfleisch", "Zauberfl. Schoko", "Wasser still", "Pfeffer-Schinkenbr.", "Testartikel-0000000"]
    mince, flakes = products[1], products[2]
    assert (mince["weight_kg"], mince["price_per_kg"], mince["line_total"], mince["discount"]) == (0.5, 7.98, 3.99, -0.4)
    assert (flakes["quantity"], flakes["unit_price"], flakes["line_total"], flakes["tax"]) == (2, 2.49, 4.98, "A")
    assert (flakes["discount"], flakes["discount_names"]) == (-0.5, ["Preisvorteil", "Lidl Plus Rabatt"])


def test_deposit_and_deposit_return_are_not_products():
    kinds = {i["description"]: i["kind"] for i in receipt.parse(TEXT)["items"]}
    assert kinds["Pfand 0,25 EM"] == "deposit" and kinds["Pfandrückgabe"] == "deposit_return"
    returned = next(i for i in receipt.parse(TEXT)["items"] if i["kind"] == "deposit_return")
    assert (returned["quantity"], returned["unit_price"], returned["line_total"]) == (-3, 0.25, -0.75)


def test_the_lines_add_up_to_the_printed_total():
    parsed = receipt.parse(TEXT)
    assert (parsed["total"], parsed["items_sum"], parsed["sums_match"], parsed["unparsed"]) == (16.79, 16.79, True, [])


def test_a_changed_price_is_noticed():
    parsed = receipt.parse(TEXT.replace("1,29 A", "1,39 A"))
    assert parsed["sums_match"] is False and parsed["items_sum"] == 16.89


def test_shop_and_date_are_read_and_the_tax_table_is_not_the_shop_netto():
    parsed = receipt.parse(TEXT)
    assert parsed["store"] == "Lidl"  # from "Lidl Plus Rabatt", although "Netto" stands in the tax table
    assert parsed["date"] == "2026-11-07"
    assert receipt.find_store([" MWST%       MWST  +   Netto  =  Brutto"]) == ""
    assert receipt.find_store(["Netto Marken-Discount", "Musterstadt"]) == "Netto Marken-Discount"


@pytest.mark.parametrize("text, want", [
    ("07.11.2026   16:42   T-ID 000000", "2026-11-07"),
    ("Musterstadt 07.11.26 16:42", "2026-11-07"),
    ("MHD 07.11.2026", ""),  # a date without a time is not the purchase date
    ("31.13.2026 10:00", ""),
])
def test_purchase_date_is_the_date_followed_by_a_time(text, want):
    assert receipt.find_date(text) == want


def test_pasted_text_without_indentation_gives_the_same_lines():
    flat = "\n".join(line.strip() for line in TEXT.split("\n"))
    assert receipt.parse(flat)["items"] == receipt.parse(TEXT)["items"]
    assert receipt.parse(TEXT.replace("\n", "\r\n"))["items"] == receipt.parse(TEXT)["items"]


def test_non_food_articles_carry_an_article_number():
    flags = {i["description"]: i["nonfood"] for i in receipt.parse(TEXT)["items"]}
    assert flags["Testartikel-0000000"] is True and flags["Spinat gehackt"] is False


def test_text_in_another_layout_becomes_one_product_per_line():
    parsed = receipt.parse("Spinat gehackt 1,29\nSUMME 1,29\nRinderhackfleisch\n\n12\nBar 5,00")
    assert parsed["layout"] == "unknown" and parsed["sums_match"] is None
    assert [i["description"] for i in parsed["items"]] == ["Spinat gehackt", "Rinderhackfleisch"]


# ---------------------------------------------- text read from a picture

def test_misread_price_columns_are_repaired():
    fix = receipt.repair_ocr
    assert fix("Spinat gehackt                     1,29 8") == "Spinat gehackt  1,29 B"  # B read as 8
    assert fix("Rinderhackfleisch                 3;995") == "Rinderhackfleisch  3,99 B"  # comma as ";", B glued on as a digit
    assert fix("     Lidl Plus Rabatt            -=0,40") == "     Lidl Plus Rabatt  -0,40"
    assert fix("     Preisvorteil      =0:30") == "     Preisvorteil  -0,30"  # minus read as "="
    assert fix("Zauberfl. Schoko      2,49 x   2    4.98: A") == "Zauberfl. Schoko      2,49 x   2  4,98 A"
    assert fix("Salat                0,79 =") == "Salat  0,79 X"  # a letter was there, but which one is lost
    assert fix("  0,500 kg x 7,98   EUR/kg") == "  0,500 kg x 7,98   EUR/kg"  # the weight line is left alone
    assert fix("Musterstraße 1") == "Musterstraße 1"


def test_a_repaired_picture_text_adds_up_again():
    damaged = (TEXT.replace("1,29 A", "1,29 4").replace("-0,40", "=0,40").replace("4,98 A", "4;98 A").replace("1,50 B\nPfand", "1,50 8\nPfand")
               .replace("-0,75 B", "-0,75 3").replace("2,19 A", "2,198"))
    assert receipt.parse(damaged)["sums_match"] is not True
    repaired = receipt.parse(receipt.repair_ocr(damaged))
    assert repaired["sums_match"] is True and repaired["total"] == 16.79
    assert [i["description"] for i in repaired["items"]] == [i["description"] for i in receipt.parse(TEXT)["items"]]


# ------------------------------------------------------- abbreviations

def test_words_are_marked_as_abbreviated_or_cut_off():
    assert receipt.pieces("Vollk.Bröt. m.Jogh.") == [("Vollk", "dot"), ("Bröt", "dot"), ("m", "dot"), ("Jogh", "dot")]
    assert receipt.pieces("SpinatGehackt 1,5%") == [("Spinat", ""), ("Gehackt", ""), ("1,5%", "num")]
    assert receipt.pieces("Erdbeeren Schokolad")[-1] == ("Schokolad", "")  # 19 characters: not cut off
    assert receipt.pieces("Erdbeeren Schokolade")[-1] == ("Schokolade", "end")  # fills the 20 printed characters
    assert receipt.words("Testartikel-0000000") == [("Testartikel", "")]


def test_abbreviations_from_the_lexicon_are_spelt_out():
    assert receipt.phrase("Vollk.Bröt. m.Jogh.") == {"text": "Vollkorn Brötchen mit Joghurt", "open": [], "changed": True}
    assert receipt.phrase("Hähn.-Schnitzel 400g")["text"] == "Hähnchen Schnitzel 400 g"


def test_unknown_abbreviations_stay_and_are_reported_as_open():
    spoken = receipt.phrase("Zauberfl. Schoko")
    assert spoken == {"text": "Zauberfl. Schoko", "open": ["zauberfl"], "changed": False}
    assert receipt.phrase("Dr. Test")["open"] == []  # too short to stand for a longer word


# ------------------------------------------------------------------ matching

def test_a_line_with_the_recalled_name_is_a_possible_match_by_name_only():
    hit = receipt.match_line("Spinat gehackt", SPINACH)
    assert hit and hit["basis"] == "name only" and hit["score"] >= receipt.POSSIBLE
    assert "Charge L5435 DD" in hit["check"] and "EAN 4337185811425" in hit["check"]
    assert "verdict" not in hit  # a receipt never says "affected"


def test_one_word_inside_a_longer_recall_name_does_not_alert():
    assert receipt.match_line("Erdbeeren", STRAWBERRY) is None
    assert receipt.match_line("Erdbeeren", STRAWBERRY, minimum=65.0) is not None  # the product-list threshold would


def test_an_abbreviated_word_stands_for_a_longer_word_of_the_recall():
    hit = receipt.match_line("Zauberfl. Schoko", ZAUBERFLEKS)
    assert hit and hit["matched_as"] == "zauberfleks Schoko"
    assert receipt.match_line("Pfeffer-Schinkenbr.", HAM)["matched_as"] == "Pfeffer Schinkenbraten"  # from the lexicon
    assert receipt.match_line("Zaub. Schoko", ZAUBERFLEKS)["matched_as"] == "zauberfleks Schoko"
    assert receipt.match_line("Zau. Schoko", ZAUBERFLEKS) is None  # three letters are too few


def test_a_brand_printed_on_the_receipt_counts():
    hit = receipt.match_line("Kölln Zauberfleks", ZAUBERFLEKS)
    assert hit and hit["basis"] == "name and brand" and "same brand" in hit["reason"]


def test_the_visitors_correction_replaces_the_rule_phrase():
    assert receipt.match_line("Zbfl. Sch.", ZAUBERFLEKS) is None
    assert receipt.match_line("Zbfl. Sch.", ZAUBERFLEKS, text="Zauberfleks Schoko") is not None


def test_a_notice_that_names_other_shops_only_is_less_likely():
    kaufland = sold_at(SPINACH, "Kaufland")
    assert receipt.narrow(kaufland, "Lidl") == ["the notice names other shops only: Kaufland"]
    assert receipt.narrow(kaufland, "Kaufland") == []
    assert receipt.narrow(kaufland, "") == []  # shop unknown: nothing speaks against it
    assert receipt.narrow(SPINACH, "Lidl") == []  # the notice names no shop: stays possible
    assert receipt.narrow(sold_at(SPINACH, "Aldi Nord", "Aldi Süd"), "Aldi") == []
    assert receipt.match_line("Spinat gehackt", kaufland, store="Lidl")["less_likely"]


def test_dates_can_speak_against_a_match():
    notice = sold_at(SPINACH, first_published="2026-01-08")  # best before 2027-10
    assert receipt.narrow(notice, "", "2026-01-10") == []
    assert receipt.narrow(notice, "", "2026-01-15") == []  # seven days of grace
    assert receipt.narrow(notice, "", "2026-01-16") == ["bought more than 7 days after the recall was published (2026-01-08)"]
    old = sold_at(SPINACH, first_published="2026-01-08", best_before=["2025-03", "2025-01-10..2025-02-01"])
    assert receipt.narrow(old, "", "2025-03-31") == []
    assert receipt.narrow(old, "", "2025-04-01") == ["the recalled packs were past their best-before date (2025-03) when you shopped"]
    assert receipt.narrow(sold_at(SPINACH, first_published="2026-01-08", best_before=["alle"]), "", "2020-01-01") == []


def test_a_whole_receipt_skips_deposits_and_non_food():
    records = [SPINACH, ZAUBERFLEKS, MINCE, HAM, record("Testartikel", notice_id="t1"), record("Pfand", notice_id="p1")]
    found = receipt.match_receipt(receipt.parse(TEXT), records)
    assert sorted((m["line_no"], m["description"], m["notice_id"]) for m in found) == [
        (1, "Spinat gehackt", "n1"), (2, "Rinderhackfleisch", "m1"), (3, "Zauberfl. Schoko", "z1"), (7, "Pfeffer-Schinkenbr.", "h1")]
    assert [m["score"] for m in found] == sorted((m["score"] for m in found), reverse=True)  # strongest first
    assert all(m["less_likely"] == ["bought more than 7 days after the recall was published (2026-01-08)"] for m in found)


def test_less_likely_matches_come_last():
    records = [sold_at(SPINACH, "Kaufland"), MINCE]
    found = receipt.match_receipt(receipt.parse(TEXT), records, purchase_date="")
    assert [m["notice_id"] for m in found] == ["m1", "n1"]


# ----------------------------------------------------------------- synthetic

def test_synthetic_lines_drop_the_brand_shorten_long_words_and_stop_at_20_characters():
    assert receipt.synthetic_line(SPINACH, "K-Classic Spinat gehackt, erntefrisch tiefgefroren") == "Spinat gehackt ernte"
    assert receipt.synthetic_line(ZAUBERFLEKS, "Kölln Zauberfleks Schoko, 375 Gramm") == "Zauberfleks Schoko"
    assert receipt.synthetic_line(HAM, "Pfeffer-Schinkenbraten geschnitten") == "Pfeffer Schin. gesch"


def test_the_evaluation_sample_is_always_the_same():
    names = [f"line {i}" for i in range(500)]
    assert receipt.eval_sample(names) == receipt.eval_sample(names) and len(receipt.eval_sample(names)) == 100
