"""Loads the fly catalog, food hatch chart, water data and river presets, expanding water groups."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import my_flies

DATA_DIR = Path(__file__).parent / "data"
MY_FLIES = DATA_DIR / "my_flies.csv"  # your own patterns, added on top of flies.json

FLY_TYPES = {
    "any": "Any fly",
    "dry": "Dry fly",
    "emerger": "Emerger",
    "nymph": "Nymph",
    "wet": "Wet fly / soft hackle",
    "streamer": "Streamer",
    "topwater": "Popper / topwater",
    "flats": "Flats (shrimp and crab)",
}

SKIES = ("sunny", "partly", "overcast", "rain")
FLOWS = ("low", "normal", "high")


@dataclass(frozen=True)
class Catalog:
    regions: dict
    water_types: dict
    typical_temp: dict
    foods: dict  # id -> food, with "water" expanded to concrete water types
    flies: dict  # id -> fly, with "water" expanded to a set of water types
    rivers: dict  # id -> home-river preset (region, water type, location, learned adjustments)


def _groups(water_types: dict) -> dict:
    groups: dict[str, list[str]] = {}
    for wid, w in water_types.items():
        groups.setdefault(w["group"], []).append(wid)
    return groups


def _expand_weights(spec: dict, groups: dict) -> dict:
    """Group keys apply first so a specific water type can override its group."""
    out: dict[str, float] = {}
    for key, mult in spec.items():
        if key in groups:
            for wid in groups[key]:
                out.setdefault(wid, mult)
    for key, mult in spec.items():
        if key not in groups:
            out[key] = mult
    return out


def _expand_list(items: list, groups: dict) -> frozenset:
    out: set[str] = set()
    for key in items:
        out.update(groups.get(key, [key]))
    return frozenset(out)


@lru_cache(maxsize=1)
def load() -> Catalog:
    waters = json.loads((DATA_DIR / "waters.json").read_text())
    foods_raw = json.loads((DATA_DIR / "foods.json").read_text())["foods"]
    flies_raw = json.loads((DATA_DIR / "flies.json").read_text())["flies"]
    rivers = json.loads((DATA_DIR / "rivers.json").read_text())["rivers"]
    entomology = json.loads((DATA_DIR / "entomology.json").read_text())["foods"]
    groups = _groups(waters["water_types"])
    flies_raw += my_flies.load(MY_FLIES, foods_raw, set(groups) | set(waters["water_types"]),
                               {f["id"] for f in flies_raw}, FLY_TYPES)

    foods = {}
    for f in foods_raw:
        if f["id"] not in entomology:
            raise ValueError(f"Food {f['id']} has no entry in entomology.json")
        foods[f["id"]] = {**f, **entomology[f["id"]], "water": _expand_weights(f["water"], groups)}
    if set(entomology) - set(foods):
        raise ValueError(f"entomology.json names unknown foods: {sorted(set(entomology) - set(foods))}")
    flies = {}
    for f in flies_raw:
        for food_id, _ in f["imitates"]:
            if food_id not in foods:
                raise ValueError(f"Fly {f['id']} imitates unknown food {food_id}")
        flies[f["id"]] = {**f, "water": _expand_list(f["water"], groups)}
    for rid, r in rivers.items():
        adj = r.get("adjust", {})
        unknown = [k for k in adj.get("foods", {}) if k not in foods] + [k for k in adj.get("flies", {}) if k not in flies]
        if r["region"] not in waters["regions"] or r["water_type"] not in waters["water_types"] or unknown:
            raise ValueError(f"River {rid} has an unknown region, water type, food or fly: {unknown}")
        for note in r.get("hatch_notes", []):
            if not note["text"] or not note["months"] or not set(note["months"]) <= set(range(1, 13)):
                raise ValueError(f"River {rid} has a hatch note without text or with bad months: {note}")

    return Catalog(
        regions=waters["regions"],
        water_types=waters["water_types"],
        typical_temp=waters["typical_temp_f"],
        foods=foods,
        flies=flies,
        rivers=rivers,
    )


def hook_label(n: int) -> str:
    """Hook numbers: positive is #n, 0 is 1/0, -1 is 2/0, and so on."""
    return f"{1 - n}/0" if n <= 0 else f"#{n}"


def size_range_label(sizes) -> str:
    big, small = sizes
    if big == small:
        return hook_label(big)
    if big > 0:
        return f"#{big}–{small}"
    return f"{hook_label(big)}–{hook_label(small)}"
