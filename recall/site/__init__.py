"""The public website: static pages, rebuilt from the database (`recall build-site`).

Everything a visitor sees is the same for everyone, so the site is plain files (GitHub Pages).
A visitor's product list is kept in their own browser (localStorage) and matched there by
static/match.js, a port of recall/match.py; nothing about the visitor reaches a server.

Every recall page shows the official notice in full and unchanged (the portal's terms ask
that republished notices are complete and unchanged), next to the fields read from it, with
a link to the original. Notices the portal removes are left out of the next build.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import parse, retailers
from ..models import FieldValue, Record
from ..normalise import FILLER, _brand_aliases, _food_words
from ..textutils import one_line
from ..web.data import FILTERS, STATE_SHORT, _load_records, recall_view

_HERE = Path(__file__).resolve().parent
_WEB_STATIC = _HERE.parent / "web" / "static"


def _rules_only(record: Record) -> Record:
    """The public site uses rules only: drop values filled by the local language model."""
    fields = {name: (FieldValue.empty() if fv.source == "model" else fv) for name, fv in record.fields.items()}
    return record.model_copy(update={"fields": fields})


def lexicon_json() -> dict:
    """What match.js and receipt.js need to work exactly like the Python code: compounds, brand spellings,
    shop names (to read the shop from a receipt) and receipt abbreviations."""
    from .. import lexicons
    from ..receipt import _abbreviations

    return {
        "food_words": sorted(_food_words()),
        "brand_aliases": _brand_aliases(),
        "filler": sorted(FILLER),
        "retailers": [list(row[:3]) for row in lexicons.load("retailers.tsv")],
        "receipt_abbrev": _abbreviations(),
        "shop_styles": retailers.browser_json(),
    }


def record_json(record: Record) -> dict:
    """One recall for the browser: the fields match.js compares, plus what an alert shows."""
    view = recall_view(record, detail=True)
    return {
        "id": record.id,
        "title": record.title,
        "link": record.link,
        "product_name": record.values("product_name"),
        "brand": record.values("brand"),
        "manufacturer": record.values("manufacturer"),
        "batch": record.values("batch"),
        "best_before": record.values("best_before"),
        "ean": record.extras.get("ean") if isinstance(record.extras.get("ean"), list) else [],
        "sellers": record.values("sellers"),
        "date": (record.values("date") or [""])[0],
        "first_published": str(record.extras.get("first_published") or ""),
        "reason_label": view["reason_label"],
        "is_pathogen": view["is_pathogen"],
        "reason_text": one_line(view["reason_text"], 220),
        "what_to_do": one_line(view["what_to_do"], 320),
        "date_display": view["date_display"],
    }


def example_receipt(records: list[Record]) -> str:
    """A MADE-UP receipt in the layout of a Lidl digital receipt, for the "Try a made-up example" button.

    Not a real receipt: three lines are written by rule from current recalls (receipt.synthetic_line: one recall
    that names Lidl or no shop, one that names no shop, one that names other shops only, so the page can show a
    match and a less likely match), the other lines and all prices are invented. The text says so in its first line."""
    from datetime import date, timedelta

    from .. import receipt

    def line_for(record: Record) -> str | None:
        names = record.values("product_name")
        text = receipt.synthetic_line(record, names[0]) if names else ""
        return text if text and receipt.match_line(text, record) else None

    def first(wanted) -> tuple[Record, str] | None:
        return next(((r, line) for r in records if wanted(r) and r not in [p[0] for p in picks] and (line := line_for(r))), None)

    picks: list[tuple[Record, str]] = []
    for wanted in (
        lambda r: any(receipt.same_shop("Lidl", s) for s in r.values("sellers")),
        lambda r: not r.values("sellers"),
        lambda r: r.values("sellers") and not any(receipt.same_shop("Lidl", s) for s in r.values("sellers")),
    ):
        if found := first(wanted):
            picks.append(found)
    ordinary = [text for text in ("Bananen kg", "Vollmilch 3,5%", "Zwiebeln rot", "Eier 10er", "Haferflocken")
                if not any(receipt.match_line(text, r) for r in records)][:3]
    published = [str(r.extras.get("first_published") or (r.values("date") or [""])[0]) for r, _ in picks]
    days = [date.fromisoformat(d) for d in published if len(d) == 10]
    bought = (min(days) if days else date(2026, 1, 15)) - timedelta(days=2)

    prices = [129, 249, 99, 179, 219, 89]
    rows = [f"{text:<34}{f'{price / 100:.2f}'.replace('.', ','):>5} A" for text, price in zip([line for _, line in picks] + ordinary, prices)]
    rows.insert(1, "     Lidl Plus Rabatt             -0,10")
    total = sum(prices[: len(picks) + len(ordinary)]) - 10
    money = f"{total / 100:.2f}".replace(".", ",")
    return "\n".join([
        "*** MADE-UP EXAMPLE, NOT A REAL RECEIPT ***",
        "          Beispielstraße 1",
        "          12345 Beispielstadt",
        "                                    EUR",
        *rows,
        "------------------------------------------",
        f"zu zahlen{money:>30}",
        f"Karte{money:>34}",
        "",
        f"{bought:%d.%m.%Y}   10:15   (made-up example)",
        "",
    ])


def official_text(conn: sqlite3.Connection, notice_id: str, raw_dir: Path) -> list[tuple[str, str]]:
    """The notice as the portal shows it: from the newest saved page, or from the feed item."""
    row = conn.execute(
        "SELECT p.path FROM pages p WHERE p.notice_id = ? ORDER BY p.version DESC LIMIT 1", (notice_id,)
    ).fetchone()
    if row and (raw_dir / "pages" / row["path"]).exists():
        return parse.page_pairs((raw_dir / "pages" / row["path"]).read_bytes())
    item = conn.execute("SELECT feed_item FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return parse.feed_pairs(item["feed_item"]) if item else []


def _environment() -> Environment:
    return Environment(loader=FileSystemLoader(_HERE / "templates"), autoescape=select_autoescape(["html"]))


class NotReady(Exception):
    """The site may not be published yet (e.g. the Impressum is missing)."""


def load_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def check_public(settings: dict) -> None:
    impressum = settings.get("impressum") or {}
    if not (impressum.get("name") and impressum.get("address")):
        raise NotReady("site.json has no Impressum (name and address); a public German website needs one")


def build(conn: sqlite3.Connection, raw_dir: Path, out: Path, *, settings: dict | None = None, public: bool = False) -> dict:
    """Write the whole site into `out` (emptied first). Returns counts for the command line.
    `public`: refuse to build without the details a public site needs."""
    settings = settings or {}
    if public:
        check_public(settings)
    records = [_rules_only(r) for r in _load_records(conn)]
    if out.exists():
        shutil.rmtree(out)
    (out / "recall").mkdir(parents=True)
    (out / "static").mkdir()
    (out / "data").mkdir()

    for name in ("style.css", "fonts.css"):
        shutil.copyfile(_WEB_STATIC / name, out / "static" / name)
    shutil.copytree(_WEB_STATIC / "fonts", out / "static" / "fonts")
    for path in (_HERE / "static").iterdir():
        if path.is_dir():  # vendor/ (pdf.js, Tesseract.js) and media/ (the story video), served from this site
            shutil.copytree(path, out / "static" / path.name)
        else:
            shutil.copyfile(path, out / "static" / path.name)
    (out / "static" / "shops.css").write_text(retailers.stylesheet(), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    (out / "data" / "recalls.json").write_text(
        json.dumps({"recalls": [record_json(r) for r in records]}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (out / "data" / "lexicon.json").write_text(json.dumps(lexicon_json(), ensure_ascii=False), encoding="utf-8")
    (out / "data" / "example_receipt.txt").write_text(example_receipt(records), encoding="utf-8")

    built = datetime.now(timezone.utc)
    common = {
        "built": built.astimezone().strftime("%d.%m.%Y, %H:%M"),
        "built_iso": built.isoformat(timespec="minutes"),
        "count": len(records),
        "impressum": settings.get("impressum") or {},
        "repo_url": settings.get("repo_url", ""),
    }
    env = _environment()
    views = [{**recall_view(r), "shops": retailers.shops(r.values("sellers"))} for r in records]
    states = sorted({s for r in records for s in r.values("states")}, key=lambda s: s)
    pages = {
        "index.html": env.get_template("index.html").render(root="", recalls=views, filters=FILTERS, states=states,
                                                            state_short=STATE_SHORT, page="recalls", **common),
        "receipt.html": env.get_template("receipt.html").render(root="", page="receipt", **common),
        "products.html": env.get_template("products.html").render(root="", page="products", **common),
        "about.html": env.get_template("about.html").render(root="", page="about", **common),
        # GitHub Pages serves 404.html at any depth, so its links need the site's absolute base path
        "404.html": env.get_template("404.html").render(root=settings.get("base_path", "/"), page="", **common),
    }
    recall_template = env.get_template("recall.html")
    for record in records:
        view = {**recall_view(record, detail=True), "shops": retailers.shops(record.values("sellers"))}
        pages[f"recall/{record.id}.html"] = recall_template.render(
            root="../", recall=view, official=official_text(conn, record.id, raw_dir), page="recall", **common
        )
    for name, html in pages.items():
        (out / name).write_text(html, encoding="utf-8")
    return {"recalls": len(records), "pages": len(pages)}
