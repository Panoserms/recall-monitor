"""Stage 7: how good is the extraction?

    make_template   data/gold_template.csv: 100 randomly drawn notices, empty label columns.
                    You fill it in by hand and save it as data/gold.csv. This code never writes gold.csv.
    score           per-field precision and recall against data/gold.csv, also split by source
                    (structured / rule / model), so you can see whether the model helps or hurts.
    source_shares   share of filled fields that came from rules alone.

Label format (one cell per field): values separated by " | ", dates as 2028-03-01 (or 2028-03
for a month, 2027-05-31..2027-07-02 for a range, "alle" for every date), "-" when the notice
states no value, an empty cell when you did not label that field.
"""
from __future__ import annotations

import csv
import json
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .extract import load_record
from .match import MyProduct, match_product
from .models import FIELDS
from .normalise import fold
from .textutils import find_dates

SEED = 20261112
NO_VALUE = "-"


def make_template(conn: sqlite3.Connection, path: Path, *, size: int = 100, seed: int = SEED) -> int:
    """Write the labelling sheet. Returns the number of notices in it."""
    if path.name == "gold.csv":
        raise ValueError("refusing to write gold.csv: it holds your hand labels; the template is gold_template.csv")
    ids = [r["id"] for r in conn.execute(
        "SELECT DISTINCT n.id FROM notices n JOIN fields f ON f.notice_id = n.id WHERE n.active = 1 ORDER BY n.id"
    )]
    sample = sorted(random.Random(seed).sample(ids, min(size, len(ids))))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["notice_id", "link", "title", *FIELDS])
        for notice_id in sample:
            row = conn.execute("SELECT link, title FROM notices WHERE id = ?", (notice_id,)).fetchone()
            writer.writerow([notice_id, row["link"], row["title"], *([""] * len(FIELDS))])
    return len(sample)


# ------------------------------------------------------------------- scoring

def _key(value: str) -> str:
    return "".join(ch for ch in fold(value) if ch.isalnum() or ch in ".!")


def _gold_values(field_name: str, cell: str) -> list[str]:
    values = [v.strip() for v in cell.split("|") if v.strip()]
    if field_name in ("best_before", "date"):
        normalised = []
        for value in values:
            dates = find_dates(value, short_years=True)
            whole = len(dates) == 1 and dates[0].text.strip() == value
            normalised.append(dates[0].iso if whole else value)
        values = normalised
    return values


@dataclass
class FieldScore:
    notices: int = 0  # notices with a label for this field
    gold: int = 0  # labelled values
    predicted: int = 0  # values the pipeline gave for those notices
    true_pos: int = 0
    empty_correct: int = 0  # notice states no value, pipeline gave none
    by_source: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # source -> [true_pos, predicted]

    @property
    def precision(self) -> float | None:
        return self.true_pos / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_pos / self.gold if self.gold else None


@dataclass
class Report:
    labelled_notices: int = 0
    missing: list[str] = field(default_factory=list)  # labelled notices with no record (not extracted)
    fields: dict[str, FieldScore] = field(default_factory=lambda: {f: FieldScore() for f in FIELDS})

    def total(self) -> FieldScore:
        total = FieldScore()
        for score in self.fields.values():
            total.notices += score.notices
            total.gold += score.gold
            total.predicted += score.predicted
            total.true_pos += score.true_pos
            total.empty_correct += score.empty_correct
            for source, (tp, predicted) in score.by_source.items():
                total.by_source[source][0] += tp
                total.by_source[source][1] += predicted
        return total


def score(conn: sqlite3.Connection, gold_path: Path) -> Report:
    report = Report()
    with gold_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        notice_id = (row.get("notice_id") or "").strip()
        if not notice_id or not any((row.get(f) or "").strip() for f in FIELDS):
            continue
        record = load_record(conn, notice_id)
        if record is None or not record.fields:
            report.missing.append(notice_id)
            continue
        report.labelled_notices += 1
        for name in FIELDS:
            cell = (row.get(name) or "").strip()
            if not cell:
                continue
            result = report.fields[name]
            result.notices += 1
            gold = [] if cell == NO_VALUE else _gold_values(name, cell)
            value = record.fields.get(name)
            predicted = value.values if value else []
            gold_keys = {_key(g) for g in gold}
            hits = sum(_key(p) in gold_keys for p in predicted)
            result.gold += len(gold)
            result.predicted += len(predicted)
            result.true_pos += hits
            result.empty_correct += not gold and not predicted
            if predicted:
                result.by_source[value.source][0] += hits
                result.by_source[value.source][1] += len(predicted)
    return report


