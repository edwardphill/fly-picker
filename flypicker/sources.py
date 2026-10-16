"""The fishing reports behind a pick: links to the reports that named a fly, or called for its kind.

The data is flypicker/data/sources.json, built from eval/reports_*.csv by `python -m eval.sources`.
web/engine.js has the same logic for the offline demo (checked by scripts/check_parity.py).
"""

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).parent / "data" / "sources.json"
FOOD_MATCH = 0.5  # food:<id> stands for flies that imitate it at least this well (as in eval/backtest.py)
SHOWN = 12  # most citations returned per fly


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(PATH.read_text())


def matches(token: str, fly: dict) -> bool:
    for term in token.split():
        neg, term = term.startswith("!"), term.lstrip("!")
        kind, _, name = term.partition(":")
        if kind == "food":
            hit = any(food == name and w >= FOOD_MATCH for food, w in fly["imitates"])
        elif kind == "family":
            hit = fly["family"] == name
        else:
            hit = fly["id"] == term
        if hit == neg:
            return False
    return True


def _months_apart(a: int, b: int) -> int:
    d = abs(a - b) % 12
    return min(d, 12 - d)


def cite(fly: dict, region: str, month: int, river: str | None = None) -> dict:
    """Reports from this region that recommended this fly, best first; how many, and how many by name.

    Order: reports that named the pattern before ones that named its kind ("streamers"), then
    reports from within a month of the date, then this river's own, then the newest.
    """
    data = load()
    found = []
    for s in data["sources"]:
        if s["region"] != region:
            continue
        pick = next((p for p in sorted(s["picks"], key=lambda p: not p["named"])
                     if any(matches(t, fly) for t in p["match"])), None)
        if pick is None:
            continue
        in_season = _months_apart(int(s["date"][5:7]), month) <= 1
        found.append(((pick["named"], in_season, s["place"] == river, s["date"]), {
            "site": s["site"], "url": s["url"], "date": s["date"], "kind": s["kind"],
            "place": data["places"][s["place"]], "said": pick["said"], "named": pick["named"],
        }))
    found.sort(key=lambda x: x[0], reverse=True)
    return {"total": len(found), "named": sum(c["named"] for _, c in found), "items": [c for _, c in found[:SHOWN]]}


def region_has_sources(region: str) -> bool:
    return any(s["region"] == region for s in load()["sources"])
