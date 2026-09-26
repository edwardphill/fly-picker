"""Scores flies with Jev (TypeSafe AI's System One model).

One request asks a Choice ("what are the fish eating?") plus a Noul per candidate fly
("would this fly catch fish here?"). Jev answers every question in parallel and returns
probabilities. Candidates are split across a few concurrent requests in case the API
limits questions per call; FLYPICKER_JEV_CHUNK sets the split size.

Needs TYPESAFE_API_KEY. Without it, recommend.py uses the hatch-chart rules instead.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from typesafe_sdk import Choice, Noul, TypeSafeClient

from .catalog import Catalog, size_range_label
from .rules import MONTHS, Conditions, food_activity, season_level, strength_label

CHUNK = int(os.environ.get("FLYPICKER_JEV_CHUNK", "24"))
NOUL_WEIGHT = 0.6  # the rest comes from how likely the fly's food is, per Jev's Choice answer


def available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())


def build_state(cat: Catalog, cond: Conditions, foods: dict) -> dict:
    temp = cond.resolved_temp(cat)
    water = cat.water_types[cond.water_type]
    hatch = sorted(foods.items(), key=lambda kv: -kv[1][0])[:8]
    return {
        "place": {
            "name": cond.place or None,
            "region": cat.regions[cond.region],
            "water_type": water["name"],
            "target_fish": water["fish"],
        },
        "month": MONTHS[cond.month - 1],
        "water_temp_f": round(temp),
        "water_temp_source": {"gauge": "live stream gauge", "angler": "angler's reading"}.get(cond.temp_source, "typical for the month"),
        "flow": cond.flow,
        "sky": cond.sky,
        "windy": cond.windy,
        "hatch_chart": [
            {"food": cat.foods[fid]["name"], "status": season_level(cat.foods[fid], cond.region, cond.month)[1]}
            for fid, _ in hatch
        ],
    }


def food_question(cat: Catalog, food_ids: list[str]) -> Choice:
    return Choice(
        instructions="What are the fish most likely feeding on in these conditions?",
        criteria={fid: cat.foods[fid]["desc"] for fid in food_ids},
    )


def fly_question(cat: Catalog, fly: dict) -> Noul:
    imitates = ", ".join(cat.foods[fid]["name"].lower() for fid, _ in fly["imitates"][:3])
    return Noul(
        instructions=(
            f"Would a {fly['name']} ({fly['family']} fly, sizes {size_range_label(fly['sizes'])}, "
            f"imitating {imitates}) catch fish in these conditions today?"
        ),
        criteria={"true": "Likely to draw strikes today", "false": "Unlikely to work today"},
    )


def score_flies(cat: Catalog, cond: Conditions, candidates: list[dict], foods: dict,
                client: TypeSafeClient | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (ranked flies, food probabilities). `candidates` are rules results, best first."""
    state = build_state(cat, cond, foods)
    food_ids = sorted(foods, key=lambda fid: -foods[fid][0])
    chunks = [candidates[i:i + CHUNK] for i in range(0, len(candidates), CHUNK)] or [[]]

    def ask(i_chunk):
        i, chunk = i_chunk
        questions = {f"fly__{c['id']}": fly_question(cat, cat.flies[c["id"]]) for c in chunk}
        if i == 0:
            questions["food"] = food_question(cat, food_ids)
        return client.system_one(state=state, questions=questions)

    own_client = client is None
    client = client or TypeSafeClient()
    try:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            responses = list(pool.map(ask, enumerate(chunks)))
    finally:
        if own_client:
            client.close()

    food_p = responses[0].choices["food"].probabilities
    nouls = {}
    for r in responses:
        for name, ans in r.nouls.items():
            nouls[name.removeprefix("fly__")] = ans.noul

    top_p = max(food_p.values(), default=0) or 1.0
    temp = cond.resolved_temp(cat)
    ranked = []
    for c in candidates:
        fly = cat.flies[c["id"]]
        food_fit, best_food = max((w * food_p.get(fid, 0.0), fid) for fid, w in fly["imitates"])
        noul = nouls.get(c["id"], 0.0)
        score = NOUL_WEIGHT * noul + (1 - NOUL_WEIGHT) * food_fit / top_p
        notes = food_activity(cat.foods[best_food], cond, temp)[1]
        ranked.append({
            **c,
            "rules_score": c["score"],
            "score": round(score, 4),
            "jev_noul": round(noul, 3),
            "strength": strength_label(score * 1.6),
            "food": best_food,
            "food_name": cat.foods[best_food]["name"],
            "reason": (f"Jev: {noul:.0%} likely to draw strikes; fish most likely eating "
                       f"{cat.foods[best_food]['name'].lower()} ({food_p.get(best_food, 0):.0%})"
                       + (f"; {'; '.join(notes)}" if notes else "")),
        })
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    shares = [{"id": fid, "name": cat.foods[fid]["name"], "share": round(p, 3)}
              for fid, p in sorted(food_p.items(), key=lambda kv: -kv[1])[:5]]
    return ranked, shares
