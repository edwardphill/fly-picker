import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from flypicker import catchlog
    monkeypatch.setattr(catchlog, "DB_PATH", str(tmp_path / "log.db"))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    import app
    return TestClient(app.app)


def test_page_is_served_in_server_mode(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "const SERVER = true;" in r.text and "Fly Picker" in r.text


def test_search_then_log_a_catch(client):
    r = client.post("/api/recommend", json={"region": "west", "water_type": "tailwater", "date": "2026-01-10"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "rules" and body["flies"]
    fly = body["flies"][0]["id"]
    assert client.post("/api/catch", json={"search_id": body["search_id"], "fly_id": fly, "outcome": "caught", "fish_count": 3}).json() == {"ok": True}
    assert client.post("/api/catch", json={"search_id": 9999, "fly_id": fly, "outcome": "caught"}).status_code == 404
    assert client.post("/api/catch", json={"search_id": body["search_id"], "fly_id": "nope", "outcome": "caught"}).status_code == 400


def test_bad_search_is_400(client):
    assert client.post("/api/recommend", json={"region": "mars", "water_type": "freestone"}).status_code == 400


def test_search_a_home_river(client):
    from flypicker import catalog, rules
    r = client.post("/api/recommend", json={"river": "elk", "date": "2026-01-10"})
    assert r.status_code == 200
    body = r.json()
    cat = catalog.load()
    assert body["conditions"]["river"]["name"] == "Elk River"
    assert body["conditions"]["region"] == cat.regions["south"]
    # The preset's region, water and any trained adjustments, whatever the latest refit kept.
    same = rules.Conditions("south", "tailwater", 1, adjust=cat.rivers["elk"].get("adjust"))
    assert body["notes"] == [] and body["flies"][0]["id"] == rules.score_flies(cat, same)[0]["id"]
    assert client.post("/api/recommend", json={"river": "nile"}).status_code == 400


def test_search_a_river_with_no_reports(client):
    from flypicker import catalog
    body = client.post("/api/recommend", json={"river": "magalloway", "date": "2026-06-10"}).json()
    assert body["conditions"]["river"] == {"name": "Magalloway River", "reports": 0}
    assert body["conditions"]["region"] == catalog.load().regions["northeast"]
    assert body["notes"] == [] and len(body["flies"]) == 10
