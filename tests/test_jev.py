"""Jev scoring against a fake TypeSafe API (no network, no key needed)."""

import json

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeClient

from flypicker import jev
from flypicker.recommend import recommend

REQ = {"region": "west", "water_type": "freestone", "date": "2026-09-20", "fly_type": "dry", "sky": "overcast", "flow": "normal"}


def fake_api(food_probs=None, fly_probs=None, fail=False):
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        calls.append(body)
        if fail:
            return httpx2.Response(500, json={"detail": "boom"})
        answers = {}
        for name, q in body["questions"].items():
            if q["type"] == "choice":
                labels = list(q["criteria"])
                probs = food_probs or {l: 1 / len(labels) for l in labels}
                probs = {l: probs.get(l, 0.0) for l in labels}
                best = max(probs, key=probs.get)
                answers[name] = {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}
            else:
                answers[name] = {"type": "noul", "noul": (fly_probs or {}).get(name.removeprefix("fly__"), 0.1)}
        return httpx2.Response(200, json={"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 0}})

    client = TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler), retry=RetryPolicy(max_retries=0))
    return client, calls


def test_jev_reranks_and_reports_foods():
    client, calls = fake_api(food_probs={"bwo": 0.7, "october_caddis": 0.2}, fly_probs={"bwo_parachute": 0.9})
    res = recommend(REQ, mode="jev", jev_client=client)
    assert res["engine"] == "jev"
    assert res["flies"][0]["id"] == "bwo_parachute"
    assert res["eating"][0] == {"id": "bwo", "name": "Blue-winged olives", "share": 0.7}
    assert "Jev: 90% likely" in res["flies"][0]["reason"]

    first = calls[0]
    assert first["model"] == "jev-latest"
    assert first["state"]["place"]["water_type"] == "Freestone river"
    assert first["state"]["month"] == "September"
    assert "food" in first["questions"]
    assert all(q["type"] == "noul" for k, q in first["questions"].items() if k != "food")


def test_candidates_are_split_across_requests(monkeypatch):
    monkeypatch.setattr(jev, "CHUNK", 5)
    client, calls = fake_api()
    res = recommend({**REQ, "fly_type": "any"}, mode="jev", jev_client=client)
    assert res["engine"] == "jev"
    assert len(calls) > 1
    assert sum("food" in c["questions"] for c in calls) == 1
    assert all(len([k for k in c["questions"] if k.startswith("fly__")]) <= 5 for c in calls)


def test_falls_back_to_rules_when_jev_fails():
    client, _ = fake_api(fail=True)
    res = recommend(REQ, mode="jev", jev_client=client)
    assert res["engine"] == "rules"
    assert any("Jev was unavailable" in n for n in res["notes"])
    assert res["flies"]


def test_auto_mode_uses_rules_without_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert recommend(REQ)["engine"] == "rules"


@pytest.mark.parametrize("bad", [{"region": "mars"}, {"water_type": "puddle"}, {"fly_type": "lure"}, {"date": "June"}])
def test_bad_requests(bad):
    from flypicker.recommend import BadRequest
    with pytest.raises(BadRequest):
        recommend({**REQ, **bad}, mode="rules")