def source_shares(conn: sqlite3.Connection) -> dict:
    """How the current records were filled. by_rules = share of filled fields that needed no model."""
    counts = {r["source"]: r["n"] for r in conn.execute(
        "SELECT f.source, COUNT(*) AS n FROM fields f JOIN notices n ON n.id = f.notice_id"
        " WHERE n.active = 1 AND f.value != '[]' GROUP BY f.source"
    )}
    total = conn.execute(
        "SELECT COUNT(*) FROM fields f JOIN notices n ON n.id = f.notice_id WHERE n.active = 1"
    ).fetchone()[0]
    filled = sum(counts.values())
    return {
        "fields": total,
        "filled": filled,
        "structured": counts.get("structured", 0),
        "rule": counts.get("rule", 0),
        "model": counts.get("model", 0),
        "by_rules": (counts.get("structured", 0) + counts.get("rule", 0)) / filled if filled else 0.0,
    }


def last_runs(conn: sqlite3.Connection) -> dict:
    """Latest run time per command (extract with and without the model kept apart)."""
    found = {}
    for row in conn.execute("SELECT command, seconds, details FROM runs ORDER BY id"):
        details = json.loads(row["details"])
        name = row["command"]
        if name == "extract":
            name = "extract (rules + model)" if details.get("model") else "extract --no-llm"
        found[name] = {"seconds": row["seconds"], **details}
    return found


# ----------------------------------------------------------- match scoring

@dataclass
class MatchReport:
    pairs: int = 0
    missing: list[str] = field(default_factory=list)
    level_correct: int = 0
    gold_positive: int = 0
    predicted_positive: int = 0
    true_positive: int = 0
    verdict_total: int = 0
    verdict_correct: int = 0

    @property
    def level_accuracy(self) -> float | None:
        return self.level_correct / self.pairs if self.pairs else None

    @property
    def precision(self) -> float | None:
        return self.true_positive / self.predicted_positive if self.predicted_positive else None

    @property
    def recall(self) -> float | None:
        return self.true_positive / self.gold_positive if self.gold_positive else None

    @property
    def verdict_accuracy(self) -> float | None:
        return self.verdict_correct / self.verdict_total if self.verdict_total else None


def score_matches(conn: sqlite3.Connection, cases_path: Path) -> MatchReport:
    """Check Stage 5 matching on written cases: (product, notice_id, expected level[, expected verdict])."""
    report = MatchReport()
    with cases_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for number, row in enumerate(rows, start=1):
        notice_id = (row.get("notice_id") or "").strip()
        want_level = (row.get("level") or "").strip()
        if not notice_id or not want_level:
            continue
        record = load_record(conn, notice_id)
        if record is None or not record.fields:
            report.missing.append(notice_id)
            continue
        product = MyProduct(
            row=number,
            name=(row.get("name") or "").strip(),
            brand=(row.get("brand") or "").strip(),
            ean=(row.get("ean") or "").strip(),
            batch=(row.get("batch") or "").strip(),
            best_before=(row.get("best_before") or "").strip(),
        )
        matched = match_product(product, record)
        got_level = matched.level if matched else "none"
        report.pairs += 1
        report.level_correct += got_level == want_level
        gold_pos = want_level in ("match", "possible")
        pred_pos = got_level in ("match", "possible")
        report.gold_positive += gold_pos
        report.predicted_positive += pred_pos
        report.true_positive += gold_pos and got_level == want_level
        want_verdict = (row.get("verdict") or "").strip()
        if want_verdict and matched:
            report.verdict_total += 1
            report.verdict_correct += matched.identifiers.get("verdict") == want_verdict
    return report

