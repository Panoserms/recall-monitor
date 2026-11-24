"""Stage 7: the gold template and the scores against hand labels."""
import csv

import pytest
from test_alert import _store
from test_match import SPINACH, record

from recall import evaluate
from recall.models import FIELDS


def _records(conn, n):
    for i in range(n):
        _store(conn, record(f"Produkt {i}", notice_id=f"n{i:03d}"))


def test_template_has_the_sample_and_empty_label_columns(conn, tmp_path):
    _records(conn, 30)
    path = tmp_path / "gold_template.csv"
    evaluate.make_template(conn, path, size=10)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 10
    assert all(row[field] == "" for row in rows for field in FIELDS)
    assert {"notice_id", "link", "title"} <= set(rows[0])


def test_template_sample_is_the_same_every_time(conn, tmp_path):
    _records(conn, 30)
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    evaluate.make_template(conn, first, size=10)
    evaluate.make_template(conn, second, size=10)
    assert first.read_text() == second.read_text()


def test_template_never_overwrites_hand_labels(conn, tmp_path):
    _records(conn, 3)
    gold = tmp_path / "gold.csv"
    with pytest.raises(ValueError, match="gold"):
        evaluate.make_template(conn, gold, size=3)


def _gold(tmp_path, rows):
    path = tmp_path / "gold.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["notice_id", *FIELDS])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def test_scores_count_values_and_skip_unlabelled_cells(conn, tmp_path):
    _store(conn, SPINACH)  # batch L5435 DD, best before 2027-10, brand K-Classic
    gold = _gold(tmp_path, [{
        "notice_id": SPINACH.id,
        "batch": "L5435 DD | L5436 DD",  # one found, one missed
        "best_before": "2027-10",
        "brand": "Lidl",  # wrong prediction
        "sellers": "-",  # labelled: the notice names no seller (prediction is empty, so correct)
        "manufacturer": "",  # not labelled: skipped
    }])
    report = evaluate.score(conn, gold)
    batch = report.fields["batch"]
    assert (batch.true_pos, batch.predicted, batch.gold) == (1, 1, 2)
    assert batch.precision == 1.0 and batch.recall == 0.5
    assert report.fields["best_before"].precision == 1.0
    assert report.fields["brand"].precision == 0.0
    assert report.fields["sellers"].notices == 1 and report.fields["sellers"].empty_correct == 1
    assert report.fields["manufacturer"].notices == 0


def test_values_are_compared_after_folding_case_and_spaces(conn, tmp_path):
    _store(conn, SPINACH)
    gold = _gold(tmp_path, [{"notice_id": SPINACH.id, "batch": "l5435dd", "brand": "k-classic"}])
    report = evaluate.score(conn, gold)
    assert report.fields["batch"].precision == 1.0
    assert report.fields["brand"].precision == 1.0


def test_share_of_fields_by_source(conn):
    _store(conn, SPINACH)
    shares = evaluate.source_shares(conn)
    assert shares["filled"] == sum(1 for f in SPINACH.fields.values() if f.values)
    assert shares["by_rules"] == 1.0  # nothing came from the model


def test_score_matches_evaluates_levels_and_verdicts(conn, tmp_path):
    _store(conn, SPINACH)  # K-Classic Spinat gehackt, batch L5435 DD, best_before 2027-10
    match_gold = tmp_path / "match_gold.csv"
    with match_gold.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["name", "brand", "ean", "batch", "best_before", "notice_id", "level", "verdict"]
        )
        writer.writeheader()
        writer.writerows([
            {
                "name": "Spinat gehackt",
                "brand": "K-Classic",
                "batch": "L5435 DD",
                "best_before": "10/2027",
                "notice_id": SPINACH.id,
                "level": "match",
                "verdict": "affected",
            },
            {
                "name": "Spinat gehackt",
                "brand": "K-Classic",
                "batch": "OTHER99",
                "best_before": "10/2028",
                "notice_id": SPINACH.id,
                "level": "match",
                "verdict": "not_affected",
            },
            {
                "name": "Spinat gehackt",
                "brand": "Iglo",
                "notice_id": SPINACH.id,
                "level": "none",
                "verdict": "",
            },
        ])
    report = evaluate.score_matches(conn, match_gold)
    assert (report.pairs, report.level_correct, report.level_accuracy) == (3, 3, 1.0)
    assert (report.precision, report.recall) == (1.0, 1.0)
    assert (report.verdict_total, report.verdict_correct, report.verdict_accuracy) == (2, 2, 1.0)

