"""Live lookups against canned USGS and Open-Meteo responses."""

import json
from datetime import date

from flypicker import conditions
from flypicker.recommend import recommend

IV = {"value": {"timeSeries": [
    {"sourceInfo": {"siteName": "FAR CREEK", "siteCode": [{"value": "111"}], "geoLocation": {"geogLocation": {"latitude": 45.2, "longitude": -111.2}}},
     "variable": {"variableCode": [{"value": "00010"}]}, "values": [{"value": [{"value": "12.0"}]}]},
    {"sourceInfo": {"siteName": "MADISON RIVER NR ENNIS", "siteCode": [{"value": "222"}], "geoLocation": {"geogLocation": {"latitude": 45.35, "longitude": -111.73}}},
     "variable": {"variableCode": [{"value": "00010"}]}, "values": [{"value": [{"value": "10.0"}]}]},
    {"sourceInfo": {"siteName": "MADISON RIVER NR ENNIS", "siteCode": [{"value": "222"}], "geoLocation": {"geogLocation": {"latitude": 45.35, "longitude": -111.73}}},
     "variable": {"variableCode": [{"value": "00060"}]}, "values": [{"value": [{"value": "2400"}]}]},
]}}
STAT = "#\nagency_cd\tsite_no\tparameter_cd\tts_id\tloc_web_ds\tmonth_nu\tday_nu\tbegin_yr\tend_yr\tcount_nu\tp25_va\tp75_va\n5s\t15s\t5s\t10n\t15s\t3n\t3n\t6n\t6n\t8n\t12s\t12s\nUSGS\t222\t00060\t1\t\t9\t26\t1990\t2025\t35\t900\t1500\n"
METEO = {"current": {"cloud_cover": 85, "precipitation": 0.0, "wind_speed_10m": 18}}


def fake_get(url, params):
    if url == conditions.USGS_IV:
        return json.dumps(IV).encode()
    if url == conditions.USGS_STAT:
        return STAT.encode()
    if url == conditions.OPEN_METEO:
        return json.dumps(METEO).encode()
    return None


def test_lookup_picks_nearest_gauge_and_classifies(monkeypatch):
    monkeypatch.setattr(conditions, "_get", fake_get)
    out = conditions.lookup(45.34, -111.72, date(2026, 9, 26))
    assert out["gauge"]["site_no"] == "222"
    assert out["water_temp_f"] == 50.0
    assert out["flow"] == "high"
    assert out["sky"] == "overcast" and out["windy"] is True


def test_recommend_uses_live_readings_for_today(monkeypatch):
    monkeypatch.setattr(conditions, "_get", fake_get)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    today = date.today().isoformat()
    res = recommend({"region": "west", "water_type": "freestone", "date": today, "lat": 45.34, "lon": -111.72})
    c = res["conditions"]
    assert c["temp_source"] == "gauge" and c["water_temp_f"] == 50
    assert c["sky"] == "overcast" and c["windy"] is True
    assert c["gauge"]["name"] == "MADISON RIVER NR ENNIS"


def test_angler_inputs_beat_live_readings(monkeypatch):
    monkeypatch.setattr(conditions, "_get", fake_get)
    today = date.today().isoformat()
    res = recommend({"region": "west", "water_type": "freestone", "date": today, "lat": 45.34, "lon": -111.72,
                     "water_temp_f": 44, "sky": "sunny", "flow": "low"}, mode="rules")
    c = res["conditions"]
    assert (c["water_temp_f"], c["temp_source"], c["sky"], c["flow"]) == (44, "angler", "sunny", "low")


def test_lookup_fails_soft(monkeypatch):
    monkeypatch.setattr(conditions, "_get", lambda url, params: None)
    today = date.today().isoformat()
    res = recommend({"region": "west", "water_type": "freestone", "date": today, "lat": 45.3, "lon": -111.7}, mode="rules")
    assert res["conditions"]["temp_source"] == "typical"
    assert any("Couldn't reach" in n for n in res["notes"])
