"""The web app: current recalls, your product list, and whether your pack is affected.

Run it with `recall serve` and open http://127.0.0.1:8000. It reads the same database as
the command line (data/recall.db) and keeps your product list in data/my_products.csv.
Matches are recomputed whenever the product list or the records change.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import config, db
from .. import match as matching
from .data import FILTERS, Store, recall_view

_HERE = Path(__file__).resolve().parent


def create_app(
    db_path: Path = config.DB_PATH,
    products_path: Path = config.MY_PRODUCTS,
    example_path: Path = config.MY_PRODUCTS_EXAMPLE,
) -> FastAPI:
    app = FastAPI(title="Recall Monitor", docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")
    store = Store(lambda: db.connect(db_path), products_path)

    def page(request: Request, name: str, **context) -> HTMLResponse:
        context.setdefault("products", store.products())
        context.setdefault("message", request.query_params.get("msg", ""))
        context["status"] = store.status()
        return templates.TemplateResponse(request, name, context)

    def back(to: str, message: str) -> RedirectResponse:
        from urllib.parse import quote

        return RedirectResponse(f"{to}?msg={quote(message)}", status_code=303)

    # ------------------------------------------------------------- pages

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        records = store.records()
        return page(
            request,
            "index.html",
            recalls=[recall_view(r) for r in records],
            alerts=store.alerts(),
            states=sorted({s for r in records for s in r.values("states")}),
            filters=FILTERS,
        )

    @app.get("/recall/{notice_id}", response_class=HTMLResponse)
    def recall_page(request: Request, notice_id: str):
        record = store.record(notice_id)
        if record is None:
            raise HTTPException(404, "This recall is not (or no longer) on lebensmittelwarnung.de.")
        mine = [a for a in store.alerts() if a["notice_id"] == notice_id]
        return page(request, "recall.html", recall=recall_view(record, detail=True), alerts=mine)

    @app.get("/products", response_class=HTMLResponse)
    def products_page(request: Request):
        alerts = store.alerts()
        by_row: dict[int, list[dict]] = {}
        for item in alerts:
            by_row.setdefault(item["product_row"], []).append(item)
        return page(request, "products.html", by_row=by_row)

    # ------------------------------------------------------ product list

    def _product(row: int, name: str, brand: str, ean: str, batch: str, best_before: str, note: str) -> matching.MyProduct:
        if not name.strip():
            raise HTTPException(400, "A product needs a name.")
        return matching.MyProduct(row=row, name=name.strip(), brand=brand.strip(), ean=ean.strip(),
                                  batch=batch.strip(), best_before=best_before.strip(), note=note.strip())

    @app.post("/products")
    def add_product(name: str = Form(""), brand: str = Form(""), ean: str = Form(""), batch: str = Form(""),
                    best_before: str = Form(""), note: str = Form("")):
        products = store.products()
        product = _product(len(products) + 1, name, brand, ean, batch, best_before, note)
        store.save_products([*products, product])
        hits = [a for a in store.alerts() if a["product_row"] == product.row and a["level"] == "match"]
        return back("/products", f"Added {product.name}." + (f" It matches {len(hits)} current recall(s)." if hits else " No current recall matches it."))

    @app.post("/products/example")
    def load_example():
        if store.products():
            return back("/products", "Your list is not empty, so the example list was not loaded.")
        shutil.copyfile(example_path, products_path)
        store.refresh()
        return back("/products", "Loaded the example list. Edit or remove the products, then add your own.")

    @app.post("/products/{row}")
    def edit_product(row: int, name: str = Form(""), brand: str = Form(""), ean: str = Form(""), batch: str = Form(""),
                     best_before: str = Form(""), note: str = Form("")):
        products = store.products()
        if not 1 <= row <= len(products):
            raise HTTPException(404, "No such product.")
        products[row - 1] = _product(row, name, brand, ean, batch, best_before, note)
        store.save_products(products)
        return back("/products", f"Saved {products[row - 1].name}.")

    @app.post("/products/{row}/delete")
    def delete_product(row: int):
        products = store.products()
        if not 1 <= row <= len(products):
            raise HTTPException(404, "No such product.")
        removed = products.pop(row - 1)
        store.save_products(products)
        return back("/products", f"Removed {removed.name}.")

    # --------------------------------------------------------------- API

    @app.get("/api/recalls")
    def api_recalls():
        return {"recalls": [recall_view(r) for r in store.records()]}

    @app.get("/api/recalls/{notice_id}")
    def api_recall(notice_id: str):
        record = store.record(notice_id)
        if record is None:
            raise HTTPException(404, "unknown or removed notice")
        return recall_view(record, detail=True)

    @app.get("/api/alerts")
    def api_alerts():
        return {"alerts": store.alerts()}

    @app.get("/api/check")
    def api_check(name: str = "", brand: str = "", ean: str = "", batch: str = "", best_before: str = ""):
        """Live check of one product (not saved): which current recalls match, and is this pack affected?"""
        if len(name.strip()) < 3 and not ean.strip():
            return {"matches": []}
        product = matching.MyProduct(row=0, name=name, brand=brand, ean=ean, batch=batch, best_before=best_before)
        found = matching.find_matches([product], store.records())[:8]
        return {"matches": [store.alert_view(m) for m in found]}

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, error: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        detail = error.detail if error.status_code != 404 or error.detail != "Not Found" else "There is no page here."
        context = {"code": error.status_code, "detail": detail, "products": [], "message": "", "status": store.status()}
        return templates.TemplateResponse(request, "error.html", context, status_code=error.status_code)

    return app
