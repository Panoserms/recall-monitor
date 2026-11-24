"""Shared test fixtures.

Tests never use the network. Tests that need real notices read two raw files
that were saved unchanged from the portal on 2026-11-11 and live in data/raw/
(not committed, see .gitignore). Without them those tests are skipped.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FEED_FIXTURE = RAW / "feed" / "feed_20261111T003953Z.xml"
PAGE_FIXTURE = RAW / "pages" / "261106_05_SH_Rindfleischsalamiprodukte__20261109T0922.html"


def _read_or_skip(path: Path) -> bytes:
    if not path.exists():
        pytest.skip(f"raw fixture missing: {path.relative_to(ROOT)} (it is not in git; see README, 'Tests')")
    return path.read_bytes()


@pytest.fixture(scope="session")
def feed_bytes() -> bytes:
    """The full food feed as downloaded on 2026-11-11 (223 notices)."""
    return _read_or_skip(FEED_FIXTURE)


@pytest.fixture(scope="session")
def page_bytes() -> bytes:
    """One notice page as downloaded on 2026-11-11 (salami, STEC)."""
    return _read_or_skip(PAGE_FIXTURE)


def cut_feed(feed: bytes, keep: int) -> bytes:
    """A smaller feed: the real header plus the first `keep` real items, unchanged."""
    text = feed.decode("utf-8")
    items = re.findall(r"<item>.*?</item>\n?", text, re.S)
    head = text[: text.index("<item>")]
    return (head + "".join(items[:keep]) + "</channel>\n</rss>\n").encode("utf-8")


@pytest.fixture(scope="session")
def mini_feed(feed_bytes: bytes) -> bytes:
    """The three newest notices of the real feed."""
    return cut_feed(feed_bytes, 3)


@pytest.fixture
def conn(tmp_path):
    from recall import db

    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def nlp():
    """The small German spaCy model (loaded once per test run)."""
    from recall.nlp import get_nlp

    return get_nlp()
