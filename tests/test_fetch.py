"""Stage 1: polite download, unchanged raw files, SQLite, no re-downloads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from recall.fetch import NotAllowed, PoliteClient, fetch_feed, fetch_pages

from conftest import cut_feed

FEED_URL = "https://www.lebensmittelwarnung.de/feed.xml"
T0 = datetime(2026, 11, 11, 8, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """Time that only moves when someone sleeps."""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeSite:
    """Answers only the URLs it was given and records every request."""

    def __init__(self, pages: dict[str, tuple[int, bytes]]):
        self.pages = dict(pages)
        self.requests: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.requests.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected request: {url}")
        return self.pages[url]


def client_for(conn, site, clock=None, min_delay=31.0):
    clock = clock or FakeClock()
    return PoliteClient(conn, site, min_delay=min_delay, clock=clock.time, sleep=clock.sleep)


def links_of(conn) -> list[str]:
    return [r["link"] for r in conn.execute("SELECT link FROM notices ORDER BY pub_date DESC")]


# ---------------------------------------------------------------- politeness

def test_second_request_waits_until_the_crawl_delay_has_passed(conn):
    site = FakeSite({FEED_URL: (200, b"x")})
    clock = FakeClock(start=1000.0)
    client = client_for(conn, site, clock, min_delay=31.0)

    client.get(FEED_URL)
    clock.now += 10  # ten seconds of other work
    client.get(FEED_URL)

    assert clock.sleeps == [21.0]


def test_crawl_delay_also_holds_for_a_new_client_on_the_same_database(conn):
    site = FakeSite({FEED_URL: (200, b"x")})
    clock = FakeClock(start=1000.0)

    client_for(conn, site, clock).get(FEED_URL)
    client_for(conn, site, clock).get(FEED_URL)  # e.g. the next `recall fetch`

    assert clock.sleeps == [31.0]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/feed.xml",  # other host
        "http://www.lebensmittelwarnung.de/feed.xml",  # not https
        "https://www.lebensmittelwarnung.de/DE/Service/Impressum/impressum_node.html",  # robots.txt
        "https://www.lebensmittelwarnung.de/EN/Service/x.html",  # robots.txt
        "https://www.lebensmittelwarnung.de/SiteGlobals/Forms/Suche.html",  # robots.txt
    ],
)
def test_requests_outside_what_robots_txt_allows_are_never_sent(conn, url):
    site = FakeSite({})
    client = client_for(conn, site)

    with pytest.raises(NotAllowed):
        client.get(url)

    assert site.requests == []


# ---------------------------------------------------------------------- feed

def test_feed_is_saved_unchanged_and_loaded_into_sqlite(conn, tmp_path, mini_feed):
    site = FakeSite({FEED_URL: (200, mini_feed)})

    result = fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0)

    assert result.downloaded is True
    assert result.path == tmp_path / "feed" / "feed_20261111T080000Z.xml"
    assert result.path.read_bytes() == mini_feed
    assert (result.total, result.new) == (3, 3)
    rows = conn.execute("SELECT id, title, pub_date, active FROM notices ORDER BY pub_date DESC").fetchall()
    assert [tuple(r) for r in rows] == [
        ("261109_09_NI_Corned_Beef", "Deutsches Corned Beef", "2026-11-10T14:35:00+01:00", 1),
        ("261109_10_BE_Wasabi_rice_crackers", "Wasabi rice crackers, 125 Gramm", "2026-11-09T15:45:00+01:00", 1),
        ("261106_05_SH_Rindfleischsalamiprodukte", "Diverse Rindfleischsalamiprodukte", "2026-11-09T09:22:00+01:00", 1),
    ]


def test_feed_younger_than_an_hour_is_not_downloaded_again(conn, tmp_path, mini_feed):
    site = FakeSite({FEED_URL: (200, mini_feed)})
    fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0)

    again = fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0 + timedelta(minutes=59))

    assert site.requests == [FEED_URL]
    assert again.downloaded is False
    assert again.total == 3


def test_feed_older_than_an_hour_is_downloaded_again(conn, tmp_path, mini_feed):
    site = FakeSite({FEED_URL: (200, mini_feed)})
    fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0)

    again = fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0 + timedelta(minutes=61))

    assert site.requests == [FEED_URL, FEED_URL]
    assert again.downloaded is True
    assert again.new == 0


def test_notice_that_left_the_feed_is_marked_inactive_not_deleted(conn, tmp_path, feed_bytes):
    site = FakeSite({FEED_URL: (200, cut_feed(feed_bytes, 3))})
    fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0)
    site.pages[FEED_URL] = (200, cut_feed(feed_bytes, 2))  # the salami notice is gone

    result = fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0 + timedelta(hours=2))

    assert result.removed == 1
    active = dict(conn.execute("SELECT id, active FROM notices").fetchall())
    assert active == {
        "261109_09_NI_Corned_Beef": 1,
        "261109_10_BE_Wasabi_rice_crackers": 1,
        "261106_05_SH_Rindfleischsalamiprodukte": 0,
    }


def test_failed_feed_download_saves_nothing_and_raises(conn, tmp_path):
    from recall.fetch import FetchError

    site = FakeSite({FEED_URL: (503, b"Service Unavailable")})

    with pytest.raises(FetchError, match="503"):
        fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: T0)

    assert not list((tmp_path / "feed").glob("*")) if (tmp_path / "feed").exists() else True
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0


# --------------------------------------------------------------------- pages

def loaded(conn, tmp_path, feed, site, when=T0):
    site.pages[FEED_URL] = (200, feed)
    fetch_feed(conn, client_for(conn, site), tmp_path, url=FEED_URL, now=lambda: when)


def test_each_notice_page_is_saved_unchanged_under_id_and_version(conn, tmp_path, mini_feed, page_bytes):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (200, b"<html>corned</html>"), wasabi: (200, b"<html>wasabi</html>"), salami: (200, page_bytes)})

    result = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)

    assert (result.fetched, result.failed, result.remaining) == (3, 0, 0)
    saved = tmp_path / "pages" / "261106_05_SH_Rindfleischsalamiprodukte__20261109T0922.html"
    assert saved.read_bytes() == page_bytes
    assert (tmp_path / "pages" / "261109_09_NI_Corned_Beef__20261110T1435.html").read_bytes() == b"<html>corned</html>"


def test_cached_pages_are_never_downloaded_again(conn, tmp_path, mini_feed):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    for link in links_of(conn):
        site.pages[link] = (200, b"<html>page</html>")
    fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)
    requests_after_first_run = list(site.requests)

    result = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)

    assert site.requests == requests_after_first_run
    assert (result.fetched, result.remaining) == (0, 0)


def test_page_file_already_on_disk_is_adopted_without_a_request(conn, tmp_path, mini_feed, page_bytes):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (200, b"c"), wasabi: (200, b"w")})  # no entry for salami: a request would fail
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "261106_05_SH_Rindfleischsalamiprodukte__20261109T0922.html").write_bytes(page_bytes)

    result = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)

    assert (result.fetched, result.adopted, result.remaining) == (2, 1, 0)
    assert salami not in site.requests


def test_updated_notice_gets_its_page_again_as_a_new_version(conn, tmp_path, mini_feed):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (200, b"old"), wasabi: (200, b"w"), salami: (200, b"s")})
    fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)
    # the authority corrects the corned beef notice the next morning
    updated = mini_feed.replace(b"<pubDate>Tue, 10 Nov 2026 14:35:00 +0100</pubDate>", b"<pubDate>Wed, 11 Nov 2026 09:05:00 +0100</pubDate>")
    assert updated != mini_feed
    loaded(conn, tmp_path, updated, site, when=T0 + timedelta(hours=2))
    site.pages[corned] = (200, b"corrected")
    site.requests.clear()

    result = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0 + timedelta(hours=2))

    assert site.requests == [corned]
    assert result.fetched == 1
    assert (tmp_path / "pages" / "261109_09_NI_Corned_Beef__20261111T0905.html").read_bytes() == b"corrected"
    assert (tmp_path / "pages" / "261109_09_NI_Corned_Beef__20261110T1435.html").read_bytes() == b"old"


def test_max_pages_fetches_only_the_newest_notices(conn, tmp_path, mini_feed):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (200, b"c"), wasabi: (200, b"w"), salami: (200, b"s")})
    site.requests.clear()

    result = fetch_pages(conn, client_for(conn, site), tmp_path, max_pages=2, now=lambda: T0)

    assert site.requests == [corned, wasabi]
    assert (result.fetched, result.remaining) == (2, 1)


def test_failed_page_is_not_saved_and_is_tried_again_next_time(conn, tmp_path, mini_feed):
    site = FakeSite({})
    loaded(conn, tmp_path, mini_feed, site)
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (500, b"oops"), wasabi: (200, b"w"), salami: (200, b"s")})

    first = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)

    assert (first.fetched, first.failed, first.remaining) == (2, 1, 1)
    assert not (tmp_path / "pages" / "261109_09_NI_Corned_Beef__20261110T1435.html").exists()

    site.pages[corned] = (200, b"c")
    second = fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0)

    assert (second.fetched, second.failed, second.remaining) == (1, 0, 0)


def test_pages_of_notices_that_left_the_feed_are_not_fetched(conn, tmp_path, feed_bytes):
    site = FakeSite({})
    loaded(conn, tmp_path, cut_feed(feed_bytes, 3), site)
    loaded(conn, tmp_path, cut_feed(feed_bytes, 2), site, when=T0 + timedelta(hours=2))
    corned, wasabi, salami = links_of(conn)
    site.pages.update({corned: (200, b"c"), wasabi: (200, b"w")})
    site.requests.clear()

    fetch_pages(conn, client_for(conn, site), tmp_path, now=lambda: T0 + timedelta(hours=2))

    assert site.requests == [corned, wasabi]
