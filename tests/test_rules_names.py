"""product_name, brand, manufacturer. Every input is a real text from the portal (feed of 2026-11-11)."""
import pytest

from recall.models import NoticeText
from recall.rules import brand, manufacturer, product


def notice(title="", **sections) -> NoticeText:
    return NoticeText(id="t", title=title, link="t", pub_date="2026-11-10T14:35:00+01:00", sections=sections)


# -------------------------------------------------------------- manufacturer

@pytest.mark.parametrize(
    "text, want",
    [
        ("Tema Fine Foods", ["Tema Fine Foods"]),
        ("Firma Demka GmbH", ["Demka GmbH"]),
        ("BLG Kardesler GmbH\nWattstaße 2-10\n68199 Mannheim", ["BLG Kardesler GmbH"]),
        ("Dille & Kamille,\nPostbus 80060,\n3508 TB Utrecht (NL)", ["Dille & Kamille"]),
        ("EDEKA ZENTRALE Stiftung & Co. KG,\nNew-York-Ring 6,\nD-22291 Hamburg", ["EDEKA ZENTRALE Stiftung & Co. KG"]),
        ("Color Brands Europe BV., Weena 00505, Rotterdam South Holland 3013 AL Netherlands", ["Color Brands Europe BV."]),
    ],
)
def test_company_name_is_the_line_before_the_address(text, want):
    assert manufacturer.extract(notice(manufacturer=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        ("Hersteller und Inverkehrbringer:\nBakenhus Biofleisch GmbH\nBakenhuser Esch 8\n26197 Großenkneten", ["Bakenhus Biofleisch GmbH"]),
        (
            "Hersteller: Recker Convenience GmbH, Diepholzer Straße 81, 49453 Wetschen, 49453 Rehden\n"
            "Inverkehrbringer: REWE Markt GmbH, Domstraße 20, 50668 Köln",
            ["Recker Convenience GmbH", "REWE Markt GmbH"],
        ),
        (
            "Hersteller:\nAbido Company for Trade and Industry\nImporteur:\nTema Fine Foods BV\nGroßhändler:\n"
            "Orient Gate GmbH,\nFahrenberg 8,\n22885 Barsbüttel",
            ["Abido Company for Trade and Industry", "Tema Fine Foods BV", "Orient Gate GmbH"],
        ),
        ("Hersteller: Rueter Fruchtsaft\nInverkehrbringer: Rueter Fruchtsaft", ["Rueter Fruchtsaft"]),
        (
            "Hergestellt für: Ersan Cimen,\nSindelfingerstraße 53,\n72070 Tübingen, Germany\nHersteller: Atabey Gida Sanayi ve Tic. Ltd. Sti",
            ["Ersan Cimen", "Atabey Gida Sanayi ve Tic. Ltd. Sti"],
        ),
        (
            "Inverkehrbringer: Consorzio Toscano D’Avitani GmbH,\nVerwaltung/Büro: conneKT 46,\n97318 Kitzingen\n"
            "Hersteller: Salumeria FRANCHI srl,\nVia Archimede,\nIT 58022 Follonica (GR)",
            ["Consorzio Toscano D’Avitani GmbH", "Salumeria FRANCHI srl"],
        ),
        (
            "Deklarierter Hersteller:\nGranizados Maresme S.L.,\nCarrer de la Cierva, 18 (Pol. Ind. Mas Roger),\n"
            "08397 Pineda de Mar / Spanien\nHändler:\nAktuell Vertriebs GmbH // H&B Handelskontor GmbH",
            ["Granizados Maresme S.L.", "Aktuell Vertriebs GmbH", "H&B Handelskontor GmbH"],
        ),
    ],
)
def test_role_labels_start_a_new_company(text, want):
    assert manufacturer.extract(notice(manufacturer=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        (
            "Orient Gate GmbH,\nAm Gewerbepark Nord 3b,\n15749 Mittenwalde,\nOrienta Foods GmbH,\nPorphyrstraße 14,\n06126 Halle (Saale)",
            ["Orient Gate GmbH", "Orienta Foods GmbH"],
        ),
        (
            "Importeur:\nAsia Express Food,\nKilbystraat 1,\n8263 Kampen,\nNiederlande\nInverkehrbringer:\n"
            "Go Asia Deutschland GmbH,\nKantstraße 115,\n10627 Berlin\nOrient Master GmbH,\nKantstraße 101,\n10627 Berlin",
            ["Asia Express Food", "Go Asia Deutschland GmbH", "Orient Master GmbH"],
        ),
        (
            "Kingdom Honey SDN BHD,\nS69-364 Sentul Boulevard, Jalang Matang 3,\nTaman City, 51200 Kuala Lumpur,\nMalaysia\n"
            "Eine verantwortliche Person in der EU ist nicht angegeben.",
            ["Kingdom Honey SDN BHD"],
        ),
    ],
)
def test_a_postcode_line_ends_one_company_and_the_next_line_starts_another(text, want):
    assert manufacturer.extract(notice(manufacturer=text)).values == want


