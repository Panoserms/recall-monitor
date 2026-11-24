"""Stage 6: one line per match - product, reason, what to do, link.

The batch / best-before / EAN verdict is part of the line, so you can see at once
whether the pack in your cupboard is one of the recalled ones.
"""
from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel

from .extract import load_record
from .match import level_of
from .models import Record
from .textutils import one_line

REASONS = {
    "salmonella": "Salmonellen",
    "listeria": "Listerien",
    "foreign_object": "Fremdkörper",
    "undeclared_allergen": "nicht deklarierte Allergene",
}
VERDICTS = {
    "affected": "YOUR PACK IS AFFECTED",
    "not_affected": "your pack is not affected",
    "check": "check your pack",
}


def reason_of(record: Record) -> str:
    """Short reason: the category, then the notice's own words."""
    category = (record.values("reason_category") or [""])[0]
    label = REASONS.get(category) or record.extras.get("reason_official") or "Sonstiges"
    text = (record.values("reason_text") or [""])[0]
    return f"{label}: {one_line(text, 140)}" if text else str(label)


class Alert(BaseModel):
    level: str
    score: float
    my_name: str
    my_brand: str
    product_row: int
    notice_id: str
    title: str
    link: str
    reason: str
    match_reason: str
    what_to_do: str
    verdict: str
    check: str
    date: str

    def line(self) -> str:
        mine = f"{self.my_name} ({self.my_brand})" if self.my_brand else self.my_name
        return " | ".join(
            [
                f"[{self.level.upper()} {self.score:.0f}] {mine} -> {self.title}",
                self.reason,
                f"{VERDICTS[self.verdict]}: {self.check}",
                f"what to do: {one_line(self.what_to_do, 160) or 'see notice'}",
                self.link,
            ]
        )


def load_alerts(conn: sqlite3.Connection) -> list[Alert]:
    """Saved matches of notices that are still on the portal, best first."""
    alerts = []
    rows = conn.execute(
        "SELECT m.* FROM matches m JOIN notices n ON n.id = m.notice_id WHERE n.active = 1"
        " ORDER BY m.score DESC, m.product_row"
    ).fetchall()
    for row in rows:
        record = load_record(conn, row["notice_id"])
        if record is None:
            continue
        identifiers = json.loads(row["identifiers"])
        alerts.append(
            Alert(
                level=level_of(row["score"]),
                score=row["score"],
                my_name=row["my_name"],
                my_brand=row["my_brand"],
                product_row=row["product_row"],
                notice_id=row["notice_id"],
                title=record.title,
                link=record.link,
                reason=reason_of(record),
                match_reason=row["reason"],
                what_to_do=str(record.extras.get("what_to_do", "")),
                verdict=identifiers.get("verdict", "check"),
                check=identifiers.get("check", ""),
                date=(record.values("date") or [""])[0],
            )
        )
    return alerts
