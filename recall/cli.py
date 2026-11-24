"""Command line: recall fetch | extract | match | alert | eval."""
from __future__ import annotations

import typer

from . import config, db

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="German food recall notices -> structured records -> alerts for your own products.",
)


@app.callback()
def main():
    """German food recall notices -> structured records -> alerts for your own products."""


def _connect():
    return db.connect(config.DB_PATH)


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return f"{seconds:.0f} s"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


@app.command()
def fetch(
    feed_only: bool = typer.Option(False, "--feed-only", help="Only the feed (one request), no notice pages."),
    max_pages: int = typer.Option(None, "--max-pages", help="Fetch at most this many notice pages in this run."),
):
    """Download new notices. Raw responses go unchanged to data/raw/, nothing is fetched twice."""
    from .fetch import FetchError, PoliteClient, _missing_pages, fetch_feed, fetch_pages

    conn = _connect()
    client = PoliteClient(conn)
    try:
        feed = fetch_feed(conn, client, config.RAW)
    except FetchError as error:
        typer.secho(f"Feed: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    how = "downloaded" if feed.downloaded else "less than an hour old, not downloaded again"
    typer.echo(
        f"Feed: {feed.total} food notices ({feed.new} new, {feed.updated} updated, {feed.removed} gone)"
        f" - {how}: {feed.path.relative_to(config.ROOT)}"
    )
    if feed_only:
        return

    waiting = len(_missing_pages(conn))
    planned = waiting if max_pages is None else min(max_pages, waiting)
    if planned:
        typer.echo(
            f"Pages: {planned} to fetch, one every {config.MIN_DELAY_S:.0f} s as robots.txt asks"
            f" (about {_duration(planned * config.MIN_DELAY_S)}). Ctrl-C is safe; run again to continue."
        )
    pages = fetch_pages(conn, client, config.RAW, max_pages=max_pages, on_progress=typer.echo)
    have = conn.execute(
        "SELECT COUNT(*) FROM notices n WHERE active = 1 AND EXISTS (SELECT 1 FROM pages p WHERE p.notice_id = n.id)"
    ).fetchone()[0]
    typer.echo(
        f"Pages: {pages.fetched} downloaded, {pages.adopted} already on disk, {pages.failed} failed,"
        f" {pages.remaining} still to fetch. Notices with a page: {have} of {feed.total}."
    )


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "-"


@app.command()
def extract(
    no_llm: bool = typer.Option(False, "--no-llm", help="Rules only; never call the local model."),
    model: str = typer.Option(config.OLLAMA_MODEL, "--model", help="Ollama model for the fallback."),
):
    """Turn every current notice into a record: rules first, the local model only for fields the rules left open."""
    from . import extract as extraction
    from .nlp import get_nlp

    conn = _connect()
    if not conn.execute("SELECT COUNT(*) FROM notices WHERE active = 1").fetchone()[0]:
        typer.secho("No notices yet. Run `recall fetch` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    fallback = None
    if not no_llm:
        from .llm import OllamaFallback, OllamaUnavailable

        try:
            fallback = OllamaFallback.connect(model=model)
            typer.echo(f"Fallback: {model} via Ollama, only for fields the rules leave open.")
        except OllamaUnavailable as error:
            typer.secho(f"Fallback off: {error}. Continuing with rules only.", fg=typer.colors.YELLOW, err=True)
    result = extraction.run(conn, config.RAW, nlp=get_nlp(), fallback=fallback, on_progress=typer.echo)
    total = sum(result.sources.values())
    typer.echo(f"Extracted {result.notices} notices in {result.seconds:.1f} s ({result.notices * 10} fields).")
    for source in ("structured", "rule", "model", "none"):
        typer.echo(f"  {source:<10} {result.sources.get(source, 0):>5}  {_share(result.sources.get(source, 0), total)}")
    if fallback:
        typer.echo(f"  model calls: {result.model_calls} (one per notice with open fields)")


def _products_path(path: str | None):
    from pathlib import Path

    if path:
        return Path(path)
    if config.MY_PRODUCTS.exists():
        return config.MY_PRODUCTS
    typer.secho(
        f"No {config.MY_PRODUCTS.relative_to(config.ROOT)} yet - using the example list."
        f" Copy it and put your own products in: cp {config.MY_PRODUCTS_EXAMPLE.relative_to(config.ROOT)}"
        f" {config.MY_PRODUCTS.relative_to(config.ROOT)}",
        fg=typer.colors.YELLOW,
        err=True,
    )
    return config.MY_PRODUCTS_EXAMPLE


@app.command()
def match(products: str = typer.Option(None, "--products", help="Product list (CSV: name, brand[, ean, batch, best_before]).")):
    """Fuzzy-match the recalled products against your product list. Saves score and reason for each match."""
    import time
    from datetime import datetime, timezone

    from . import extract as extraction
    from . import match as matching

    conn = _connect()
    records = extraction.load_records(conn)
    if not records:
        typer.secho("No records yet. Run `recall extract` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    path = _products_path(products)
    my_products = matching.load_products(path)
    started, clock = datetime.now(timezone.utc), time.perf_counter()
    found = matching.find_matches(my_products, records)
    matching.save_matches(conn, found)
    seconds = time.perf_counter() - clock
    strong = sum(m.level == "match" for m in found)
    extraction.log_run(conn, "match", started, seconds, {"products": len(my_products), "records": len(records), "matches": len(found)})
    typer.echo(
        f"{len(my_products)} products x {len(records)} current recalls in {seconds:.2f} s:"
        f" {strong} matches, {len(found) - strong} possible matches. Run `recall alert` to see them."
    )


@app.command()
def alert(only_matches: bool = typer.Option(False, "--only-matches", help="Leave out possible matches.")):
    """One line per match: your product, the reason, whether your pack is affected, what to do, link."""
    from .alert import load_alerts

    alerts = [a for a in load_alerts(_connect()) if a.level == "match" or not only_matches]
    if not alerts:
        typer.echo("No recall matches your products. (Run `recall match` after every `recall extract`.)")
        return
    for item in alerts:
        colour = typer.colors.RED if item.verdict == "affected" else typer.colors.YELLOW if item.level == "match" else None
        typer.secho(item.line(), fg=colour)
    typer.echo(f"\nSource: lebensmittelwarnung.de - always check the official notice before you act.")


def _pct(value: float | None) -> str:
    return "  -  " if value is None else f"{100 * value:5.1f}"


@app.command("eval")
def evaluate_(
    template: bool = typer.Option(False, "--template", help="Write data/gold_template.csv (random notices, empty labels)."),
    size: int = typer.Option(100, "--size", help="Notices in the template."),
    gold: str = typer.Option(None, "--gold", help="Hand-labelled file (default data/gold.csv)."),
):
    """Share of fields from rules alone, run time, and per-field precision / recall against your hand labels."""
    import json
    from pathlib import Path

    from . import evaluate

    conn = _connect()
    if template:
        count = evaluate.make_template(conn, config.GOLD_TEMPLATE, size=size)
        typer.echo(
            f"Wrote {config.GOLD_TEMPLATE.relative_to(config.ROOT)} with {count} randomly drawn notices"
            f" (seed {evaluate.SEED}). Label them by hand (format in recall/evaluate.py),"
            f" then save the file as {config.GOLD.relative_to(config.ROOT)} and run `recall eval`."
        )
        return

    shares = evaluate.source_shares(conn)
    runs = evaluate.last_runs(conn)
    typer.echo(f"Fields: {shares['filled']} of {shares['fields']} filled.")
    typer.echo(
        f"  from rules alone: {_share(shares['structured'] + shares['rule'], shares['filled'])}"
        f"  (structured {shares['structured']}, rule {shares['rule']}, model {shares['model']})"
    )
    for name, run in runs.items():
        typer.echo(f"  run time {name}: {run['seconds']:.1f} s")

    gold_path = Path(gold) if gold else config.GOLD
    result = {"shares": shares, "runs": runs}
    if not gold_path.exists():
        typer.secho(
            f"\nNo {gold_path.name} yet, so no accuracy. Run `recall eval --template`, label the notices by hand,"
            f" save as {config.GOLD.relative_to(config.ROOT)}.",
            fg=typer.colors.YELLOW,
        )
    else:
        report = evaluate.score(conn, gold_path)
        typer.echo(f"\nAgainst {gold_path.name}: {report.labelled_notices} labelled notices"
                   + (f" ({len(report.missing)} not in the database)" if report.missing else ""))
        typer.echo(f"  {'field':<16}{'notices':>8}{'P %':>7}{'R %':>7}   precision by source")
        rows = {}
        for name, s in [*report.fields.items(), ("ALL", report.total())]:
            by_source = ", ".join(f"{src} {_pct(tp / n if n else None).strip()} ({n})" for src, (tp, n) in sorted(s.by_source.items()))
            typer.echo(f"  {name:<16}{s.notices:>8}{_pct(s.precision):>7}{_pct(s.recall):>7}   {by_source}")
            rows[name] = {"notices": s.notices, "gold": s.gold, "predicted": s.predicted, "true_pos": s.true_pos,
                          "precision": s.precision, "recall": s.recall, "by_source": {k: list(v) for k, v in s.by_source.items()}}
        result["accuracy"] = rows
    if config.MATCH_CASES.exists():
        m = evaluate.score_matches(conn, config.MATCH_CASES)
        typer.echo(
            f"\nMatching, written cases in {config.MATCH_CASES.name} (a regression check, not hand labels): {m.pairs} pairs —"
            f" level {_pct(m.level_accuracy).strip()} % ({m.level_correct}/{m.pairs}),"
            f" P {_pct(m.precision).strip()} %, R {_pct(m.recall).strip()} %,"
            f" verdict {_pct(m.verdict_accuracy).strip()} % ({m.verdict_correct}/{m.verdict_total})"
        )
        result["matching"] = {
            "pairs": m.pairs,
            "level_correct": m.level_correct,
            "level_accuracy": m.level_accuracy,
            "gold_positive": m.gold_positive,
            "predicted_positive": m.predicted_positive,
            "true_positive": m.true_positive,
            "precision": m.precision,
            "recall": m.recall,
            "verdict_total": m.verdict_total,
            "verdict_correct": m.verdict_correct,
            "verdict_accuracy": m.verdict_accuracy,
        }
    out = config.DATA / "eval_report.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"\nSaved {out.relative_to(config.ROOT)}")


@app.command("build-site")
def build_site(
    out: str = typer.Option(None, "--out", help="Folder for the website (default: public/)."),
    public: bool = typer.Option(False, "--public", help="Refuse to build unless site.json has what a public site needs."),
):
    """Write the public website as static files: rules only, visitors' product lists stay in their browser."""
    from pathlib import Path

    from . import site

    settings = site.load_settings(config.SITE_SETTINGS)
    target = Path(out) if out else config.SITE_OUT
    try:
        counts = site.build(_connect(), config.RAW, target, settings=settings, public=public)
    except site.NotReady as error:
        typer.secho(f"Not built: {error}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo(f"Built {counts['pages']} pages for {counts['recalls']} current recalls in {target}.")
    if not public:
        typer.echo(f"Preview: python -m http.server -d {target} 8001, then open http://127.0.0.1:8001")


@app.command()
def serve(
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("127.0.0.1", "--host", help="127.0.0.1 = only this computer can open it."),
):
    """Open the web app: current recalls, your products, and whether your pack is affected."""
    import uvicorn

    from .web import create_app

    typer.echo(f"Recall Monitor runs at http://{host}:{port}  (Ctrl-C stops it)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
