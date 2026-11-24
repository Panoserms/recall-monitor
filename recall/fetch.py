"""Stage 1: download the feed and the notice pages, politely and only once.

Raw responses are saved unchanged in data/raw/:
    feed/feed_<UTC time>.xml
    pages/<notice id>__<version>.html      (version = time of the notice's last update)
A notice that the authority corrects gets a new version, so its page is fetched once more.
"""
from __future__ import annotations

import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import config
from .db import get_meta, set_meta
from .feed import FeedItem, parse_feed, version_of

Transport = Callable[[str], tuple[int, bytes]]


class NotAllowed(Exception):
    """The URL is outside what the tool may request (wrong host or robots.txt)."""


class FetchError(Exception):
    """A download failed."""


def check_allowed(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != config.ALLOWED_HOST:
        raise NotAllowed(f"only https://{config.ALLOWED_HOST} is requested, not {url}")
    if parts.path.startswith(config.DISALLOWED_PREFIXES):
        raise NotAllowed(f"robots.txt disallows {parts.path}")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(url: str) -> tuple[int, bytes]:
    """One GET with the standard library. Returns (status, body); the body is not touched."""
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    opener = urllib.request.build_opener(_CheckedRedirects)
    try:
        with opener.open(request, timeout=config.REQUEST_TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class PoliteClient:
    """Sends requests no faster than the site's crawl delay.

    The time of the last request is kept in the database, so the delay also
    holds between two runs of the program and between two programs.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        transport: Transport = urllib_transport,
        *,
        min_delay: float = config.MIN_DELAY_S,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.conn = conn
        self.transport = transport
        self.min_delay = min_delay
        self.clock = clock
        self.sleep = sleep

    def _reserve_slot(self) -> float:
        """Book the next free moment for a request and return how long to wait for it."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            now = self.clock()
            last = get_meta(self.conn, "last_request_epoch")
            slot = now if last is None else max(now, float(last) + self.min_delay)
            set_meta(self.conn, "last_request_epoch", repr(slot))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return slot - now

    def get(self, url: str) -> tuple[int, bytes]:
        check_allowed(url)
        wait = self._reserve_slot()
        if wait > 0:
            self.sleep(wait)
        return self.transport(url)


# ---------------------------------------------------------------------- feed

@dataclass
class FeedResult:
    path: Path
    downloaded: bool  # False = a saved feed younger than the TTL was used
    total: int
    new: int
    updated: int
    removed: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _newest_feed(feed_dir: Path) -> tuple[Path, datetime] | None:
    newest = None
    for path in feed_dir.glob("feed_*.xml"):
        try:
            saved = datetime.strptime(path.stem, "feed_%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if newest is None or saved > newest[1]:
            newest = (path, saved)
    return newest


def load_feed(conn: sqlite3.Connection, items: list[FeedItem], seen_at: datetime) -> tuple[int, int, int]:
    """Put the feed's notices into SQLite. Returns (new, updated, removed)."""
    stamp = seen_at.isoformat(timespec="seconds")
    new = updated = 0
    conn.execute("BEGIN")
    try:
        known = {r["id"]: r["pub_date"] for r in conn.execute("SELECT id, pub_date FROM notices")}
        for item in items:
            pub = item.pub_date.isoformat()
            if item.id not in known:
                new += 1
                conn.execute(
                    "INSERT INTO notices (id, link, title, pub_date, feed_item, first_seen, last_seen, active)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (item.id, item.link, item.title, pub, item.raw, stamp, stamp),
                )
            else:
                updated += known[item.id] != pub
                conn.execute(
                    "UPDATE notices SET link = ?, title = ?, pub_date = ?, feed_item = ?, last_seen = ?, active = 1"
                    " WHERE id = ?",
                    (item.link, item.title, pub, item.raw, stamp, item.id),
                )
        in_feed = {item.id for item in items}
        gone = [(i,) for i in known if i not in in_feed]
        removed = conn.execute(
            f"SELECT COUNT(*) FROM notices WHERE active = 1 AND id IN ({','.join('?' * len(gone))})",
            [g[0] for g in gone],
        ).fetchone()[0] if gone else 0
        conn.executemany("UPDATE notices SET active = 0 WHERE id = ?", gone)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return new, updated, removed


def fetch_feed(
    conn: sqlite3.Connection,
    client: PoliteClient,
    raw_dir: Path,
    *,
    url: str = config.FEED_URL,
    ttl: float = config.FEED_TTL_S,
    now: Callable[[], datetime] = _utc_now,
) -> FeedResult:
    feed_dir = raw_dir / "feed"
    moment = now()
    cached = _newest_feed(feed_dir) if feed_dir.exists() else None
    if cached and (moment - cached[1]).total_seconds() < ttl:
        path, saved_at, downloaded = cached[0], cached[1], False
        data = path.read_bytes()
    else:
        status, data = client.get(url)
        if status != 200:
            raise FetchError(f"feed download failed with HTTP {status}")
        items = parse_feed(data)  # a broken feed must not be saved as if it were fine
        feed_dir.mkdir(parents=True, exist_ok=True)
        path = feed_dir / f"feed_{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.xml"
        path.write_bytes(data)
        saved_at, downloaded = moment, True
    items = parse_feed(data)
    new, updated, removed = load_feed(conn, items, saved_at)
    return FeedResult(path=path, downloaded=downloaded, total=len(items), new=new, updated=updated, removed=removed)


# --------------------------------------------------------------------- pages

@dataclass
class PagesResult:
    fetched: int = 0  # downloaded in this run
    adopted: int = 0  # file was already in data/raw/pages/, only registered
    failed: int = 0
    remaining: int = 0  # still without a page after this run


def page_file_name(notice_id: str, pub_date_iso: str) -> str:
    return f"{notice_id}__{version_of(datetime.fromisoformat(pub_date_iso))}.html"


def _missing_pages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Active notices whose current version has no saved page, newest first."""
    rows = conn.execute("SELECT id, link, pub_date FROM notices WHERE active = 1 ORDER BY pub_date DESC").fetchall()
    have = {(r["notice_id"], r["version"]) for r in conn.execute("SELECT notice_id, version FROM pages")}
    return [r for r in rows if (r["id"], version_of(datetime.fromisoformat(r["pub_date"]))) not in have]


MAX_FAILURES_IN_A_ROW = 3


def fetch_pages(
    conn: sqlite3.Connection,
    client: PoliteClient,
    raw_dir: Path,
    *,
    max_pages: int | None = None,
    on_progress: Callable[[str], None] | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> PagesResult:
    pages_dir = raw_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    result = PagesResult()
    say = on_progress or (lambda message: None)

    def register(row: sqlite3.Row, name: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO pages (notice_id, version, path, fetched_at) VALUES (?, ?, ?, ?)",
            (row["id"], version_of(datetime.fromisoformat(row["pub_date"])), name, now().isoformat(timespec="seconds")),
        )

    todo = []
    for row in _missing_pages(conn):
        name = page_file_name(row["id"], row["pub_date"])
        if (pages_dir / name).exists():  # saved earlier, e.g. before the database was rebuilt
            register(row, name)
            result.adopted += 1
        else:
            todo.append((row, name))

    failures_in_a_row = 0
    budget = len(todo) if max_pages is None else min(max_pages, len(todo))
    for number, (row, name) in enumerate(todo[:budget], start=1):
        try:
            status, body = client.get(row["link"])
        except (OSError, NotAllowed) as error:
            status, body = None, str(error).encode()
        if status == 200:
            (pages_dir / name).write_bytes(body)
            register(row, name)
            result.fetched += 1
            failures_in_a_row = 0
            say(f"[{number}/{budget}] saved {name} ({len(body) / 1000:.0f} kB)")
        else:
            result.failed += 1
            failures_in_a_row += 1
            say(f"[{number}/{budget}] FAILED {row['id']} ({'HTTP ' + str(status) if status else body.decode(errors='replace')})")
            if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                say(f"stopping after {MAX_FAILURES_IN_A_ROW} failures in a row; run `recall fetch` again later")
                break
    result.remaining = len(_missing_pages(conn))
    return result