@pytest.mark.parametrize(
    "text, want",
    [
        (
            "Eine verantwortliche Person in der EU ist nicht angegeben.\nHersteller laut Kennzeichnung: Atci Gida San. ve Tic. Ltd. Şti.,\n"
            "Mimar Hayrettin Mahallesi,\nTatlikuyu Sk. No: 6 Fatih/Istanbul",
            ["Atci Gida San. ve Tic. Ltd. Şti."],
        ),
        (
            "Hersteller: Etumax Corporation, Damaskus, Syrien Arabische Republik, www.etumax-corporation.com\n"
            "Eine verantwortliche Person in der EU ist nicht angegeben.",
            ["Etumax Corporation"],
        ),
        ("Hersteller: Türkei, Code-Nr. TR-34-K-226898", []),
        ("Hersteller: www.goldq7bitkisel.com, Türkei.\nEine verantwortliche Person in der EU ist nicht angegeben.", []),
    ],
)
def test_sentences_countries_and_web_addresses_are_not_company_names(text, want):
    assert manufacturer.extract(notice(manufacturer=text)).values == want


def test_manufacturer_is_marked_as_found_by_a_rule():
    found = manufacturer.extract(notice(manufacturer="BLG Kardesler GmbH\nWattstaße 2-10\n68199 Mannheim"))

    assert (found.source, found.rule) == ("rule", "manufacturer.name_before_address")


# --------------------------------------------------------------------- brand

@pytest.mark.parametrize(
    "product_text, want",
    [
        ("Sesampaste (Tahina), Marke: Chtoura Garden, 12x800 Gramm", ["Chtoura Garden"]),
        ("Sumach gemahlen, 200 Gramm der Marke Ikleel Algabal (ME TRADE INTL)", ["Ikleel Algabal"]),
        ("Paprika-Gewürzzubereitung Pul Biber der Marke Suntat", ["Suntat"]),
        ('Bratolivenöl aus Kreta, Marke "GHORBAN", 750 Milliliter', ["GHORBAN"]),
        ('8 Kräuter, tiefgefroren, 75 Gramm der Marke "All Seasons"', ["All Seasons"]),
        ("Kalmar Fangarme – Marke Più Amore a Tavola", ["Più Amore a Tavola"]),
        ("Palmzucker, Marke Royal Orient, 454 Gramm\nPalmzucker, Marke Royal Orient, 500 Gramm", ["Royal Orient"]),
        (
            "TNT Synapsensause Wild Berry, 440 Gramm\nMarke: True Nutrition Technology\n"
            "Produktart: Koffeinhaltiges Pulver zur Herstellung eines Getränks",
            ["True Nutrition Technology"],
        ),
        ('Maissnack der Marke "BOY BAWANG"\nBOY BAWANG CORNICK LECHON MANOK FLAVOR', ["BOY BAWANG"]),
        # plural: two brands joined by "und"
        ("Muskatnuss gemahlen, 75 Gramm der Marken Sahra und Hira", ["Sahra", "Hira"]),
        ("Nelken ganz (Karanfil Bütün) der Marken Sahra und Hira, PET Behälter 110 Gramm, PET Behälter 50 Gramm, Glas 50 Gramm", ["Sahra", "Hira"]),
    ],
)
def test_brand_named_after_the_word_marke(product_text, want):
    found = brand.extract(notice(product=product_text))

    assert (found.values, found.source, found.rule) == (want, "rule", "brand.after_marke")


