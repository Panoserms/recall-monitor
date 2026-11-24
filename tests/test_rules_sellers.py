"""sellers. Every input is a real value of the page field "Vertrieb über" or a real sentence of a notice."""
import pytest

from recall.models import NoticeText
from recall.rules import sellers


def notice(**sections) -> NoticeText:
    return NoticeText(id="t", title="t", link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


@pytest.mark.parametrize(
    "text, want",
    [
        ("Aldi Nord", ["Aldi Nord"]),
        ("ALDI Nord und ALDI SÜD", ["Aldi Nord", "Aldi Süd"]),
        ("EDEKA Filialen und Marktkauf Filialen", ["Edeka", "Marktkauf"]),
        ("tegut-Filialen", ["tegut"]),
        ("Go Asia Filialen", ["Go Asia"]),
        ("REWE Group,\nPenny-Filialen", ["Rewe", "Penny"]),
        ("Netto Marken-Discount,\nALDI Süd und ALDI Nord", ["Netto Marken-Discount", "Aldi Süd", "Aldi Nord"]),
        ("Filialen von Netto Marken-Discount", ["Netto Marken-Discount"]),
        ("Lidl Deutschland bundesweit", ["Lidl"]),
        ("Globus Verbrauchermärkte bundesweit", ["Globus"]),
        ("Action-Filialen", ["Action"]),
        ("Alnatura Super Natur Märkte und weitere Handelsketten", ["Alnatura"]),
        ("Treets Salted Peanuts Vegan 200 Gramm: Edeka, Globus\nK-Classic Choc it bunte Erdnüsse 300 Gramm: Kaufland", ["Edeka", "Globus", "Kaufland"]),
        ("Online-Vertrieb: Amazon.de, eigener Online-Shop (timber-taste.de), Etsy, ebay, TikTok Shop", ["Amazon", "Etsy", "ebay", "TikTok Shop"]),
        # shop names inside sentences
        ("Das Produkt wurde online über Amazon vertrieben.", ["Amazon"]),
        ("Der Artikel wurde über Filialen der Handelsketten Kaufland, famila und Combi verkauft.", ["Kaufland", "famila", "Combi"]),
        ("Die Ware ist bei Denns BioMarkt und in ausgewählten Naturkostfachmärkten erhältlich.", ["Denns BioMarkt"]),
        ("Die Produkte wurden in der Zeit von Januar 2026 bis Juli 2026 in TK Maxx Stores verkauft.", ["TK Maxx"]),
        ("Verkauf über TK Maxx Store zwischen Februar und Juni 2026", ["TK Maxx"]),
    ],
)
def test_known_shops_are_found_and_spelt_one_way(text, want):
    assert sellers.extract(notice(sold_via=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Kaufland Dienstleistung GmbH & Co. KG", ["Kaufland"]),
        ("Lidl Stiftung & Co. KG", ["Lidl"]),
        ("NORMA Lebensmittelfilialbetrieb Stiftung & Co. KG", ["Norma"]),
        ("EDEKA AG Hamburg", ["Edeka"]),
        (
            "Dirk Rossmann GmbH\nBitterfelder Str. 1\n06188 Landsberg\nund\nGlobus Logistik GmbH & Co. KG\nGlobusallee\n55411 Bingen",
            ["Rossmann", "Globus"],
        ),
    ],
)
def test_company_name_of_a_known_shop_gives_the_shop(text, want):
    assert sellers.extract(notice(sold_via=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Hohensteiner Hofkäserei", ["Hohensteiner Hofkäserei"]),
        (
            "Edeka (Einzelhandel und Großhandel), Globus, Hamberger Großmarkt, Kaufland, REWE, HIT-Markt, Transgourmet",
            ["Edeka", "Globus", "Hamberger Großmarkt", "Kaufland", "Rewe", "HIT", "Transgourmet"],
        ),
        ("Al Rabie Lebensmittelgeschäft\nEisenbahnstraße 57\n04315 Leipzig", ["Al Rabie Lebensmittelgeschäft"]),
        ("The Link, Gottlob-Grotz-Staße 1, 74321 Biegtigheim-Bissingen", ["The Link"]),
        ("TJX Deutschland Ltd. & Co. KG, Peter-Mueller-Straße 18, 40468 Düsseldorf.", ["TJX Deutschland Ltd. & Co. KG"]),
        ("Vertrieb Deutschland:\nHeiderbeck GmbH,\nGewerbering 4,\n82140 Olching", ["Heiderbeck GmbH"]),
        ("Telesto Food & Trading,\nUlzburgerstraße 676,\n22844 Norderstedt\nDie Vertriebswege sind nicht bekannt.", ["Telesto Food & Trading"]),
    ],
)
def test_shops_that_are_not_in_the_lexicon_are_kept_as_written(text, want):
    assert sellers.extract(notice(sold_via=text)).values == want


@pytest.mark.parametrize(
    "text",
    [
        "verschiedene Einzelhändler",
        "Diverse Einzelhändler",
        "diverse Lebensmitteleinzelhändler",
        "Bundesweit",
        "rein lokaler Vertrieb",
        "siehe Presseinformation",
        "eigenen Hofladen- vor Ort",
        "Asiatische und Afrikanische Supermärkte",
        "den Einzelhandel sowie über die firmeneigene Homepage",
        "Lebensmitteleinzelhandel, Naturkost- und Feinkosthandel, Metzgereien, Hofläden, Gastronomie, eigene Verkaufsstelle sowie online",
        "Die Produkte wurden ausschließlich über den Online-Handel vertrieben.",
        "Der Artikel wurde im Landkreis Miesbach über den Hofladen verkauft.",
    ],
)
def test_a_sales_channel_without_a_shop_name_gives_no_seller(text, nlp):
    found = sellers.extract(notice(sold_via=text), nlp)

    assert (found.values, found.source, found.rule) == ([], "none", "sellers.no_named_seller")


def test_unknown_sales_channels_are_reported_as_unknown():
    found = sellers.extract(
        notice(sold_via="Die Vertriebswege sind nicht bekannt. Es wird jedoch von einem bundesweiten Vertrieb ausgegangen.")
    )

    assert (found.values, found.source, found.rule) == ([], "none", "sellers.stated_unknown")


def test_sellers_are_marked_as_found_by_a_rule_with_the_text_as_evidence():
    found = sellers.extract(notice(sold_via="EDEKA und Marktkauf"))

    assert (found.source, found.rule, found.evidence) == ("rule", "sellers.lexicon", "EDEKA und Marktkauf")


# ---- spaCy patterns: shop names the lexicon does not know, inside sentences

def test_shop_after_ueber_or_bei_is_found_through_the_sentence_structure(nlp):
    assert sellers.shops_by_dependency(nlp("Das Produkt wurde online über Amazon vertrieben.")) == ["Amazon"]
    assert sellers.shops_by_dependency(nlp("Der Artikel wurde bei Aldi Nord zum Verkauf angeboten.")) == ["Aldi Nord"]


def test_a_common_noun_after_ueber_is_not_a_shop(nlp):
    assert sellers.shops_by_dependency(nlp("Die Produkte wurden ausschließlich über den Online-Handel vertrieben.")) == []
    assert sellers.shops_by_dependency(nlp("Der Artikel wurde im Landkreis Miesbach über den Hofladen verkauft.")) == []


def test_company_named_after_the_word_firma_is_a_seller(nlp):
    text = (
        "Das Produkt Wild Stracke wurde im Zeitraum 02.10.2026 bis 09.10.2026 im Hofladen der Firma Wilder Wand in Hollenbach, "
        "bei der Firma Obst und Gemüse Dietrich, Stätte 6 in 99974 Mühlhausen und am 04.10.2026 in Rockensußra zum Kartoffelfest "
        "in einem Verkaufswagen verkauft."
    )

    found = sellers.extract(notice(sold_via=text), nlp)

    assert found.values == ["Wilder Wand", "Obst und Gemüse Dietrich"]
    assert found.rule == "sellers.sentence_pattern"


def test_company_whose_branches_sold_the_product_is_a_seller(nlp):
    text = (
        "Das Produkt wurde ausschließlich im Zeitraum vom 09.10.2026 bis einschließlich 14.10.2026 in Thüringen in den Filialen der "
        "Fleisch- und Wurstwaren Schmalkalden GmbH Thüringen verkauft."
    )

    assert sellers.extract(notice(sold_via=text), nlp).values == ["Fleisch- und Wurstwaren Schmalkalden GmbH Thüringen"]


# ---- notices without the field "Vertrieb über"

def test_shop_named_in_the_advice_is_used_when_there_is_no_sales_field():
    advice = (
        "Sollten Kundinnen und Kunden an einer entsprechenden Allergie oder Unverträglichkeit leiden, bitten wir sie dringend, vom Verzehr "
        "abzusehen und das Produkt ungeöffnet oder bereits angebrochen in die dm-Märkte zurückzubringen."
    )

    found = sellers.extract(notice(recommendation=advice))

    assert (found.values, found.source) == (["dm"], "rule")


def test_shop_in_quotes_before_filialen_is_found():
    found = sellers.extract(notice(recommendation="Das Produkt kann in allen „Go Asia“-Filialen zurückgegeben werden. Der Kaufpreis wird erstattet"))

    assert found.values == ["Go Asia"]


def test_advice_that_names_no_shop_gives_nothing():
    found = sellers.extract(notice(recommendation="Geben Sie das Produkt an der Verkaufsstelle zurück."))

    assert (found.values, found.source, found.rule) == ([], "none", None)
