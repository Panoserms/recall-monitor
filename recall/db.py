"""SQLite storage. The raw files in data/raw/ stay the source of truth."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id         TEXT PRIMARY KEY,      -- folder name of the notice link
    link       TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    pub_date   TEXT NOT NULL,         -- feed pubDate = last update of the notice (ISO 8601)
    feed_item  TEXT NOT NULL,         -- the raw <item> from the feed, unchanged
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1   -- 0 = no longer in the feed
);
CREATE TABLE IF NOT EXISTS pages (
    notice_id  TEXT NOT NULL REFERENCES notices(id),
    version    TEXT NOT NULL,         -- pub_date of the notice when the page was saved
    path       TEXT NOT NULL,         -- file name inside data/raw/pages/
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (notice_id, version)
);
CREATE TABLE IF NOT EXISTS fields (
    notice_id  TEXT NOT NULL REFERENCES notices(id),
    field      TEXT NOT NULL,
    value      TEXT NOT NULL,         -- JSON: a string or a list of strings
    source     TEXT NOT NULL,         -- structured | rule | model | none
    rule       TEXT,                  -- which rule produced it
    evidence   TEXT,                  -- the piece of text the value was read from
    PRIMARY KEY (notice_id, field)
);
CREATE TABLE IF NOT EXISTS extras (
    notice_id  TEXT PRIMARY KEY REFERENCES notices(id),
    data       TEXT NOT NULL          -- JSON: what_to_do, package, consequences, ...
);
CREATE TABLE IF NOT EXISTS matches (
    product_row   INTEGER NOT NULL,   -- line in the product list (1 = first product)
    my_name       TEXT NOT NULL,
    my_brand      TEXT NOT NULL,
    notice_id     TEXT NOT NULL REFERENCES notices(id),
    recall_name   TEXT NOT NULL,
    score         REAL NOT NULL,
    reason        TEXT NOT NULL,
    identifiers   TEXT NOT NULL,      -- JSON: verdict on the batch / best-before date of your pack
    PRIMARY KEY (product_row, notice_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    command    TEXT NOT NULL,
    started_at TEXT NOT NULL,
    seconds    REAL NOT NULL,
    details    TEXT NOT NULL          -- JSON
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, isolation_level=None)  # autocommit; explicit BEGIN where needed
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
