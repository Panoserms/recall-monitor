import pytest

from recall.feed import notice_id, parse_feed, version_of


def test_parse_feed_reads_every_notice_of_the_real_feed(feed_bytes):
    items = parse_feed(feed_bytes)

    assert len(items) == 223
    assert len({item.id for item in items}) == 223


def test_parse_feed_keeps_title_link_date_and_the_raw_item(feed_bytes):
    first = parse_feed(feed_bytes)[0]

    assert first.id == "261109_09_NI_Corned_Beef"
    assert first.title == "Deutsches Corned Beef"
    assert first.link == (
        "https://www.lebensmittelwarnung.de/___lebensmittelwarnung.de/Meldungen/2026/"
        "11_November/261109_09_NI_Corned_Beef/261109_09_NI_Corned_Beef.html"
    )
    assert first.pub_date.isoformat() == "2026-11-10T14:35:00+01:00"
    assert first.raw.startswith("<item>") and first.raw.endswith("</item>")
    assert "<b>Chargennummer / Los-Kennzeichnung:</b> Chargennummer: 090426<br/>" in first.raw


@pytest.mark.parametrize(
    "link, want",
    [
        # the usual shape: the folder name is the id
        (
            "https://www.lebensmittelwarnung.de/___lebensmittelwarnung.de/Meldungen/2026/11_November/"
            "261106_04_BW_Pinienkerne/261106_04_BW_Pinienkerne_Meldung.html",
            "261106_04_BW_Pinienkerne",
        ),
        # folder and file name differ: the folder wins
        (
            "https://www.lebensmittelwarnung.de/___lebensmittelwarnung.de/Meldungen/2026/03_Maerz/"
            "260302_01_Sildenafil_in_NEM/260302_01_BW_Sildenafil_in_NEM_Meldung.html",
            "260302_01_Sildenafil_in_NEM",
        ),
        # characters that are awkward in file names are replaced
        (
            "https://www.lebensmittelwarnung.de/___lebensmittelwarnung.de/Meldungen/2026/01_Januar/"
            "260105_02_BY_Nuss,_Kern/260105_02_BY_Nuss,_Kern.html",
            "260105_02_BY_Nuss__Kern",
        ),
    ],
)
def test_notice_id_is_the_folder_name_of_the_link(link, want):
    assert notice_id(link) == want


def test_notice_id_of_an_unknown_link_shape_is_stable_and_file_safe():
    a = notice_id("https://www.lebensmittelwarnung.de/irgendwo.html")
    b = notice_id("https://www.lebensmittelwarnung.de/irgendwo.html")
    other = notice_id("https://www.lebensmittelwarnung.de/anderswo.html")

    assert a == b
    assert a != other
    assert a.startswith("n_") and a.replace("_", "").isalnum()


def test_version_is_the_date_and_time_of_the_last_update(feed_bytes):
    first = parse_feed(feed_bytes)[0]

    assert version_of(first.pub_date) == "20261110T1435"


def test_parse_feed_refuses_a_feed_that_declares_entities():
    bomb = b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel></channel></rss>'

    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_feed(bomb)
