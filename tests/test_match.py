"""Stage 5: matching your products against recalls, and checking batch / best-before / EAN.

The recall records hold the values `recall extract` found in real notices (2026-11-12).
"""
import pytest

from recall import match
from recall.models import FieldValue, Record


def record(product, brand=(), batch=(), best_before=(), ean=(), manufacturer=(), title=None, notice_id="n1") -> Record:
    def fv(values):
        return FieldValue(values=list(values), source="rule" if values else "none")

    return Record(
        id=notice_id,
        title=title or product,
        link=f"https://www.lebensmittelwarnung.de/{notice_id}.html",
        pub_date="2026-01-08T16:45:00+01:00",
        fields={
            "product_name": fv([product]), "brand": fv(brand), "manufacturer": fv(manufacturer), "batch": fv(batch),
            "best_before": fv(best_before), "reason_category": fv(["foreign_object"]), "reason_text": fv([]),
            "sellers": fv([]), "states": fv([]), "date": fv(["2026-01-08"]),
        },
        extras={"ean": list(ean), "what_to_do": "Das Produkt kann in allen Kaufland Filialen zurückgegeben werden."},
    )


# notice 260108_04_BW_Spinat
SPINACH = record(
    "K-Classic Spinat gehackt, erntefrisch tiefgefroren", brand=["K-Classic"], batch=["L5435 DD"],
    best_before=["2027-10"], ean=["4337185811425"], manufacturer=["FLANDERS BEST NV"],
    title="K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm",
)


def mine(name, brand="", **extra) -> match.MyProduct:
    return match.MyProduct(row=1, name=name, brand=brand, **extra)


# ------------------------------------------------------------------ names

def test_same_product_same_brand_is_a_match():
    found = match.match_product(mine("Spinat gehackt", "K Classic"), SPINACH)
    assert found and found.level == "match"
    assert "K-Classic" in found.reason


def test_same_product_other_brand_is_not_a_match():
    assert match.match_product(mine("Blattspinat", "Iglo"), SPINACH) is None


def test_without_a_brand_the_name_alone_can_match():
    found = match.match_product(mine("Spinat"), SPINACH)
    assert found and found.level in {"match", "possible"}


def test_same_brand_other_product_is_not_a_match():
    assert match.match_product(mine("Haferflocken", "K-Classic"), SPINACH) is None


def test_a_different_meat_with_the_same_head_is_not_a_match():
    minced_pork = record("Schweinehackfleisch", notice_id="n2")
    assert match.match_product(mine("Rinderhackfleisch"), minced_pork) is None


def test_compound_and_phrase_for_the_same_thing_match():
    minced_beef = record("Rinderhackfleisch", notice_id="n3")  # notice 260921_09_ST_Rinderhackfleisch
    assert match.match_product(mine("Hackfleisch vom Rind"), minced_beef)


def test_lexicalised_compounds_with_a_shared_head_do_not_match():
    blueberries = record("EDEKA Bio Wildheidelbeeren tiefgefroren", brand=["EDEKA Bio"], notice_id="n4")
    assert match.match_product(mine("Himbeeren"), blueberries) is None


def test_the_ean_decides_when_both_sides_have_one():
    found = match.match_product(mine("Gemüse", "irgendwas", ean="4337185811425"), SPINACH)
    assert found and found.score == 100 and "EAN" in found.reason


# ------------------------------------------------------------ identifiers

def test_without_pack_details_the_alert_says_what_to_check():
    verdict = match.check_identifiers(mine("Spinat"), SPINACH)
    assert verdict["verdict"] == "check"
    assert "L5435 DD" in verdict["check"] and "10/2027" in verdict["check"]


@pytest.mark.parametrize("best_before, want", [("31.10.2027", "affected"), ("2027-10-02", "affected"), ("05.11.2027", "not_affected")])
def test_best_before_inside_the_recalled_month(best_before, want):
    assert match.check_identifiers(mine("Spinat", best_before=best_before), SPINACH)["verdict"] == want


@pytest.mark.parametrize("batch, want", [("L5435 DD", "affected"), ("l5435dd", "affected"), ("L5436 DD", "not_affected")])
def test_batch_compared_without_spaces_and_case(batch, want):
    assert match.check_identifiers(mine("Spinat", batch=batch), SPINACH)["verdict"] == want


def test_every_batch_recalled():
    coconut = record("Annam – Trockene Kokosnuss Halbschnitt", batch=["alle"], best_before=["alle"])
    assert match.check_identifiers(mine("Kokosnuss", batch="X1", best_before="01.01.2030"), coconut)["verdict"] == "affected"


@pytest.mark.parametrize("best_before, want", [("15.06.2027", "affected"), ("03.07.2027", "not_affected")])
def test_best_before_inside_a_recalled_range(best_before, want):
    # notice 261105_02_BY_Pinienkerne: "zwischen 31.05.2027 bis einschließlich 02.07.2027"
    pine_nuts = record("Alnatura Pinienkerne", best_before=["2027-05-31..2027-07-02"])
    assert match.check_identifiers(mine("Pinienkerne", best_before=best_before), pine_nuts)["verdict"] == want


def test_conflicting_answers_mean_check():
    verdict = match.check_identifiers(mine("Spinat", batch="L5435 DD", best_before="05.11.2027"), SPINACH)
    assert verdict["verdict"] == "check"


# ------------------------------------------------------------ product list

def test_product_list_reads_optional_columns(tmp_path):
    path = tmp_path / "my_products.csv"
    path.write_text("name,brand,best_before\nSpinat gehackt,K-Classic,31.10.2027\nHaferflocken,,\n", encoding="utf-8")
    products = match.load_products(path)
    assert [(p.row, p.name, p.brand, p.best_before) for p in products] == [
        (1, "Spinat gehackt", "K-Classic", "31.10.2027"),
        (2, "Haferflocken", "", ""),
    ]


def test_product_list_with_semicolons_from_a_german_spreadsheet(tmp_path):
    path = tmp_path / "my_products.csv"
    path.write_text("name;brand\nSpinat gehackt;K-Classic\n", encoding="utf-8-sig")
    assert match.load_products(path)[0].brand == "K-Classic"