@pytest.mark.parametrize(
    "product_text, want",
    [
        ("ja! Schweine Mini Schnitzel, 400 Gramm", ["ja!"]),
        ("K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm", ["K-Classic"]),
        ("EDEKA Herzstücke Chocolate Caramel, 500 Milliliter", ["EDEKA Herzstücke"]),
        ("Alnatura Kichererbsen im Glas, 330 Gramm", ["Alnatura"]),
    ],
)
def test_known_brand_at_the_start_of_the_product_name(product_text, want):
    found = brand.extract(notice(title=product_text, product=product_text))

    assert (found.values, found.source, found.rule) == (want, "rule", "brand.lexicon")


@pytest.mark.parametrize(
    "title, company, want",
    [
        ("Wurzener Weiße Bohnen, 500 Gramm und 10 Kilogramm", "Wurzener Nahrungsmittel GmbH,\nAm Mühlgraben 1,\n04808 Wurzen", ["Wurzener"]),
        ("Rueter verschiedene Saefte", "Hersteller: Rueter Fruchtsaft\nInverkehrbringer: Rueter Fruchtsaft", ["Rueter"]),
    ],
)
def test_product_name_that_starts_like_the_company_name_gives_the_brand(title, company, want):
    found = brand.extract(notice(title=title, product=title, manufacturer=company))

    assert (found.values, found.source, found.rule) == (want, "rule", "brand.company_name_in_product")


def test_a_shop_name_containing_marken_is_not_a_brand_label():
    found = brand.extract(notice(product="Netto Marken-Discount Jack's Ice-Cream Choco Crumble, 500 Milliliter"))

    assert found.rule != "brand.after_marke"


def test_no_brand_in_the_notice_gives_nothing():
    found = brand.extract(
        notice(
            title="Deutsches Corned Beef",
            product="Deutsches Corned Beef, 160 Gramm",
            manufacturer="Hersteller und Inverkehrbringer:\nBakenhus Biofleisch GmbH\nBakenhuser Esch 8\n26197 Großenkneten",
        )
    )

    assert (found.values, found.source) == ([], "none")


# ------------------------------------------------------------------- product

@pytest.mark.parametrize(
    "title, product_text, want",
    [
        ("ja! Schweine Mini Schnitzel, 400 Gramm", "ja! Schweine Mini Schnitzel, 400 Gramm", ["ja! Schweine Mini Schnitzel"]),
        (
            "K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm",
            "K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm",
            ["K-Classic Spinat gehackt, erntefrisch tiefgefroren"],
        ),
        ("Paprika-Gewürzzubereitung 100 Gramm", "Paprika-Gewürzzubereitung Pul Biber der Marke Suntat", ["Paprika-Gewürzzubereitung Pul Biber"]),
        ("Apfel-Granatapfel-Fruchtplatte - 300 Gramm", "Lavashak Anar - Apfel-Granatapfel-Fruchtplatte - 300 Gramm", ["Lavashak Anar - Apfel-Granatapfel-Fruchtplatte"]),
        (
            "TNT Synapsensause Wild Berry, 440 Gramm",
            "TNT Synapsensause Wild Berry, 440 Gramm\nMarke: True Nutrition Technology\nProduktart: Koffeinhaltiges Pulver zur Herstellung eines Getränks",
            ["TNT Synapsensause Wild Berry"],
        ),
    ],
)
def test_pack_size_and_brand_note_are_removed_from_the_name(title, product_text, want):
    found = product.extract(notice(title=title, product=product_text))

    assert (found.values, found.source, found.rule) == (want, "rule", "product.name")


@pytest.mark.parametrize(
    "title, product_text, want",
    [
        ("Gefrorene Austern, 226 Gramm", "Gefrorene Austern, 226 Gramm, Surasang Frozen oysters (I:Q:F:) Huitre Congelee", ["Gefrorene Austern"]),
        ("Yerba Mate Tee gruen und weiß, 250 Gramm", "Yerba Mate Tee gruen und weiß, Kharta Khadra, 250 Gramm", ["Yerba Mate Tee gruen und weiß"]),
        ("Palmzucker, 500 Gramm", "Palmzucker, Lotus, 500 Gramm", ["Palmzucker"]),
        (
            "Nelken ganz, 50 Gramm und 110 Gramm",
            "Nelken ganz (Karanfil Bütün) der Marken Sahra und Hira, PET Behälter 110 Gramm, PET Behälter 50 Gramm, Glas 50 Gramm",
            ["Nelken ganz"],
        ),
    ],
)
def test_additions_that_the_title_leaves_out_are_dropped(title, product_text, want):
    assert product.extract(notice(title=title, product=product_text)).values == want


