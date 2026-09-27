"""Hatch-chart scorer: works with no API key and no training data.

It estimates how active each food item is for the conditions, then scores each fly
by the foods it imitates. Jev (see jev.py) uses the same conditions and candidates.
web/engine.js is a line-for-line port for the offline demo page; keep them in sync
(scripts/check_parity.py compares the two).
"""

from dataclasses import dataclass

from .catalog import Catalog, size_range_label

PEAK = 1.0
ON = 0.55
OFF = 0.04
TEMP_FALLOFF_F = 12.0  # activity fades to its floor this many degrees outside a food's range
TEMP_FLOOR = 0.08
# List order (see mix): each fly already listed for the same food cuts a fly's score to this share,
# and each fly already listed of the same type (dry, nymph, streamer...) to this share. Picked on the
# older Caney Fork and Elk River reports: the gentlest setting within noise of the best one there
# (see eval/train.py --mixing). One fly per food scored a little higher on those reports, but it fills
# a dries-only list in February with out-of-season hatches.
FOOD_REPEAT = 0.3
TYPE_REPEAT = 0.8
MIXED_PLACES = 10  # places filled this way; the rest stay in score order
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


@dataclass
class Conditions:
    region: str
    water_type: str
    month: int
    fly_type: str = "any"
    water_temp_f: float | None = None
    temp_source: str = "typical"  # typical | gauge | angler
    sky: str = "partly"
    windy: bool = False
    flow: str = "normal"
    place: str | None = None
    # Learned per-river multipliers (see eval/train.py and data/rivers.json):
    # {"name": "Elk River", "foods": {food_id: x}, "flies": {fly_id: x}}
    adjust: dict | None = None

    def resolved_temp(self, cat: Catalog) -> float:
        if self.water_temp_f is not None:
            return float(self.water_temp_f)
        profile = cat.water_types[self.water_type]["temp_profile"]
        return float(cat.typical_temp[self.region][profile][self.month - 1])


def _season_spec(food: dict, region: str) -> dict | None:
    season = food["season"]
    if region in season:
        return season[region]
    if region == "south" and "east" in season and "all" not in season:
        # Southern hatches run about a month ahead of the East's.
        shift = lambda ms: [((m - 2) % 12) + 1 for m in ms]
        east = season["east"]
        return {"peak": shift(east.get("peak", [])), "on": shift(east.get("on", []))}
    if region == "northeast" and "east" in season:
        # Foods without a northern chart of their own keep the East's months.
        return season["east"]
    return season.get("all")


def season_level(food: dict, region: str, month: int) -> tuple[float, str]:
    spec = _season_spec(food, region)
    if spec is None:
        return 0.0, "not found in this region"
    if month in spec.get("peak", []):
        return PEAK, "peak season"
    if month in spec.get("on", []):
        return ON, "in season"
    return food.get("base", OFF), "out of season"


def temp_fit(food: dict, temp: float) -> float:
    lo, hi = food["temp"]
    if lo <= temp <= hi:
        return 1.0
    gap = lo - temp if temp < lo else temp - hi
    return max(TEMP_FLOOR, 1.0 - gap / TEMP_FALLOFF_F)


def food_activity(food: dict, cond: Conditions, temp: float) -> tuple[float, list[str]]:
    water = food["water"].get(cond.water_type, 0.0)
    level, season_note = season_level(food, cond.region, cond.month)
    if water == 0.0 or level == 0.0:
        return 0.0, []
    notes = [f"{season_note} in {MONTHS[cond.month - 1]}"]

    tf = temp_fit(food, temp)
    lo, hi = food["temp"]
    if tf < 1.0:
        notes.append(f"{temp:.0f}°F water is {'cold' if temp < lo else 'warm'} for them ({lo}–{hi}°F)")

    sky_mods = food.get("sky", {})
    sky = sky_mods.get(cond.sky, 1.0)
    if sky > 1.0:
        notes.append("rain helps" if cond.sky == "rain" else f"{cond.sky} skies help")
    if cond.windy:
        sky *= sky_mods.get("windy", 1.0)
        if sky_mods.get("windy", 1.0) > 1.0:
            notes.append("wind helps")

    flow = food.get("flow", {}).get(cond.flow, 1.0)
    if food["stage"] == "surface":
        flow *= {"high": 0.6, "low": 1.1}.get(cond.flow, 1.0)
    if flow > 1.0 and cond.flow == "high":
        notes.append("high water helps")

    boost = (cond.adjust or {}).get("foods", {}).get(food["id"], 1.0)
    return level * water * tf * sky * flow * boost, notes


