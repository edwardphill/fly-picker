"""What to fish: two or three flies and a straight answer on dry flies.

The ranked list is long on purpose, but nobody ties on ten flies. This narrows it:

  * A river with a plan in rivers.json (hand-checked against local reports and shop hatch calendars)
    uses it for every month, whenever the fly type is "Any fly".
  * Any other water gets the same kind of answer from the ranking: two or three flies spread across
    foods and kinds, with dries ruled out unless something is on the surface that month.

The dries call comes from the hatch chart. "yes" needs a hatch or terrestrial at full strength at
this water temperature; olives and tricos alone only earn "hatch-only" (a dry works for an hour or
two a day, not all month); anything fainter is "no". It only applies to trout water.

web/engine.js has the same logic for the offline demo (checked by scripts/check_parity.py).
"""

from . import rules, sources

DRY_YES = 0.9
DRY_MAYBE = 0.5
MAX_PICKS = 3
NOT_FOR_DRIES = ("mouse", "frog", "topwater_bug", "worm_hatch")  # surface foods you don't match with a dry fly
NARROW_WINDOW = ("bwo", "trico")  # tiny mayflies: a dry works for a window, not all month
SURFACE_FAMILIES = ("dry", "topwater")


def surface_foods(cat, foods: dict) -> list[dict]:
    """Foods on the surface this month, most active first."""
    out = [{"id": fid, "name": cat.foods[fid]["name"], "a": a}
           for fid, (a, _) in foods.items()
           if cat.foods[fid]["stage"] == "surface" and fid not in NOT_FOR_DRIES]
    return sorted(out, key=lambda f: -f["a"])


def dries_call(cat, cond: rules.Conditions, foods: dict) -> dict | None:
    """{'verdict': 'yes' | 'hatch-only' | 'no', 'text': ..., 'a': activity}, or None off trout water."""
    if cat.water_types[cond.water_type]["fish"] != "trout":
        return None
    top, month = surface_foods(cat, foods), rules.MONTHS[cond.month - 1]
    solid = [f for f in top if f["id"] not in NARROW_WINDOW]
    narrow = [f for f in top if f["id"] in NARROW_WINDOW]
    s = solid[0]["a"] if solid else 0
    n = narrow[0]["a"] if narrow else 0
    best = max(s, n)
    names = " and ".join(f["name"].lower() for f in top[:2])
    if s >= DRY_YES:
        return {"verdict": "yes", "text": f"{names[:1].upper()}{names[1:]} are on the surface in {month}.", "a": s}
    if best >= DRY_MAYBE:
        return {"verdict": "hatch-only", "a": best,
                "text": f"Surface food is only partly on in {month} ({names}). "
                        "Tie on a dry only when you see fish rising; otherwise fish under the surface."}
    return {"verdict": "no", "a": best,
            "text": f"Nothing on the hatch chart is reliably on the surface in {month} at this water temperature. "
                    "Fish under the surface and leave the dries in the box."}


def plan_for(river: dict | None, month: int) -> dict | None:
    for entry in (river or {}).get("plan", []):
        if month in entry["months"]:
            return entry
    return None


def advise(cat, cond: rules.Conditions, ranked: list[dict], river_id: str | None = None) -> dict:
    """ranked is the full best-first list from rules.score_flies (or the Jev rescoring of it)."""
    river = cat.rivers.get(river_id) if river_id else None
    month = rules.MONTHS[cond.month - 1]
    entry = plan_for(river, cond.month) if cond.fly_type == "any" else None
    if entry:
        return {
            "kind": "plan", "where": river["name"], "month": month,
            "dries": {"verdict": entry["dries"], "text": entry["dries_text"]},
            "picks": [{"id": p["fly"], "name": cat.flies[p["fly"]]["name"], "family": cat.flies[p["fly"]]["family"],
                       "sizes": p["size"], "why": p["why"]} for p in entry["picks"]],
            "src": entry.get("src", []), "facts": river.get("facts", []),
        }

    call = dries_call(cat, cond, rules.active_foods(cat, cond))
    want_dry = cond.fly_type in ("dry", "topwater")
    picks, seen_food, seen_family = [], set(), {}

    def pick(f: dict) -> dict:
        return {"id": f["id"], "name": f["name"], "family": f["family"], "sizes": f["sizes"], "why": f["reason"],
                "sources": sources.cite(cat.flies[f["id"]], cond.region, cond.month, river_id)}

    for f in ranked:
        if len(picks) >= MAX_PICKS:
            break
        if f["strength"] == "long shot":
            continue
        surface = f["family"] in SURFACE_FAMILIES
        if surface and call and call["verdict"] == "no" and not want_dry:
            continue
        if surface and any(p["family"] in SURFACE_FAMILIES for p in picks) and not (call and call["verdict"] == "yes"):
            continue
        if f["food"] in seen_food or seen_family.get(f["family"], 0) >= 2:
            continue
        seen_food.add(f["food"])
        seen_family[f["family"]] = seen_family.get(f["family"], 0) + 1
        picks.append(pick(f))

    # When dries are worth fishing, one of the flies should be a dry.
    if call and call["verdict"] == "yes" and not any(p["family"] in SURFACE_FAMILIES for p in picks):
        dry = next((f for f in ranked if f["family"] in SURFACE_FAMILIES and f["strength"] != "long shot"), None)
        if dry:
            if len(picks) >= MAX_PICKS:
                picks[MAX_PICKS - 1] = pick(dry)
            else:
                picks.append(pick(dry))

    dries = {"verdict": call["verdict"], "text": call["text"]} if call else None
    if dries and want_dry and dries["verdict"] == "no":
        dries["text"] += " You asked for dry flies, so these are the best of them, but expect little."
    return {"kind": "model", "where": river["name"] if river else None, "month": month, "dries": dries,
            "picks": picks, "src": [], "facts": river.get("facts", []) if river else []}