@pytest.mark.parametrize(
    "title, product_text, want",
    [
        (
            "Gewürzmischungen von Dille & Kamille",
            "00024629 - GUACAMOLE-MIX 55 Gramm BIO\n00024646 - EINTOPFGEWÜRZ 45 Gramm BIO\n00024650 - FISCHGEWÜRZ 30 Gramm BIO\n"
            "00024634 - KRÄUTERMISCHUNG ITALIENISCHER ART 30 Gramm BIO",
            ["GUACAMOLE-MIX BIO", "EINTOPFGEWÜRZ BIO", "FISCHGEWÜRZ BIO", "KRÄUTERMISCHUNG ITALIENISCHER ART BIO"],
        ),
        (
            "Rueter verschiedene Saefte",
            "Rueter Apfel-Birnen-Saft, Rueter Apfelpunsch alkoholfrei, Rueter Apfel-Quitten-Saft, Rueter Apfelsaft klar, "
            "Rueter Apfelsaft Naturtrueb, Rueter Birnensaft",
            ["Rueter Apfel-Birnen-Saft", "Rueter Apfelpunsch alkoholfrei", "Rueter Apfel-Quitten-Saft", "Rueter Apfelsaft klar", "Rueter Apfelsaft Naturtrueb", "Rueter Birnensaft"],
        ),
        (
            "Verschiedene Sorten MINI BRIE, 150 Gramm",
            "Verschiedene Sorten MINI BRIE, 150 Gramm\nBrie Mini Nuss 150 Gramm, Marke: Eberle Spezialitäten\n"
            "Brie Mini Schnittlauch 150 Gramm, Marke: Eberle Spezialitäten\nBrie Mini Trüffel 150 Gramm, Marke: Eberle Spezialitäten\n"
            "Brie Mini Chili 150 Gramm, Marke: Eberle Spezialitäten",
            ["Brie Mini Nuss", "Brie Mini Schnittlauch", "Brie Mini Trüffel", "Brie Mini Chili"],
        ),
        ('Maissnack der Marke "BOY BAWANG"', 'Maissnack der Marke "BOY BAWANG"\nBOY BAWANG CORNICK LECHON MANOK FLAVOR', ["Maissnack", "BOY BAWANG CORNICK LECHON MANOK FLAVOR"]),
        (
            "Palmzucker, verschiedene Verpackungseinheiten, 454 Gramm, 500 Gramm",
            "Palmzucker, Marke Royal Orient, 454 Gramm\nPalmzucker, Marke Royal Orient, 500 Gramm",
            ["Palmzucker"],
        ),
        ("Wurzener Weiße Bohnen, 500 Gramm und 10 Kilogramm", "Wurzener Weiße Bohnen, 500 Gramm und Wurzener Weiße Bohnen, 10 Kilogramm", ["Wurzener Weiße Bohnen"]),
    ],
)
def test_several_products_in_one_notice_become_a_list(title, product_text, want):
    found = product.extract(notice(title=title, product=product_text))

    assert found.values == want
    assert found.source == "rule"


def test_the_salami_notice_lists_each_product_once(page_bytes):
    from recall.parse import page_sections

    found = product.extract(notice(title="Diverse Rindfleischsalamiprodukte", **page_sections(page_bytes)))

    assert found.values == [
        "Rinder-Peperonisalami halal mit Geflügelfleisch",
        "Rindfleischsalami halal Kaliber 60 mit Geflügelfleisch",
        "Rindfleischsalami halal Kaliber 80 mit Geflügelfleisch",
        "Rindfleischsalami rein Rind Kaliber 80",
        "Rindfleischsalami rein Rind halal Kaliber 80 Vakuum",
        "Rindfleischsalami Kappen halal mit Geflügelfleisch",
        "Rindfleischsalami-Scheiben, halal mit Geflügelfleisch, ungleiche Scheiben",
        "Pizza Rindfleischsalami halal Kaliber 60 mit Geflügelfleisch",
    ]
    assert found.rule == "product.list"


