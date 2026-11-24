"""Reading the labelled sections out of a feed item and out of a notice page."""
from recall.feed import parse_feed
from recall.parse import feed_sections, merge_sections, page_attachments, page_sections


def test_feed_item_is_split_into_its_labelled_sections(feed_bytes):
    corned_beef = parse_feed(feed_bytes)[0]

    assert feed_sections(corned_beef.raw) == {
        "image_source": "© Firma Bakenhus",
        "package": "160 Gramm im Glas",
        "batch": "Chargennummer: 090426",
        "contact": (
            "Bakenhus Biofleisch GmbH\nBakenhuser Esch 8\n26197 Großenkneten\n"
            "Mailadresse: Mailadresse der Firma Bakenhus\nWebsite:Website der Firma Bakenhus\nPressemitteilung:"
        ),
        "reason_official": "Fremdkörper",
        "best_before": "Mindesthaltbarkeitsdatum: 01.03.2028, 05.03.2028 und 10.03.2028",
        "manufacturer": "Hersteller und Inverkehrbringer:\nBakenhus Biofleisch GmbH\nBakenhuser Esch 8\n26197 Großenkneten",
        "product": "Deutsches Corned Beef, 160 Gramm",
        "states": "Bremen, Hamburg, Mecklenburg-Vorpommern, Niedersachsen, Schleswig-Holstein",
    }


def test_feed_label_that_is_not_known_is_kept_under_its_own_name():
    item = "<item><description><![CDATA[<b>Neues Feld:</b> etwas<br/><b>Grund der Meldung:</b>   Allergene<br/>]]></description></item>"

    assert feed_sections(item) == {"other:Neues Feld": "etwas", "reason_official": "Allergene"}


def test_page_gives_the_sections_the_feed_does_not_have(page_bytes):
    sections = page_sections(page_bytes)

    assert sections["more_info"] == (
        "Der Rückruf erfolgt vorsorglich, weil in einer Einzeluntersuchung "
        "Shigatoxinbildende Escherichia coli (STEC) nachgewiesen wurden."
    )
    assert sections["recommendation"].startswith("Sollten keine Durcherhitzung erfolgen")
    assert sections["recommendation"].endswith("am Ort des Kaufes zurückgeben.")
    assert sections["consequences"].startswith("STEC-Bakterien können innerhalb weniger Tage")
    assert sections["reported_by"] == "Schleswig-Holstein"
    assert sections["first_published"] == "06.11.2026"
    assert sections["last_updated"] == "09.11.2026"
    assert sections["update_notes"].startswith("09.11.2026: Die Produktbezeichnungen sowie die betroffenen Chargen wurden korrigiert.")
    assert sections["reason_official"] == "Krankheitserreger"


def test_page_lists_and_line_breaks_become_lines(page_bytes):
    sections = page_sections(page_bytes)

    states = sections["states"].split("\n")
    assert len(states) == 15
    assert states[:3] == ["Baden-Württemberg", "Bayern", "Berlin"]
    assert states[-1] == "Thüringen"
    products = sections["product"].split("\n")
    assert len(products) == 14
    assert products[0] == "Rinder-Peperonisalami halal mit Geflügelfleisch 1000 Gramm;"
    assert sections["batch"].split("\n")[:2] == ["260904 23.10.2026;", "260907 26.10.2026;"]
    assert sections["manufacturer"].split("\n") == [
        "Hersteller:",
        "Norderstedter Fleisch- und Wurstwaren Peter Faden GmbH & Co KG,",
        "Kösliner Weg 14,",
        "22850 Norderstedt",
    ]


def test_page_attachments_lists_the_press_release(page_bytes):
    assert page_attachments(page_bytes) == [
        "https://www.lebensmittelwarnung.de/___lebensmittelwarnung.de/Meldungen/2026/11_November/"
        "261106_05_SH_Rindfleischsalamiprodukte/261106_05_SH_Rindfleischsalamiprodukte_Presse2.pdf"
        "?__blob=publicationFile&v=1"
    ]


def test_page_wins_over_feed_and_feed_fills_what_the_page_lacks():
    feed = {"batch": "from feed", "package": "160 Gramm"}
    page = {"batch": "from page", "more_info": "Glassplitter"}

    assert merge_sections(feed, page) == {"batch": "from page", "package": "160 Gramm", "more_info": "Glassplitter"}


# ---- the official text, complete and in page order (shown unchanged on the public site) ----

def test_page_pairs_keep_the_portal_labels_and_order(page_bytes):
    from recall.parse import page_pairs

    pairs = page_pairs(page_bytes)
    labels = [label for label, _ in pairs]
    assert labels[0] == "Produktbezeichnung/ -beschreibung"
    assert "Weitere Informationen" in labels and "Empfehlung" in labels
    assert labels.index("Weitere Informationen") < labels.index("Empfehlung")
    assert all(text for _, text in pairs)


def test_page_pairs_hold_every_section_the_parser_knows(page_bytes):
    from recall.parse import page_pairs, page_sections

    assert len(page_pairs(page_bytes)) >= len(page_sections(page_bytes))


def test_feed_pairs_keep_the_feed_labels(feed_bytes):
    from recall.feed import parse_feed
    from recall.parse import feed_pairs

    item = parse_feed(feed_bytes)[0]
    labels = [label for label, _ in feed_pairs(item.raw)]
    assert "Grund der Meldung" in labels and "Hersteller / Inverkehrbringer" in labels
