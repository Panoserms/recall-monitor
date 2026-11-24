"""What the pages show: records, your products, and matches, cached until something changes."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable

from .. import match as matching
from ..alert import REASONS
from ..match import _show_date, level_of
from ..models import FIELDS, FieldValue, Record
from ..normalise import fold
from ..textutils import one_line

STATE_SHORT = {
    "Baden-Württemberg": "BW", "Bayern": "BY", "Berlin": "BE", "Brandenburg": "BB", "Bremen": "HB", "Hamburg": "HH",
    "Hessen": "HE", "Mecklenburg-Vorpommern": "MV", "Niedersachsen": "NI", "Nordrhein-Westfalen": "NW",
    "Rheinland-Pfalz": "RP", "Saarland": "SL", "Sachsen": "SN", "Sachsen-Anhalt": "ST", "Schleswig-Holstein": "SH",
    "Thüringen": "TH",
}
REASON_LABEL = {
    "salmonella": "Salmonella", "listeria": "Listeria", "foreign_object": "Foreign object",
    "undeclared_allergen": "Allergen", "other": "Other reason", "": "Reason not named",
}
FIELD_LABEL = {
    "product_name": "Product", "brand": "Brand", "manufacturer": "Company", "batch": "Batch", "best_before": "Best before",
    "reason_category": "Reason", "reason_text": "Reason text", "sellers": "Sold at", "states": "States", "date": "Published",
}
SOURCE_LABEL = {"structured": "portal field", "rule": "rule", "model": "local model", "none": "not found"}
VERDICT_LABEL = {"affected": "Your pack is affected", "not_affected": "Your pack is not affected", "check": "Check your pack"}


# the portal's own reason (first one listed), used when the category is "other"
OFFICIAL_GROUP = {
    "Krankheitserreger": ("pathogen", "Other pathogen"),
    "Rückstände und Kontaminanten": ("substance", "Residues, contaminants"),
    "Gesundheitsschädliche Substanz": ("substance", "Harmful substance"),
    "Irreführung und Täuschung": ("other", "Misleading label"),
    "Sonstige Gründe": ("other", "Other reason"),
}
FILTERS = [
    ("", "All reasons"), ("salmonella", "Salmonella"), ("listeria", "Listeria"), ("pathogen", "Other pathogen"),
    ("foreign_object", "Foreign object"), ("undeclared_allergen", "Allergen"), ("substance", "Harmful substance"),
    ("other", "Other"),
]


def reason_group(record: Record) -> tuple[str, str]:
    """(filter group, label) of a recall: the category, refined by the portal's reason for "other"."""
    category = _first(record, "reason_category")
    if category and category != "other":
        return category, REASON_LABEL[category]
    official = str(record.extras.get("reason_official", "")).split("\n")[0].strip()
    return OFFICIAL_GROUP.get(official, ("other", "Other reason"))


def german_date(iso: str) -> str:
    return _show_date(iso) if iso and iso[:1].isdigit() else iso


def _first(record: Record, name: str) -> str:
    values = record.values(name)
    return values[0] if values else ""


def recall_view(record: Record, detail: bool = False) -> dict:
    """One recall as the templates and the JSON API see it."""
    group, label = reason_group(record)
    states = record.values("states")
    eans = record.extras.get("ean") or []
    view = {
        "id": record.id,
        "title": record.title,
        "link": record.link,
        "date": _first(record, "date"),
        "date_display": german_date(_first(record, "date")),
        "products": record.values("product_name"),
        "brand": ", ".join(record.values("brand")),
        "company": ", ".join(record.values("manufacturer")),
        "reason": group,
        "reason_label": label,
        "is_pathogen": group in ("salmonella", "listeria", "pathogen"),
        "reason_official": record.extras.get("reason_official", ""),
        "states": states,
        "states_short": [STATE_SHORT.get(s, s) for s in states],
        "all_states": len(states) == 16,
        "batch": record.values("batch"),
        "best_before": [german_date(v) for v in record.values("best_before")],
        "ean": eans,
        "search": fold(" ".join([record.title, *record.values("product_name"), *record.values("brand"),
                                 *record.values("manufacturer"), *record.values("batch"), *eans])),
    }
    if detail:
        view.update(
            reason_text=_first(record, "reason_text"),
            what_to_do=str(record.extras.get("what_to_do", "")),
            consequences=str(record.extras.get("consequences", "")),
            sellers=record.values("sellers"),
            package=str(record.extras.get("package", "")),
            image=str(record.extras.get("image", "")),
            image_source=str(record.extras.get("image_source", "")),
            attachments=record.extras.get("attachments") or [],
            first_published=german_date(str(record.extras.get("first_published", ""))),
            last_updated=german_date(str(record.extras.get("last_updated", ""))),
            update_notes=str(record.extras.get("update_notes", "")),
            has_page=record.extras.get("has_page") == "yes",
            fields=[_field_view(name, record.fields.get(name, FieldValue())) for name in FIELDS],
        )
    return view


