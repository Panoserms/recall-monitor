"""Evaluate receipt reading and receipt matching. Four numbers, kept apart, never merged.

    python scripts/receipt_eval.py [--receipts ~/receipts-lidl] [--out data/receipt_eval]

    1  Line extraction (REAL): every receipt in <receipts>/clean/*.txt is parsed and compared with the
       reference parse in <receipts>/items.csv, line by line; share of receipts whose lines add up to
       the printed total. Every mismatch is listed.
    2  Description -> product phrase (REAL, needs your labels): 100 distinct descriptions, drawn with a
       fixed seed and never used to build the abbreviation lexicon. The script writes the template
       2_phrase_template.csv (no system output in it). Write the phrases with
       `python scripts/label_app.py` (it saves 2_phrase_labels.csv) and run again. Without labels the
       number is reported as "not measured".
    3  False alerts (REAL, the headline): all receipts against all current recalls. Alerts per 100
       receipts for name-only matching, with retailer narrowing, with date narrowing, and with both,
       at three alert thresholds. 3_alert_pairs_template.csv lists every distinct (receipt line,
       recall) pair. Answer them with `python scripts/label_app.py` (true = same product, kind = same
       kind of product but another brand or shop, false = different product, unsure), which writes
       3_alert_pairs_labels.csv; then run this script again.
    4  Detection (SYNTHETIC): receipt-style lines made by rule from the recalled products themselves
       (receipt.synthetic_line). Shows that the matcher can find a recalled item, not how it does on
       real purchases. Optimistic, because the lines are built from the very names they must match.

The receipt archive is private and stays outside this repository; so do all files this script writes
(data/receipt_eval/ is git-ignored). Nothing is sent anywhere.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recall import config, receipt  # noqa: E402
from recall.normalise import tokens  # noqa: E402
from recall.web.data import _load_records  # noqa: E402

THRESHOLDS = (65.0, 74.0, 80.0)  # 65 = the product-list matcher's "possible", 74 = adopted for receipts, 80 = its "match"
STORE = "Lidl"  # the archive holds Lidl receipts only


def _answer(cell: str) -> str:
    """true | kind | false | unsure, as scripts/label_app.py writes them (yes/no and ja/nein are read too)."""
    cell = cell.strip().lower()
    if cell in {"true", "yes", "y", "1", "ja", "wahr"}:
        return "true"
    if cell in {"false", "no", "n", "nein", "falsch"}:
        return "false"
    return cell if cell in {"kind", "unsure"} else "unsure"


def _float(cell: str) -> float | None:
    return None if cell in ("", None) else float(cell)


def _records() -> list:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return _load_records(conn)


def seen_before_split(counts: collections.Counter) -> set[str]:
    """Descriptions that were printed on screen while the data was first looked at, before the evaluation
    sample was drawn (reproduced here with the same code). Reported apart so the sample stays honest."""
    random.seed(1)
    first = set(random.sample(sorted(counts), 70))
    return first | set([d for d in counts if re.search(r"[A-Za-zäöü]\.", d)][:60])


# ---------------------------------------------------------------- 1 extraction

def extraction(receipts_dir: Path, out: Path) -> tuple[dict, dict[str, dict]]:
    reference: dict[str, list[dict]] = collections.defaultdict(list)
    with (receipts_dir / "items.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            reference[row["receipt_id"]].append(row)
    parsed: dict[str, dict] = {}
    mismatches = []
    sums_ok = stores = unparsed = lines = 0
    for path in sorted((receipts_dir / "clean").glob("*.txt")):
        receipt_id = path.stem
        result = receipt.parse(path.read_text(encoding="utf-8"))
        parsed[receipt_id] = result
        sums_ok += result["sums_match"] is True
        stores += result["store"] == STORE
        unparsed += len(result["unparsed"])
        lines += len(result["items"])
        mine = [(i["kind"], i["description"], i["quantity"], i["unit_price"], i["weight_kg"], i["price_per_kg"],
                 i["line_total"], i["tax"], i["discount"], "; ".join(i["discount_names"])) for i in result["items"]]
        theirs = [(r["kind"], r["description"], int(r["quantity"]), _float(r["unit_price"]), _float(r["weight_kg"]),
                   _float(r["price_per_kg"]), _float(r["line_total"]), r["tax"], _float(r["discount"]), r["discount_names"])
                  for r in reference[receipt_id]]
        if mine != theirs:
            differing = next(((a, b) for a, b in zip(mine, theirs) if a != b), (len(mine), len(theirs)))
            mismatches.append({"receipt_id": receipt_id, "first_difference": repr(differing)})
        if result["sums_match"] is not True:
            mismatches.append({"receipt_id": receipt_id, "first_difference": f"items add up to {result['items_sum']}, printed total {result['total']}"})
        for line in result["unparsed"]:
            mismatches.append({"receipt_id": receipt_id, "first_difference": f"line not understood: {line}"})
    _write(out / "1_extraction_mismatches.csv", ["receipt_id", "first_difference"], mismatches)
    count = len(parsed)
    return {
        "receipts": count, "lines": lines, "sums_match": sums_ok, "equal_to_reference": count - len({m["receipt_id"] for m in mismatches}),
        "unparsed_lines": unparsed, "store_read_from_text": stores, "date_read_from_text": sum(bool(p["date"]) for p in parsed.values()),
        "mismatches": len(mismatches),
    }, parsed


# -------------------------------------------------------------------- 2 phrase

def phrases(counts: collections.Counter, out: Path) -> dict:
    sample = receipt.eval_sample(sorted(counts))
    seen = seen_before_split(counts)
    template = out / "2_phrase_template.csv"
    _write(template, ["description", "times_bought", "seen_before_split", "product_phrase"],
           [{"description": d, "times_bought": counts[d], "seen_before_split": "yes" if d in seen else "", "product_phrase": ""} for d in sample])
    result = {"sample": len(sample), "seen_before_split": sum(d in seen for d in sample),
              "changed_by_lexicon": sum(receipt.phrase(d)["changed"] for d in sample),
              "still_abbreviated": sum(bool(receipt.phrase(d)["open"]) for d in sample), "measured": False}
    labels = out / "2_phrase_labels.csv"
    if not labels.exists():
        return result
    with labels.open(encoding="utf-8-sig", newline="") as handle:
        answered = [r for r in csv.DictReader(handle) if (r.get("product_phrase") or "").strip()]
    rows = [r for r in answered if r["product_phrase"].strip() != "?"]  # "?" = you could not tell what the product was
    result["could_not_tell"] = len(answered) - len(rows)
    failures, exact, overlap = [], 0, []
    for row in rows:
        want, got = tokens(row["product_phrase"]), tokens(receipt.phrase(row["description"])["text"])
        shared = sum(min(want.count(w), got.count(w)) for w in set(want))
        f1 = 2 * shared / (len(want) + len(got)) if want and got else 0.0
        overlap.append(f1)
        exact += want == got
        if want != got:
            failures.append({"description": row["description"], "your_phrase": row["product_phrase"],
                             "rule_phrase": receipt.phrase(row["description"])["text"], "word_f1": round(f1, 2)})
    _write(out / "2_phrase_failures.csv", ["description", "your_phrase", "rule_phrase", "word_f1"], failures)
    held_out = [r for r in rows if r["description"] not in seen]
    result.update(measured=True, labelled=len(rows), exact=exact, word_f1=round(sum(overlap) / len(overlap), 3) if overlap else None,
                  exact_never_seen=sum(tokens(r["product_phrase"]) == tokens(receipt.phrase(r["description"])["text"]) for r in held_out),
                  labelled_never_seen=len(held_out))
    return result


# --------------------------------------------------------------------- 3 alerts

def alerts(parsed: dict[str, dict], records: list, out: Path) -> dict:
    by_id = {r.id: r for r in records}
    cache: dict[str, list[dict]] = {}
    rows = []
    for receipt_id, result in parsed.items():
        bought = receipt_id[:10]
        for item in result["items"]:
            if item["kind"] != "product" or item["nonfood"]:
                continue
            description = item["description"]
            if description not in cache:
                cache[description] = [hit for r in records if (hit := receipt.match_line(description, r, minimum=min(THRESHOLDS)))]
            for hit in cache[description]:
                reasons = receipt.narrow(by_id[hit["notice_id"]], STORE, bought)
                rows.append({
                    "receipt_id": receipt_id, "bought": bought, "line_no": item["line_no"], "description": description,
                    "matched_as": hit["matched_as"], "notice_id": hit["notice_id"], "recall_name": hit["recall_name"],
                    "score": hit["score"], "basis": hit["basis"],
                    "other_shops_only": any(r.startswith("the notice names other shops") for r in reasons),
                    "dates_rule_it_out": any(not r.startswith("the notice names other shops") for r in reasons),
                })
    _write(out / "3_alerts.csv", list(rows[0].keys()) if rows else ["receipt_id"], rows)

    pairs: dict[tuple, dict] = {}
    for row in rows:
        pair = pairs.setdefault((row["description"], row["notice_id"]), {
            "description": row["description"], "matched_as": row["matched_as"], "notice_id": row["notice_id"],
            "recall_name": row["recall_name"], "score": row["score"], "alerts": 0, "alerts_after_narrowing": 0, "same_product": ""})
        pair["alerts"] += 1
        pair["alerts_after_narrowing"] += not (row["other_shops_only"] or row["dates_rule_it_out"])
    ordered = sorted(pairs.values(), key=lambda p: (-p["score"], p["description"], p["notice_id"]))
    _write(out / "3_alert_pairs_template.csv", list(ordered[0].keys()) if ordered else ["description"], ordered)

    receipts = len(parsed)
    table = {}
    for threshold in THRESHOLDS:
        hits = [r for r in rows if r["score"] >= threshold]
        variants = {
            "name only": hits,
            "with retailer": [r for r in hits if not r["other_shops_only"]],
            "with date": [r for r in hits if not r["dates_rule_it_out"]],
            "with both": [r for r in hits if not (r["other_shops_only"] or r["dates_rule_it_out"])],
        }
        table[str(threshold)] = {name: {"alerts": len(v), "receipts_with_alert": len({r["receipt_id"] for r in v}),
                                        "per_100_receipts": round(100 * len(v) / receipts, 1)} for name, v in variants.items()}
    result = {"receipts": receipts, "product_lines": sum(1 for p in parsed.values() for i in p["items"] if i["kind"] == "product"),
              "nonfood_lines_skipped": sum(1 for p in parsed.values() for i in p["items"] if i["kind"] == "product" and i["nonfood"]),
              "recalls": len(records), "distinct_pairs": len(pairs), "by_threshold": table, "labelled": False}

    labels = out / "3_alert_pairs_labels.csv"
    if labels.exists():
        with labels.open(encoding="utf-8-sig", newline="") as handle:
            marked = {(r["description"], r["notice_id"]): _answer(r["same_product"]) for r in csv.DictReader(handle)
                      if (r.get("same_product") or "").strip()}
        judged_table = {}
        for threshold in THRESHOLDS:
            for name, keep in (("name only", lambda r: True), ("with both", lambda r: not (r["other_shops_only"] or r["dates_rule_it_out"]))):
                hits = [r for r in rows if r["score"] >= threshold and keep(r)]
                counts = collections.Counter(marked.get((r["description"], r["notice_id"]), "no answer") for r in hits)
                wrong = counts["kind"] + counts["false"]
                judged_table[f"{threshold} {name}"] = {
                    "alerts": len(hits), "same_product": counts["true"], "same_kind_other_brand_or_shop": counts["kind"],
                    "different_product": counts["false"], "unsure": counts["unsure"], "no_answer": counts["no answer"],
                    "false_alerts_per_100_receipts": round(100 * wrong / receipts, 1),
                    "different_product_per_100_receipts": round(100 * counts["false"] / receipts, 1)}
        result.update(labelled=True, labelled_pairs=len(marked), pairs_without_answer=sum(1 for key in pairs if key not in marked),
                      judged=judged_table)
    return result


# ----------------------------------------------------------------- 4 synthetic

def synthetic(records: list, out: Path) -> dict:
    rows = []
    for record in records:
        for name in record.values("product_name")[:1] or [record.title]:
            line = receipt.synthetic_line(record, name)
            if len(tokens(line)) == 0:
                continue
            sellers = record.values("sellers")
            hits = [hit for r in records if (hit := receipt.match_line(line, r, sellers[0] if sellers else STORE, "", minimum=min(THRESHOLDS)))]
            own = next((h for h in hits if h["notice_id"] == record.id), None)
            rows.append({"SYNTHETIC_line": line, "made_from": name, "notice_id": record.id, "score": own["score"] if own else "",
                         "other_recalls_alerting_at_74": sum(1 for h in hits if h["notice_id"] != record.id and h["score"] >= 74.0),
                         "abbreviated": "." in line or len(line) >= receipt.CUT_AT})
    _write(out / "4_SYNTHETIC_detection.csv", list(rows[0].keys()), rows)
    result = {"SYNTHETIC": True, "lines": len(rows), "abbreviated_or_cut": sum(r["abbreviated"] for r in rows)}
    for threshold in THRESHOLDS:
        found = [r for r in rows if r["score"] != "" and r["score"] >= threshold]
        result[f"found_at_{threshold}"] = len(found)
        cut = [r for r in rows if r["abbreviated"]]
        result[f"found_at_{threshold}_abbreviated_or_cut"] = sum(1 for r in cut if r["score"] != "" and r["score"] >= threshold)
    return result


# ------------------------------------------------------------------------ main

def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--receipts", default=str(Path.home() / "receipts-lidl"), help="folder with clean/*.txt and items.csv")
    parser.add_argument("--out", default=str(config.DATA / "receipt_eval"))
    args = parser.parse_args()
    receipts_dir, out = Path(args.receipts), Path(args.out)
    if not (receipts_dir / "clean").is_dir():
        sys.exit(f"No receipts in {receipts_dir}/clean. The archive is private and not part of this repository.")
    started = time.perf_counter()
    records = _records()

    one, parsed = extraction(receipts_dir, out)
    counts = collections.Counter(i["description"] for p in parsed.values() for i in p["items"] if i["kind"] == "product")
    two = phrases(counts, out)
    three = alerts(parsed, records, out)
    four = synthetic(records, out)
    report = {"1_extraction_REAL": one, "2_phrase_REAL": two, "3_alerts_REAL": three, "4_detection_SYNTHETIC": four,
              "adopted_threshold": receipt.POSSIBLE, "seconds": round(time.perf_counter() - started, 1)}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"1 LINE EXTRACTION (real, {one['receipts']} Lidl receipts, {one['lines']} lines)")
    print(f"    items add up to the printed total: {one['sums_match']}/{one['receipts']}")
    print(f"    equal to the reference parse (items.csv): {one['equal_to_reference']}/{one['receipts']}; lines not understood: {one['unparsed_lines']}")
    print(f"    shop read from the receipt text: {one['store_read_from_text']}/{one['receipts']}; purchase date read from the text: "
          f"{one['date_read_from_text']}/{one['receipts']} (the archive's texts are cut off before the date line)")
    print(f"    mismatches listed in {out.name}/1_extraction_mismatches.csv: {one['mismatches']}")
    print(f"\n2 DESCRIPTION -> PRODUCT PHRASE (real, {two['sample']} held-out descriptions, {two['seen_before_split']} of them seen before the split)")
    if two["measured"]:
        print(f"    {two['could_not_tell']} marked as unknown and left out; exact (same words): {two['exact']}/{two['labelled']}; mean word F1 {two['word_f1']}; "
              f"never-seen only: {two['exact_never_seen']}/{two['labelled_never_seen']}; failures in 2_phrase_failures.csv")
    else:
        print(f"    NOT MEASURED: no labels yet. Write them with `python scripts/label_app.py` (or fill product_phrase in "
              f"{out.name}/2_phrase_template.csv and save it as 2_phrase_labels.csv).")
    print(f"    (the lexicon changes {two['changed_by_lexicon']} of the {two['sample']}; {two['still_abbreviated']} keep an abbreviated or cut-off word)")
    print(f"\n3 FALSE ALERTS (real, {three['receipts']} receipts, {three['product_lines']} product lines, {three['nonfood_lines_skipped']} "
          f"non-food lines skipped, {three['recalls']} recalls)")
    print("    alerts per 100 receipts (alerts / receipts with at least one):")
    print(f"    {'score from':<12}{'name only':>20}{'with retailer':>20}{'with date':>20}{'with both':>20}")
    for threshold, variants in three["by_threshold"].items():
        cells = "".join(f"{v['per_100_receipts']:>9} ({v['alerts']}/{v['receipts_with_alert']})".rjust(20) for v in variants.values())
        print(f"    {threshold:<12}{cells}" + ("   <- adopted" if float(threshold) == receipt.POSSIBLE else ""))
    if three["labelled"]:
        print(f"    your answers ({three['labelled_pairs']} pairs answered, {three['pairs_without_answer']} of the current pairs without an answer):")
        for name, j in three["judged"].items():
            print(f"    from {name}: {j['alerts']} alerts = {j['same_product']} same product, {j['same_kind_other_brand_or_shop']} same kind but other "
                  f"brand or shop, {j['different_product']} different product, {j['unsure']} unsure, {j['no_answer']} no answer"
                  f" -> {j['false_alerts_per_100_receipts']} false alerts per 100 receipts ({j['different_product_per_100_receipts']} of them a different product)")
    else:
        print(f"    Whether an alert is right is NOT MEASURED: answer the {three['distinct_pairs']} distinct pairs with `python scripts/label_app.py` "
              f"(or fill same_product in {out.name}/3_alert_pairs_template.csv and save it as 3_alert_pairs_labels.csv).")
    print(f"\n4 DETECTION (SYNTHETIC lines made by rule from the {four['lines']} recalled products; optimistic)")
    for threshold in THRESHOLDS:
        print(f"    found from score {threshold}: {four[f'found_at_{threshold}']}/{four['lines']}"
              f"   (abbreviated or cut-off lines only: {four[f'found_at_{threshold}_abbreviated_or_cut']}/{four['abbreviated_or_cut']})")
    print(f"\nSaved {out}/report.json ({report['seconds']} s)")


if __name__ == "__main__":
    main()
