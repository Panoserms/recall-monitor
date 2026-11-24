"""The web app: pages, the product list, and the live check. Uses a temporary database and product list."""
import csv

import pytest
from fastapi.testclient import TestClient
from test_alert import _store
from test_match import SPINACH, record

from recall import db
from recall.web import create_app

OTHER = record("Deutsches Corned Beef", manufacturer=["Bakenhus Biofleisch GmbH"], best_before=["2028-03-01"],
               notice_id="261109_09_NI_Corned_Beef")


@pytest.fixture
def paths(tmp_path):
    database = tmp_path / "recall.db"
    conn = db.connect(database)
    _store(conn, SPINACH)
    _store(conn, OTHER)
    conn.close()
    example = tmp_path / "example.csv"
    example.write_text("name,brand,ean,batch,best_before,note\nSpinat gehackt,K-Classic,,,,example\n", encoding="utf-8")
    return {"db": database, "products": tmp_path / "my_products.csv", "example": example}


@pytest.fixture
def client(paths):
    return TestClient(create_app(db_path=paths["db"], products_path=paths["products"], example_path=paths["example"]))


def _products(paths):
    with paths["products"].open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_home_lists_current_recalls(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "K-Classic Spinat gehackt" in page.text and "Deutsches Corned Beef" in page.text
    assert "lebensmittelwarnung.de" in page.text  # source line


def test_empty_product_list_invites_to_add_products(client):
    assert "Add your products" in client.get("/").text


def test_recall_page_shows_what_to_check_and_the_official_link(client):
    page = client.get(f"/recall/{SPINACH.id}")
    assert page.status_code == 200
    assert "L5435 DD" in page.text and "10/2027" in page.text
    assert SPINACH.link in page.text


def test_unknown_recall_is_404(client):
    assert client.get("/recall/nope").status_code == 404


def test_adding_a_product_saves_it_and_shows_the_alert(client, paths):
    answer = client.post("/products", data={"name": "Spinat gehackt", "brand": "K-Classic", "best_before": "31.10.2027"},
                         follow_redirects=False)
    assert answer.status_code == 303
    assert _products(paths)[0]["name"] == "Spinat gehackt"
    home = client.get("/").text
    assert "1 of your 1 product has a current recall" in home and "Your pack is affected" in home


def test_editing_and_removing_a_product(client, paths):
    client.post("/products", data={"name": "Spinat", "brand": ""})
    client.post("/products/1", data={"name": "Spinat gehackt", "brand": "K-Classic", "batch": "L5435 DD"})
    assert _products(paths)[0]["batch"] == "L5435 DD"
    client.post("/products/1/delete")
    assert _products(paths) == []


def test_a_product_needs_a_name(client, paths):
    answer = client.post("/products", data={"name": "  ", "brand": "Kölln"})
    assert answer.status_code == 400
    assert not paths["products"].exists()


def test_load_example_list(client, paths):
    client.post("/products/example")
    assert _products(paths)[0]["name"] == "Spinat gehackt"


def test_live_check_answers_with_the_verdict(client):
    answer = client.get("/api/check", params={"name": "Spinat gehackt", "brand": "K-Classic", "best_before": "05.11.2027"})
    [found] = answer.json()["matches"]
    assert found["notice_id"] == SPINACH.id
    assert found["verdict"] == "not_affected"


def test_live_check_with_a_short_name_gives_nothing(client):
    assert client.get("/api/check", params={"name": "S"}).json()["matches"] == []


def test_notices_removed_from_the_portal_are_not_shown(client, paths):
    conn = db.connect(paths["db"])
    conn.execute("UPDATE notices SET active = 0 WHERE id = ?", (OTHER.id,))
    conn.close()
    assert "Deutsches Corned Beef" not in client.get("/").text
    assert client.get(f"/recall/{OTHER.id}").status_code == 404


def test_api_lists_recalls_as_json(client):
    data = client.get("/api/recalls").json()
    assert {r["id"] for r in data["recalls"]} == {SPINACH.id, OTHER.id}