def _field_view(name: str, value: FieldValue) -> dict:
    shown = [german_date(v) for v in value.values] if name in ("best_before", "date") else value.values
    if name == "reason_category":
        shown = [REASON_LABEL.get(v, v) for v in value.values]
    return {
        "name": name,
        "label": FIELD_LABEL[name],
        "shown": shown,
        "source": value.source,
        "source_label": SOURCE_LABEL[value.source],
        "rule": value.rule or "",
        "evidence": one_line(value.evidence or "", 400),
    }


# --------------------------------------------------------------------- store

def _load_records(conn: sqlite3.Connection) -> list[Record]:
    """Every current record in three queries, newest first."""
    notices = conn.execute(
        "SELECT id, title, link, pub_date FROM notices WHERE active = 1 ORDER BY pub_date DESC"
    ).fetchall()
    fields: dict[str, dict[str, FieldValue]] = {}
    for f in conn.execute("SELECT * FROM fields"):
        fields.setdefault(f["notice_id"], {})[f["field"]] = FieldValue(
            values=json.loads(f["value"]), source=f["source"], rule=f["rule"], evidence=f["evidence"]
        )
    extras = {e["notice_id"]: json.loads(e["data"]) for e in conn.execute("SELECT notice_id, data FROM extras")}
    records = []
    for n in notices:
        if n["id"] in fields:
            records.append(Record(id=n["id"], title=n["title"], link=n["link"], pub_date=n["pub_date"],
                                  fields=fields[n["id"]], extras=extras.get(n["id"], {})))
    # newest first by publication date, not by last update
    return sorted(records, key=lambda r: (_first(r, "date"), r.pub_date), reverse=True)


class Store:
    def __init__(self, connect: Callable[[], sqlite3.Connection], products_path: Path):
        self._connect = connect
        self.products_path = products_path
        self._lock = threading.Lock()
        self._records: list[Record] = []
        self._records_key: tuple | None = None
        self._alerts: list[dict] = []
        self._alerts_key: tuple | None = None

    # records ---------------------------------------------------------------
    def _key(self, conn: sqlite3.Connection) -> tuple:
        return (
            conn.execute("SELECT COALESCE(MAX(id), 0) FROM runs").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0],
            conn.execute("SELECT COALESCE(SUM(active), 0), COUNT(*) FROM notices").fetchone()[:],
        )

    def records(self) -> list[Record]:
        conn = self._connect()
        try:
            key = self._key(conn)
            with self._lock:
                if key != self._records_key:
                    self._records, self._records_key = _load_records(conn), key
                return self._records
        finally:
            conn.close()

    def record(self, notice_id: str) -> Record | None:
        return next((r for r in self.records() if r.id == notice_id), None)

    # products --------------------------------------------------------------
    def products(self) -> list[matching.MyProduct]:
        return matching.load_products(self.products_path) if self.products_path.exists() else []

    def save_products(self, products: list[matching.MyProduct]) -> None:
        renumbered = [p.model_copy(update={"row": i}) for i, p in enumerate(products, start=1)]
        matching.save_products(self.products_path, renumbered)
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            self._alerts_key = None

    # matches ---------------------------------------------------------------
    def alert_view(self, m: matching.Match) -> dict:
        record = self.record(m.notice_id)
        view = recall_view(record, detail=True) if record else {}
        return {
            "product_row": m.product.row,
            "my_name": m.product.name,
            "my_brand": m.product.brand,
            "notice_id": m.notice_id,
            "title": m.title,
            "link": m.link,
            "score": m.score,
            "level": level_of(m.score),
            "match_reason": m.reason,
            "verdict": m.identifiers.get("verdict", "check"),
            "verdict_label": VERDICT_LABEL[m.identifiers.get("verdict", "check")],
            "checks": m.identifiers.get("checks", {}),
            "check": m.identifiers.get("check", ""),
            "reason_label": view.get("reason_label", ""),
            "is_pathogen": view.get("is_pathogen", False),
            "reason_text": view.get("reason_text", ""),
            "what_to_do": view.get("what_to_do", ""),
            "batch": view.get("batch", []),
            "best_before": view.get("best_before", []),
            "ean": view.get("ean", []),
            "date_display": view.get("date_display", ""),
        }

    def alerts(self) -> list[dict]:
        """Matches between your products and the current recalls; also saved for `recall alert`."""
        records = self.records()
        mtime = self.products_path.stat().st_mtime_ns if self.products_path.exists() else 0
        key = (self._records_key, mtime)
        with self._lock:
            if key == self._alerts_key:
                return self._alerts
        found = matching.find_matches(self.products(), records)
        conn = self._connect()
        try:
            matching.save_matches(conn, found)
        finally:
            conn.close()
        views = [self.alert_view(m) for m in found]
        with self._lock:
            self._alerts, self._alerts_key = views, key
        return views

    def status(self) -> dict:
        conn = self._connect()
        try:
            seen = conn.execute("SELECT MAX(last_seen) FROM notices").fetchone()[0] or ""
            run = conn.execute("SELECT started_at FROM runs WHERE command = 'extract' ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return {"feed_checked": german_date(seen[:10]) if seen else "", "extracted": german_date(run[0][:10]) if run else ""}


__all__ = ["Store", "recall_view", "REASONS"]