def active_foods(cat: Catalog, cond: Conditions) -> dict[str, tuple[float, list[str]]]:
    temp = cond.resolved_temp(cat)
    out = {}
    for fid, food in cat.foods.items():
        act, notes = food_activity(food, cond, temp)
        if act > 0:
            out[fid] = (act, notes)
    return out


def fly_matches(fly: dict, cond: Conditions) -> bool:
    return cond.water_type in fly["water"] and cond.fly_type in ("any", fly["family"])


def recommended_sizes(fly: dict, food: dict) -> tuple[list[int], bool]:
    """The overlap of the fly's sizes and the food's, and whether they overlap at all."""
    big = max(fly["sizes"][0], food["sizes"][0])
    small = min(fly["sizes"][1], food["sizes"][1])
    if big <= small:
        return [big, small], True
    return list(fly["sizes"]), False


def strength_label(score: float) -> str:
    if score >= 0.8:
        return "strong"
    if score >= 0.35:
        return "fair"
    return "long shot"


def score_flies(cat: Catalog, cond: Conditions, foods: dict | None = None, mixed: bool = True) -> list[dict]:
    """Best first. mixed=True is the order the app lists: spread across foods and fly types (see mix)."""
    foods = active_foods(cat, cond) if foods is None else foods
    results = []
    for fly in cat.flies.values():
        if not fly_matches(fly, cond):
            continue
        parts = sorted(
            ((w * foods[fid][0], fid) for fid, w in fly["imitates"] if fid in foods),
            reverse=True,
        )
        if not parts:
            continue
        best, best_food = parts[0]
        score = best + 0.25 * sum(p for p, _ in parts[1:3])
        food = cat.foods[best_food]
        sizes, overlap = recommended_sizes(fly, food)
        if not overlap:
            score *= 0.8  # the fly doesn't come in the size the food runs
        score *= 0.75 + 0.25 * fly["proven"]
        reason = f"Imitates {food['name'].lower()}: " + "; ".join(foods[best_food][1])
        adjust = cond.adjust or {}
        boost = adjust.get("flies", {}).get(fly["id"], 1.0)
        score *= boost
        if boost * adjust.get("foods", {}).get(best_food, 1.0) >= 1.25:
            reason += f"; favored in {adjust.get('name', 'local')} reports"
        results.append({
            "_raw": score,
            "id": fly["id"],
            "name": fly["name"],
            "family": fly["family"],
            "score": round(score, 4),
            "strength": strength_label(score),
            "sizes": size_range_label(sizes),
            "food": best_food,
            "food_name": food["name"],
            "reason": reason,
        })
    # Sort on the unrounded score so the order matches web/engine.js exactly.
    results.sort(key=lambda r: (-r["_raw"], r["name"]))
    if mixed:
        results = mix(results, score=lambda r: r["_raw"])
    for r in results:
        del r["_raw"]
    return results


def mix(ranked: list[dict], places: int = MIXED_PLACES, score=lambda r: r["score"],
        food_repeat: float = FOOD_REPEAT, type_repeat: float = TYPE_REPEAT) -> list[dict]:
    """Reorders a best-first list so one food or fly type can't fill the top places.

    Fishing reports mostly name a kind of fly (midges, streamers, nymphs), so five flies for one hatch
    is a weaker box than the best fly for each of several foods. Each place goes to the fly with the
    best score after the food_repeat and type_repeat cuts for the flies already listed. The scores
    shown don't change, and ties keep the incoming order.
    """
    left, out, food_cut, type_cut = list(ranked), [], {}, {}
    while left and len(out) < places:
        best_i, best_v = 0, -1.0
        for i, r in enumerate(left):
            v = score(r) * food_cut.get(r["food"], 1.0) * type_cut.get(r["family"], 1.0)
            if v > best_v:
                best_i, best_v = i, v
        r = left.pop(best_i)
        out.append(r)
        food_cut[r["food"]] = food_cut.get(r["food"], 1.0) * food_repeat
        type_cut[r["family"]] = type_cut.get(r["family"], 1.0) * type_repeat
    return out + left


def food_shares(foods: dict, cat: Catalog, top: int = 5) -> list[dict]:
    total = sum(a for a, _ in foods.values()) or 1.0
    ranked = sorted(foods.items(), key=lambda kv: -kv[1][0])[:top]
    return [{"id": fid, "name": cat.foods[fid]["name"], "share": round(a / total, 3)} for fid, (a, _) in ranked]
