"""A small local page for labelling the receipt evaluation by hand.

    python scripts/receipt_eval.py     # once, writes the two templates into data/receipt_eval/
    python scripts/label_app.py        # opens http://127.0.0.1:8777 in your browser

Two tasks, each on its own tab:
    Alerts    for every distinct (receipt line, recall) pair: is the thing you bought this recalled product?
              saved to data/receipt_eval/3_alert_pairs_labels.csv, column same_product:
              true (same product) | kind (same kind of product, other brand or shop) | false (different product) | unsure
    Phrases   for 100 receipt descriptions: write the product out in full.
              saved to data/receipt_eval/2_phrase_labels.csv, column product_phrase ("?" = you do not know)

Every click is written to the CSV file at once, so you can stop at any time and go on later. The page shows no
score and no output of the matcher unless you ask for it, so your labels are not steered by it.
`python scripts/receipt_eval.py` then reads the two label files and reports the measured numbers.

The server listens on this computer only (127.0.0.1), loads nothing from the internet and sends nothing anywhere.
The receipt lines are private: the label files stay in data/receipt_eval/, which is git-ignored.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import random
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from recall import config  # noqa: E402
from recall.textutils import one_line  # noqa: E402
from recall.web.data import _load_records, recall_view  # noqa: E402

PAGE = Path(__file__).resolve().parent / "label_app.html"
STATIC = ROOT / "recall" / "web" / "static"
PAIR_VALUES = {"true", "kind", "false", "unsure", ""}
TYPES = {".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".html": "text/html; charset=utf-8"}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _shown(path: Path) -> str:
    """A path as the page shows it: relative to the project when it lies inside it."""
    return str(path.relative_to(ROOT)) if ROOT in path.parents else str(path)


class Labels:
    """The two label files. A template gives the rows and their order; the label file holds your answers."""

    def __init__(self, out: Path, receipts_dir: Path):
        self.out = out
        self.lock = threading.Lock()
        self.pair_template = _read(out / "3_alert_pairs_template.csv")
        self.phrase_template = _read(out / "2_phrase_template.csv")
        if not self.pair_template or not self.phrase_template:
            sys.exit(f"No templates in {out}. Run `python scripts/receipt_eval.py` first.")
        self.pair_file, self.phrase_file = out / "3_alert_pairs_labels.csv", out / "2_phrase_labels.csv"
        self.pairs = {(r["description"], r["notice_id"]): (r.get("same_product") or "").strip().lower() for r in _read(self.pair_file)}
        self.phrases = {r["description"]: (r.get("product_phrase") or "").strip() for r in _read(self.phrase_file)}
        self.pair_extra = {(r["description"], r["notice_id"]): r for r in _read(self.pair_file)}
        self.bought = self._purchases(receipts_dir)
        self.recalls = self._recalls()

    @staticmethod
    def _purchases(receipts_dir: Path) -> dict[str, dict]:
        """What the receipts themselves say about a line: how often, when, at what price. Helps you remember the product."""
        found: dict[str, dict] = collections.defaultdict(lambda: {"times": 0, "dates": [], "prices": collections.Counter(), "tax": ""})
        for row in _read(receipts_dir / "items.csv"):
            if row["kind"] != "product":
                continue
            entry = found[row["description"]]
            entry["times"] += 1
            entry["dates"].append(row["receipt_id"][:10])
            price = row["price_per_kg"] or row["unit_price"]
            if price:
                entry["prices"][(f"{float(price):.2f}".replace(".", ","), "€/kg" if row["price_per_kg"] else "€")] += 1
            entry["tax"] = row["tax"]
        out = {}
        for description, entry in found.items():
            price = entry["prices"].most_common(1)[0][0] if entry["prices"] else None
            out[description] = {"times": entry["times"], "first": min(entry["dates"]), "last": max(entry["dates"]),
                                "price": f"{price[0]} {price[1]}" if price else "",
                                "vat": {"A": "7 % VAT (food)", "B": "19 % VAT"}.get(entry["tax"], "")}
        return out

    @staticmethod
    def _recalls() -> dict[str, dict]:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        found = {}
        for record in _load_records(conn):
            view = recall_view(record, detail=True)
            found[record.id] = {key: view[key] for key in (
                "title", "link", "products", "brand", "company", "reason_label", "sellers", "date_display", "batch", "best_before")}
            found[record.id]["reason_text"] = one_line(view["reason_text"], 260)  # the full text is one click away
        conn.close()
        return found

    def data(self) -> dict:
        order = list(range(len(self.pair_template)))
        random.Random(20261118).shuffle(order)  # not by score, so the order tells you nothing about the answer
        pairs = []
        for index in order:
            row = self.pair_template[index]
            key = (row["description"], row["notice_id"])
            pairs.append({"description": row["description"], "notice_id": row["notice_id"], "label": self.pairs.get(key, ""),
                          "matched_as": row["matched_as"], "score": row["score"], "alerts": row["alerts"],
                          "bought": self.bought.get(row["description"], {}), "recall": self.recalls.get(row["notice_id"], {})})
        phrases = [{"description": row["description"], "label": self.phrases.get(row["description"], ""),
                    "bought": self.bought.get(row["description"], {})} for row in self.phrase_template]
        return {"pairs": pairs, "phrases": phrases,
                "files": {"pairs": _shown(self.pair_file), "phrases": _shown(self.phrase_file)}}

    def set_pair(self, description: str, notice_id: str, value: str) -> None:
        if value not in PAIR_VALUES:
            raise ValueError(f"unknown label {value!r}")
        with self.lock:
            self.pairs[(description, notice_id)] = value
            rows = [{**row, "same_product": self.pairs.get((row["description"], row["notice_id"]), "")} for row in self.pair_template]
            in_template = {(row["description"], row["notice_id"]) for row in self.pair_template}
            # labels for pairs that are no longer alerts are kept at the end, never thrown away
            rows += [{**self.pair_extra[key], "same_product": value_} for key, value_ in self.pairs.items()
                     if key not in in_template and value_ and key in self.pair_extra]
            self._write(self.pair_file, list(self.pair_template[0].keys()), rows)

    def set_phrase(self, description: str, value: str) -> None:
        with self.lock:
            self.phrases[description] = value.strip()
            rows = [{**row, "product_phrase": self.phrases.get(row["description"], "")} for row in self.phrase_template]
            self._write(self.phrase_file, list(self.phrase_template[0].keys()), rows)

    @staticmethod
    def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
        temporary = path.with_suffix(".csv.tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)


def handler(labels: Labels):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                return self._send(200, PAGE.read_bytes(), TYPES[".html"])
            if path == "/api/data":
                return self._send(200, json.dumps(labels.data(), ensure_ascii=False).encode("utf-8"), "application/json")
            if path.startswith("/static/"):
                target = (STATIC / path[len("/static/"):]).resolve()
                if STATIC in target.parents and target.is_file() and target.suffix in TYPES:
                    return self._send(200, target.read_bytes(), TYPES[target.suffix])
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            origin = self.headers.get("Origin")
            if origin and origin.split("//")[-1] != self.headers.get("Host"):
                return self._send(403, b"other origin", "text/plain")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                if self.path == "/api/pair":
                    labels.set_pair(body["description"], body["notice_id"], body["label"])
                elif self.path == "/api/phrase":
                    labels.set_phrase(body["description"], body["label"])
                else:
                    return self._send(404, b"not found", "text/plain")
            except (KeyError, ValueError) as error:
                return self._send(400, str(error).encode("utf-8"), "text/plain")
            self._send(200, b'{"saved":true}', "application/json")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--receipts", default=str(Path.home() / "receipts-lidl"))
    parser.add_argument("--out", default=str(config.DATA / "receipt_eval"))
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    labels = Labels(Path(args.out), Path(args.receipts))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(labels))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Labelling page: {url}   (stop with Ctrl+C; every answer is saved at once)")
    if not args.no_open:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Your labels are in", labels.out)


if __name__ == "__main__":
    main()
