"""One entry point: conditions in, ranked flies out. Uses Jev when a key is set, else the rules."""

import logging
from datetime import date

from . import catalog, conditions, jev, rules

log = logging.getLogger(__name__)
TOP_N = 10
JEV_CANDIDATES = 40  # best rules candidates sent to Jev for rescoring


class BadRequest(ValueError):
    pass


def _with_river(req: dict, cat: catalog.Catalog) -> tuple[dict, dict | None]:
    """A home-river preset fixes region and water type, and names the place if the request doesn't."""
    if not req.get("river"):
        return req, None
    river = cat.rivers.get(req["river"])
    if river is None:
        raise BadRequest(f"Pick a river: {', '.join(cat.rivers)}")
    return {**req, "region": river["region"], "water_type": river["water_type"],
            "place": req.get("place") or river["place"]}, river


def _parse(req: dict, cat: catalog.Catalog) -> tuple[rules.Conditions, date]:
    region, water = req.get("region"), req.get("water_type")
    if region not in cat.regions:
        raise BadRequest(f"Pick a region: {', '.join(cat.regions)}")
    if water not in cat.water_types:
        raise BadRequest(f"Pick a water type: {', '.join(cat.water_types)}")
    fly_type = req.get("fly_type") or "any"
    if fly_type not in catalog.FLY_TYPES:
        raise BadRequest(f"Pick a fly type: {', '.join(catalog.FLY_TYPES)}")
    try:
        on = date.fromisoformat(req["date"]) if req.get("date") else date.today()
    except ValueError:
        raise BadRequest("Date must look like 2026-06-24")
    sky = req.get("sky") or "partly"
    flow = req.get("flow") or "normal"
    if sky not in catalog.SKIES or flow not in catalog.FLOWS:
        raise BadRequest(f"Sky must be one of {catalog.SKIES}; flow one of {catalog.FLOWS}")
    temp = req.get("water_temp_f")
    cond = rules.Conditions(
        region=region, water_type=water, month=on.month, fly_type=fly_type,
        water_temp_f=float(temp) if temp not in (None, "") else None,
        temp_source="angler" if temp not in (None, "") else "typical",
        sky=sky, windy=bool(req.get("windy")), flow=flow, place=req.get("place"),
    )
    return cond, on


def recommend(req: dict, mode: str = "auto", jev_client=None) -> dict:
    """mode: 'auto' (Jev if a key is set), 'rules', or 'jev'."""
    cat = catalog.load()
    req, river = _with_river(req, cat)
    cond, on = _parse(req, cat)
    if river:
        cond.adjust = river.get("adjust")
    notes: list[str] = []

    live = {}
    lat, lon = req.get("lat"), req.get("lon")
    preset_spot = river is not None and (lat is None or lon is None)
    if preset_spot:
        lat, lon = river["lat"], river["lon"]
    if lat is not None and lon is not None and req.get("use_live", True):
        if abs((on - date.today()).days) <= 1:
            live = conditions.lookup(float(lat), float(lon), on)
            if "water_temp_f" in live and cond.temp_source != "angler":
                cond.water_temp_f, cond.temp_source = live["water_temp_f"], "gauge"
            if "flow" in live and not req.get("flow"):
                cond.flow = live["flow"]
            if "sky" in live and not req.get("sky"):
                cond.sky, cond.windy = live["sky"], live["windy"] or cond.windy
            if not live:
                notes.append("Couldn't reach the stream gauge or weather service, so typical conditions were used.")
        elif not preset_spot:
            notes.append("Live gauge and weather are only used for today's date.")

    foods = rules.active_foods(cat, cond)
    ranked = rules.score_flies(cat, cond, foods)
    shares = rules.food_shares(foods, cat)
    used = "rules"

    want_jev = mode == "jev" or (mode == "auto" and jev.available())
    if want_jev and ranked:
        try:
            ranked, shares = jev.score_flies(cat, cond, ranked[:JEV_CANDIDATES], foods, client=jev_client)
            used = "jev"
        except Exception as e:  # network, auth, quota: fall back rather than fail the search
            log.warning("Jev scoring failed, using rules: %s", e)
            notes.append("Jev was unavailable, so these are hatch-chart rankings.")

    if not foods:
        notes.append("The starter hatch chart doesn't cover this water in this region yet.")

    return {
        "engine": used,
        "conditions": {
            "region": cat.regions[cond.region],
            "water_type": cat.water_types[cond.water_type]["name"],
            "fish": cat.water_types[cond.water_type]["fish"],
            "date": on.isoformat(),
            "fly_type": catalog.FLY_TYPES[cond.fly_type],
            "water_temp_f": round(cond.resolved_temp(cat)),
            "temp_source": cond.temp_source,
            "sky": cond.sky, "windy": cond.windy, "flow": cond.flow,
            "gauge": live.get("gauge"),
            "river": river and {"name": river["name"], "reports": river.get("trained_on", {}).get("reports", 0)},
        },
        "eating": shares,
        "flies": ranked[:TOP_N],
        "notes": notes,
    }
