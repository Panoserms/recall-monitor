"""Propose entries for recall/lexicons/receipt_abbrev.tsv from real receipt descriptions.

    python scripts/receipt_abbrev_candidates.py [--receipts ~/receipts-lidl] [--min-count 1]

Reads items.csv of the private receipt archive (never copied into this repository) and prints, for every
token that ends in a full stop ("Vollk.", "Jogh."), the full words that start with it:
words written out in other receipt descriptions, in the food lexicon, or in recall product names.
The output is a list of proposals; the lexicon itself is written and checked by hand.

The 100 descriptions drawn for the hand-labelled evaluation (scripts/receipt_eval.py, same seed)
are left out, so the lexicon is never built from descriptions it is later scored on.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recall import lexicons, receipt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", default=str(Path.home() / "receipts-lidl"))
    parser.add_argument("--min-count", type=int, default=1)
    args = parser.parse_args()
    with (Path(args.receipts) / "items.csv").open(encoding="utf-8", newline="") as handle:
        counts = collections.Counter(r["description"] for r in csv.DictReader(handle) if r["kind"] == "product")
    held_out = set(receipt.eval_sample(sorted(counts)))
    rest = {d: n for d, n in counts.items() if d not in held_out}

    full: collections.Counter = collections.Counter()
    short: collections.Counter = collections.Counter()
    for description, n in rest.items():
        words = receipt.words(description)
        for index, (word, cut) in enumerate(words):
            if cut == "dot":
                short[word.lower()] += n
            elif not (index == len(words) - 1 and len(description) >= receipt.CUT_AT - 1) and len(word) >= 4:
                full[word.lower()] += n
    for row in lexicons.load("food_words.tsv"):
        full[row[0]] += 1
    known = {row[0] for row in lexicons.load("receipt_abbrev.tsv")}
    for abbreviation, n in short.most_common():
        if n < args.min_count:
            break
        found = [(w, c) for w, c in full.most_common() if w.startswith(abbreviation) and len(w) > len(abbreviation)]
        mark = "=" if abbreviation in known else "?"
        examples = [d for d in rest if abbreviation in [w.lower() for w, cut in receipt.words(d) if cut == "dot"]][:3]
        print(f"{mark} {abbreviation}.\t{n}\t{', '.join(f'{w} ({c})' for w, c in found[:5])}\t{' | '.join(examples)}")


if __name__ == "__main__":
    main()