@pytest.mark.parametrize(
    "title, product_text, want, rule",
    [
        (
            "Crab Blue Swimming Cut U/10 Casabor",
            "Crab Blue Swimming Cut U/10 Casabor, blaue Schwimmkrabben, frozen blue swimming crab",
            ["Crab Blue Swimming Cut U/10 Casabor"],
            "product.title",
        ),
        ("Kalmar Fangarme", "Kalmar Fangarme – Marke Più Amore a Tavola", ["Kalmar Fangarme"], "product.title"),
        ("Wasabi rice crackers, 125 Gramm", "Wasabi rice crackers", ["Wasabi rice crackers"], "product.field"),
        ("Night Longer, 144 Gramm", "Night Longer Nahrungsergänzungsmittel", ["Night Longer Nahrungsergänzungsmittel"], "product.field"),
    ],
)
def test_name_that_the_portal_already_gives_as_such_counts_as_structured(title, product_text, want, rule):
    found = product.extract(notice(title=title, product=product_text))

    assert (found.values, found.source, found.rule) == (want, "structured", rule)


def test_running_text_in_the_product_field_is_not_a_product_name():
    found = product.extract(
        notice(
            title="BEBA- und ALFAMINO-Produkte (Update zu Kaufland)",
            product="Update vom 14. Oktober 2026: Die Kaufland Dienstleistung GmbH & Co. KG wiederholt den bereits Anfang des Jahres "
            "durchgeführten Rückruf bestimmter BEBA-Produkte, da betroffene Chargen in einzelnen Kaufland-Filialen nicht vollständig "
            "aus dem Verkauf genommen wurden.\nProduktabbildungen des Herstellers",
        )
    )

    assert found.values == ["BEBA- und ALFAMINO-Produkte"]
    assert found.rule == "product.from_title"


@pytest.mark.parametrize(
    "title, product_text, want",
    [
        (
            "Mönchshof Natur Radler Blutorange, 0,5 Liter",
            "Mönchshof Natur Radler Blutorange, 0,5 Liter",
            ["Mönchshof Natur Radler Blutorange"],
        ),
        (
            "Mineralwässer „Raffelberger Medium”, 0,75 Liter und „Raffelberger Klassik”, 0,7 Liter",
            "Mineralwässer „Raffelberger Medium”, 0,75 Liter und „Raffelberger Klassik”, 0,7 Liter",
            ["Mineralwässer „Raffelberger Medium” und „Raffelberger Klassik”"],
        ),
        (
            "Schokoladenstreusel 400 Gramm",
            '„Belbake Schokoladenstreusel (mindestens 32% Kakao), 400 Gramm"',
            ["Belbake Schokoladenstreusel (mindestens 32% Kakao)"],
        ),
        (
            # the compound size goes; then the title's own short form wins, as for "Palmzucker, Lotus, 500 Gramm"
            # and "Yerba Mate Tee gruen und weiß, Kharta Khadra, 250 Gramm" (the name before the brand)
            "Cholin, 50 Gramm/60 Kapseln",
            "Cholin 600 mg, ZeinPharma, 50 Gramm/60 Kapseln",
            ["Cholin"],
        ),
        (
            "Bio Brennnessel Bünting Tee",
            "Bio Brennnessel, Bünting Tee, 20 Aufgussbeutel á 2 Gramm",
            ["Bio Brennnessel, Bünting Tee"],
        ),
        (
            '„Treets Salted Peanuts Vegan 200 Gramm" und „K-Classic Choc it bunte Erdnüsse 300 Gramm"',
            '„Treets Salted Peanuts Vegan 200 Gramm" und „K-Classic Choc it bunte Erdnüsse 300 Gramm"',
            ["Treets Salted Peanuts Vegan", "K-Classic Choc it bunte Erdnüsse"],
        ),
    ],
)
def test_decimal_sizes_compound_sizes_and_outer_quotes_are_cleaned(title, product_text, want):
    assert product.extract(notice(title=title, product=product_text)).values == want


def test_compound_sizes_are_removed_from_a_name():
    assert product.clean_name("Cholin 600 mg, ZeinPharma, 50 Gramm/60 Kapseln") == "Cholin, ZeinPharma"
    assert product.clean_name("Bio Brennnessel, Bünting Tee, 20 Aufgussbeutel á 2 Gramm") == "Bio Brennnessel, Bünting Tee"


def test_lowercase_brand_after_der_marke_and_marke_in_marking():
    found_lower = brand.extract(notice(title="Sonnenblumenkerne der Marke göral", product="Sonnenblumenkerne"))
    assert (found_lower.values, found_lower.rule) == (["göral"], "brand.after_marke")

    found_marking = brand.extract(notice(title="Brotaufstriche", product="Brotaufstriche", marking="Marke: Yörem"))
    assert (found_marking.values, found_marking.rule) == (["Yörem"], "brand.after_marke")

