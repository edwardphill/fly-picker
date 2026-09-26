"""Live conditions near a spot: water temperature and flow from USGS gauges, weather from Open-Meteo.

Both services are free and need no key. Every lookup fails soft: it returns None, and the
recommender falls back to typical values for the month.

Note: USGS is moving from its legacy Water Services API (used here) to the new Water Data
APIs at api.waterdata.usgs.gov; swap the two URLs below when the legacy service retires.
"""

import json
import math
import urllib.parse
import urllib.request
from datetime import date

USGS_IV = "https://waterservices.usgs.gov/nwis/iv/"
USGS_STAT = "https://waterservices.usgs.gov/nwis/stat/"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 8
SEARCH_BOX_DEG = 0.25  # about 15-17 miles each way


def _get(url: str, params: dict) -> bytes | None:
    try:
        req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "fly-picker/0.1"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except Exception:
        return None


def _miles(lat1, lon1, lat2, lon2) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def nearest_gauge(lat: float, lon: float) -> dict | None:
    """Latest water temp (F) and flow (cfs) from the nearest active USGS gauge within the search box."""
    b = SEARCH_BOX_DEG
    raw = _get(USGS_IV, {
        "format": "json",
        "bBox": f"{lon - b:.4f},{lat - b:.4f},{lon + b:.4f},{lat + b:.4f}",
        "parameterCd": "00010,00060",
        "siteStatus": "active",
    })
    if raw is None:
        return None
    try:
        series = json.loads(raw)["value"]["timeSeries"]
    except (ValueError, KeyError):
        return None

    sites: dict[str, dict] = {}
    for ts in series:
        info = ts["sourceInfo"]
        site_no = info["siteCode"][0]["value"]
        geo = info["geoLocation"]["geogLocation"]
        values = ts["values"][0]["value"]
        if not values:
            continue
        try:
            reading = float(values[-1]["value"])
        except ValueError:
            continue
        if reading <= -999999:  # USGS no-data sentinel
            continue
        site = sites.setdefault(site_no, {
            "site_no": site_no,
            "name": info["siteName"],
            "miles": round(_miles(lat, lon, geo["latitude"], geo["longitude"]), 1),
        })
        code = ts["variable"]["variableCode"][0]["value"]
        if code == "00010":
            site["water_temp_f"] = round(reading * 9 / 5 + 32, 1)
        elif code == "00060":
            site["flow_cfs"] = reading

    # Prefer the closest gauge that reports temperature, else the closest with flow.
    ranked = sorted(sites.values(), key=lambda s: ("water_temp_f" not in s, s["miles"]))
    return ranked[0] if ranked else None


def flow_class(site_no: str, cfs: float, on: date) -> str | None:
    """'low', 'normal' or 'high' against this gauge's 25th/75th percentile flow for the calendar day."""
    raw = _get(USGS_STAT, {
        "format": "rdb", "sites": site_no, "statReportType": "daily",
        "statTypeCd": "p25,p75", "parameterCd": "00060",
    })
    if raw is None:
        return None
    header = None
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if header is None:
            header = cols
            continue
        if cols[0].endswith("s") and cols[0][:-1].isdigit():  # RDB column-width row, e.g. "5s"
            continue
        row = dict(zip(header, cols))
        if row.get("month_nu") == str(on.month) and row.get("day_nu") == str(on.day):
            try:
                p25, p75 = float(row["p25_va"]), float(row["p75_va"])
            except (KeyError, ValueError):
                return None
            return "low" if cfs < p25 else "high" if cfs > p75 else "normal"
    return None


def weather(lat: float, lon: float) -> dict | None:
    raw = _get(OPEN_METEO, {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "current": "cloud_cover,precipitation,wind_speed_10m",
        "wind_speed_unit": "mph",
    })
    if raw is None:
        return None
    try:
        cur = json.loads(raw)["current"]
    except (ValueError, KeyError):
        return None
    cloud, rain, wind = cur.get("cloud_cover", 50), cur.get("precipitation", 0), cur.get("wind_speed_10m", 0)
    sky = "rain" if rain >= 0.2 else "overcast" if cloud >= 70 else "sunny" if cloud <= 30 else "partly"
    return {"sky": sky, "windy": wind >= 15, "cloud_cover": cloud, "wind_mph": wind}


def lookup(lat: float, lon: float, on: date) -> dict:
    """Everything we can find for a spot. Keys are only present when a lookup worked."""
    out: dict = {}
    gauge = nearest_gauge(lat, lon)
    if gauge:
        out["gauge"] = gauge
        if "water_temp_f" in gauge:
            out["water_temp_f"] = gauge["water_temp_f"]
        if "flow_cfs" in gauge:
            fc = flow_class(gauge["site_no"], gauge["flow_cfs"], on)
            if fc:
                out["flow"] = fc
    wx = weather(lat, lon)
    if wx:
        out["weather"] = wx
        out["sky"], out["windy"] = wx["sky"], wx["windy"]
    return out
