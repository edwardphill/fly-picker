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
    from flypicker import catalog
    r = client.post("/api/recommend", json={"river": "elk", "date": "2026-01-10"})
    assert r.status_code == 200
    body = r.json()
    assert body["conditions"]["river"]["name"] == "Elk River"
    assert body["conditions"]["region"] == catalog.load().regions["south"]
    assert body["notes"] == [] and body["flies"][0]["id"] == "zebra_midge"
    assert client.post("/api/recommend", json={"river": "nile"}).status_code == 400
