"""Stage 2 end to end: notices in SQLite -> records in the fields and extras tables.

Uses the real feed of 2026-11-11 and the real salami page (STEC) saved the same day.
"""
from datetime import datetime, timezone

from conftest import PAGE_FIXTURE, RAW

from recall import extract
from recall.feed import parse_feed
from recall.fetch import load_feed
from recall.models import FIELDS

SALAMI = "261106_05_SH_Rindfleischsalamiprodukte"


def _loaded(conn, feed_bytes, *, page_version: str | None = "20261109T0922"):
    load_feed(conn, parse_feed(feed_bytes), datetime(2026, 11, 11, tzinfo=timezone.utc))
    if page_version:
        conn.execute(
            "INSERT INTO pages (notice_id, version, path, fetched_at) VALUES (?, ?, ?, ?)",
            (SALAMI, page_version, PAGE_FIXTURE.name, "2026-11-11T00:00:00+00:00"),
        )
    return conn.execute("SELECT * FROM notices WHERE id = ?", (SALAMI,)).fetchone()


def test_a_notice_with_its_page_has_the_page_sections(conn, feed_bytes, page_bytes):
    notice = extract.notice_text(conn, _loaded(conn, feed_bytes), RAW)
    assert notice.has_page
    assert "STEC" in notice.sections["more_info"]  # only the page has "Weitere Informationen"
    assert notice.sections["image_source"]  # only the feed has "Bildquelle"


def test_without_a_page_the_feed_alone_is_used(conn, feed_bytes):
    notice = extract.notice_text(conn, _loaded(conn, feed_bytes, page_version=None), RAW)
    assert not notice.has_page
    assert "more_info" not in notice.sections


def test_an_outdated_page_does_not_override_the_newer_feed(conn, feed_bytes, page_bytes):
    row = _loaded(conn, feed_bytes, page_version="20261101T0000")  # page saved before the last update
    notice = extract.notice_text(conn, row, RAW)
    assert notice.has_page and not notice.page_is_current
    feed_only = extract.notice_text(conn, _loaded_without_page(conn, row), RAW)
    for name, value in feed_only.sections.items():
        assert notice.sections[name] == value  # every feed section wins
    assert "more_info" in notice.sections  # the old page still adds what the feed lacks


def _loaded_without_page(conn, row):
    conn.execute("DELETE FROM pages WHERE notice_id = ?", (row["id"],))
    return row


def test_record_has_every_field_with_a_source(conn, feed_bytes, page_bytes, nlp):
    record = extract.extract_notice(extract.notice_text(conn, _loaded(conn, feed_bytes), RAW), nlp)
    assert set(record.fields) == set(FIELDS)
    assert record.fields["reason_category"].values == ["other"]  # STEC is neither salmonella nor listeria
    assert record.fields["states"].source == "structured"
    assert record.extras["what_to_do"]
    assert record.extras["image"].startswith("https://www.lebensmittelwarnung.de/")


def test_run_stores_records_and_can_read_them_back(conn, feed_bytes, page_bytes, nlp):
    _loaded(conn, feed_bytes)
    result = extract.run(conn, RAW, nlp=nlp, only=[SALAMI])
    assert result.notices == 1
    stored = extract.load_record(conn, SALAMI)
    assert stored.fields["reason_category"].values == ["other"]
    assert stored.extras["what_to_do"]
    run = conn.execute("SELECT command, seconds FROM runs").fetchone()
    assert run["command"] == "extract" and run["seconds"] >= 0


def test_running_twice_replaces_instead_of_adding(conn, feed_bytes, page_bytes, nlp):
    _loaded(conn, feed_bytes)
    extract.run(conn, RAW, nlp=nlp, only=[SALAMI])
    extract.run(conn, RAW, nlp=nlp, only=[SALAMI])
    assert conn.execute("SELECT COUNT(*) FROM fields WHERE notice_id = ?", (SALAMI,)).fetchone()[0] == len(FIELDS)
