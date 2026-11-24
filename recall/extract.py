"""Stage 2: turn every notice into a record, field by field, and store it.

For each notice: feed item (+ saved page) -> sections (parse.py) -> one rule module per
field (rules/) -> optional model fallback for fields the rules left open (llm.py) ->
the tables `fields` and `extras`.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from . import parse
from .feed import version_of
from .models import FIELDS, FieldValue, NoticeText, Record
from .rules import batch, best_before, brand, date, ean, manufacturer, product, reason_category, reason_text, sellers, states
from .textutils import find_dates

# fallback(notice, names of the open fields) -> values for some of them (see llm.py)
Fallback = Callable[[NoticeText, list[str]], dict[str, FieldValue]]

_RULES = {
    "product_name": product.extract,
    "brand": brand.extract,
    "manufacturer": manufacturer.extract,
    "batch": batch.extract,
    "best_before": best_before.extract,
    "reason_category": reason_category.extract,
    "reason_text": reason_text.extract,
    "states": states.extract,
    "date": date.extract,
}
_IMAGE = re.compile(r'<img src="([^"]+)"')


# ------------------------------------------------------------------- reading

def notice_text(conn: sqlite3.Connection, row: sqlite3.Row, raw_dir: Path) -> NoticeText:
    """The sections of one notice from its feed item and its newest saved page.

    A page saved for the current version is the fuller source and wins. A page saved
    before the last update may hold old batch numbers, so then the feed wins and the
    old page only adds what the feed does not have (reason text, advice)."""
    feed = parse.feed_sections(row["feed_item"])
    current = version_of(datetime.fromisoformat(row["pub_date"]))
    page_row = conn.execute(
        "SELECT version, path FROM pages WHERE notice_id = ? ORDER BY version DESC LIMIT 1", (row["id"],)
    ).fetchone()
    page_bytes = None
    if page_row and (raw_dir / "pages" / page_row["path"]).exists():
        page_bytes = (raw_dir / "pages" / page_row["path"]).read_bytes()
    is_current = bool(page_bytes) and page_row["version"] >= current
    if page_bytes is None:
        sections = feed
    elif is_current:
        sections = parse.merge_sections(feed, parse.page_sections(page_bytes))
    else:
        sections = parse.merge_sections(parse.page_sections(page_bytes), feed)
    attachments = [urljoin(row["link"], href) for href in parse.page_attachments(page_bytes)] if page_bytes else []
    return NoticeText(
        id=row["id"],
        title=row["title"],
        link=row["link"],
        pub_date=row["pub_date"],
        sections=sections,
        has_page=page_bytes is not None,
        page_is_current=is_current,
        raw_item=row["feed_item"],
        attachments=attachments,
    )


# ---------------------------------------------------------------- extracting

def _iso(text: str) -> str:
    dates = find_dates(text)
    return dates[0].iso if dates else ""


def extras_of(notice: NoticeText) -> dict[str, str | list[str]]:
    """What the alert and the web page show besides the ten fields. Copied, not interpreted."""
    s = notice.sections
    image = _IMAGE.search(notice.raw_item)
    found = {
        "what_to_do": s.get("recommendation", ""),
        "consequences": s.get("consequences", ""),
        "package": s.get("package", ""),
        "marking": s.get("marking", ""),
        "reason_official": s.get("reason_official", ""),
        "update_notes": s.get("update_notes", ""),
        "reported_by": s.get("reported_by", ""),
        "first_published": _iso(s.get("first_published", "")),
        "last_updated": _iso(s.get("last_updated", "")),
        "image": image.group(1).replace("&amp;", "&") if image else "",
        "image_source": s.get("image_source", ""),
        "attachments": notice.attachments,
        "ean": ean.extract(notice).values,
        "has_page": "yes" if notice.has_page else "no",
        "page_is_current": "yes" if notice.page_is_current else "no",
    }
    return {k: v for k, v in found.items() if v}


def is_open(value: FieldValue) -> bool:
    """Left empty by the rules, and the notice does not say the value is unknown."""
    return value.source == "none" and value.rule is None


def extract_notice(notice: NoticeText, nlp=None, fallback: Fallback | None = None) -> Record:
    fields = {name: rule(notice) for name, rule in _RULES.items()}
    fields["sellers"] = sellers.extract(notice, nlp)
    if fallback:
        open_fields = [name for name in FIELDS if is_open(fields[name])]
        if open_fields:
            for name, value in fallback(notice, open_fields).items():
                if name in open_fields and value.values:
                    fields[name] = value
    return Record(
        id=notice.id,
        title=notice.title,
        link=notice.link,
        pub_date=notice.pub_date,
        fields={name: fields[name] for name in FIELDS},
        extras=extras_of(notice),
    )


# ------------------------------------------------------------------- storage

def save_record(conn: sqlite3.Connection, record: Record) -> None:
    conn.execute("DELETE FROM fields WHERE notice_id = ?", (record.id,))
    conn.executemany(
        "INSERT INTO fields (notice_id, field, value, source, rule, evidence) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (record.id, name, json.dumps(value.values, ensure_ascii=False), value.source, value.rule, value.evidence)
            for name, value in record.fields.items()
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO extras (notice_id, data) VALUES (?, ?)",
        (record.id, json.dumps(record.extras, ensure_ascii=False)),
    )


def load_record(conn: sqlite3.Connection, notice_id: str) -> Record | None:
    row = conn.execute("SELECT id, title, link, pub_date FROM notices WHERE id = ?", (notice_id,)).fetchone()
    if row is None:
        return None
    fields = {
        f["field"]: FieldValue(values=json.loads(f["value"]), source=f["source"], rule=f["rule"], evidence=f["evidence"])
        for f in conn.execute("SELECT * FROM fields WHERE notice_id = ?", (notice_id,))
    }
    extras_row = conn.execute("SELECT data FROM extras WHERE notice_id = ?", (notice_id,)).fetchone()
    return Record(
        id=row["id"], title=row["title"], link=row["link"], pub_date=row["pub_date"],
        fields=fields, extras=json.loads(extras_row["data"]) if extras_row else {},
    )


def load_records(conn: sqlite3.Connection, *, active_only: bool = True) -> list[Record]:
    """All extracted records, newest first. Notices the portal has removed are left out by default."""
    where = "WHERE active = 1" if active_only else ""
    ids = [r["id"] for r in conn.execute(f"SELECT id FROM notices {where} ORDER BY pub_date DESC")]
    records = [load_record(conn, i) for i in ids]
    return [r for r in records if r and r.fields]


# ----------------------------------------------------------------------- run

@dataclass
class ExtractResult:
    notices: int = 0
    seconds: float = 0.0
    sources: Counter = field(default_factory=Counter)  # source -> number of fields
    filled: int = 0  # fields with a value
    model_calls: int = 0


def log_run(conn: sqlite3.Connection, command: str, started: datetime, seconds: float, details: dict) -> None:
    conn.execute(
        "INSERT INTO runs (command, started_at, seconds, details) VALUES (?, ?, ?, ?)",
        (command, started.isoformat(timespec="seconds"), seconds, json.dumps(details, ensure_ascii=False)),
    )


def run(
    conn: sqlite3.Connection,
    raw_dir: Path,
    *,
    nlp=None,
    fallback: Fallback | None = None,
    only: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ExtractResult:
    started, clock = datetime.now(timezone.utc), time.perf_counter()
    rows = conn.execute("SELECT * FROM notices WHERE active = 1 ORDER BY pub_date DESC").fetchall()
    if only is not None:
        rows = [r for r in rows if r["id"] in set(only)]
    result = ExtractResult()
    calls = Counter()

    def counting_fallback(notice: NoticeText, open_fields: list[str]) -> dict[str, FieldValue]:
        calls["n"] += 1
        return fallback(notice, open_fields)

    for number, row in enumerate(rows, start=1):
        record = extract_notice(notice_text(conn, row, raw_dir), nlp, counting_fallback if fallback else None)
        conn.execute("BEGIN")
        save_record(conn, record)
        conn.execute("COMMIT")
        for value in record.fields.values():
            result.sources[value.source] += 1
            result.filled += bool(value.values)
        result.notices += 1
        if on_progress and number % 25 == 0:
            on_progress(f"  {number}/{len(rows)} notices")
    result.seconds = time.perf_counter() - clock
    result.model_calls = calls["n"]
    log_run(
        conn, "extract", started, result.seconds,
        {"notices": result.notices, "sources": dict(result.sources), "filled": result.filled,
         "model": bool(fallback), "model_calls": result.model_calls},
    )
    return result
