"""Reads your own flies from a spreadsheet-style CSV (flypicker/data/my_flies.csv).

Only name, type and imitates are required. Columns:

    name      Fly name, e.g. "Kenny (black)". Must not repeat a fly already in the catalog.
    type      dry, emerger, nymph, wet, streamer, topwater or flats.
    imitates  Foods it imitates, separated by ";". Each may carry a 0-1 match after ":",
              e.g. "caddis:0.7; sowbug" (0.8 when left off). Food ids or names both work.
    sizes     Hook sizes, e.g. "12-16", "14", or "2/0-4". Blank: the first food's sizes.
    water     Water types or groups separated by ";", e.g. "tailwater; LAKE".
              Blank: wherever its foods live.
    proven    0-1, how much you trust it. Blank: 0.7.
    notes     Anything; ignored by the ranking.
"""

import csv
import re
from pathlib import Path

DEFAULT_WEIGHT = 0.8
DEFAULT_PROVEN = 0.7


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def hook_number(text: str) -> int:
    """'14' -> 14, '#14' -> 14, '1/0' -> 0, '2/0' -> -1 (the catalog's numbering)."""
    text = text.strip().lstrip("#")
    try:
        return 1 - int(text[:-2]) if text.endswith("/0") else int(text)
    except ValueError:
        raise ValueError(f"size {text!r} should be a hook number like 14 or 2/0") from None


def parse_sizes(text: str) -> list[int]:
    parts = [p for p in re.split(r"\s*(?:-|–|to)\s*", text.strip()) if p]
    nums = [hook_number(p) for p in parts]
    if len(nums) not in (1, 2):
        raise ValueError(f"sizes {text!r} should look like 12-16, 14 or 2/0-4")
    return [min(nums), max(nums)]  # [largest hook, smallest hook]


def load(path: Path, foods: list[dict], waters: set, taken: set, fly_types: dict) -> list[dict]:
    if not path.exists():
        return []
    by_key = {}
    for f in foods:
        by_key[f["id"]] = f
        by_key[slug(f["name"])] = f
    types = {t for t in fly_types if t != "any"}

    flies = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row_no, row in enumerate(csv.DictReader(fh), start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not row.get("name") or row["name"].startswith("#"):
                continue
            try:
                flies.append(_fly(row, by_key, waters, taken, types))
            except (ValueError, KeyError) as e:
                raise ValueError(f"{path.name} row {row_no} ({row['name']}): {e}") from None
            taken.add(flies[-1]["id"])
    return flies


def _fly(row: dict, by_key: dict, waters: set, taken: set, types: set) -> dict:
    fid = slug(row["name"])
    if fid in taken:
        raise ValueError(f"a fly with id {fid!r} already exists; give it a different name")
    family = row.get("type", "").lower()
    if family not in types:
        raise ValueError(f"type {family!r} should be one of {', '.join(sorted(types))}")

    imitates = []
    for part in filter(None, (p.strip() for p in row.get("imitates", "").split(";"))):
        key, _, weight = part.partition(":")
        food = by_key.get(key.strip()) or by_key.get(slug(key))
        if food is None:
            raise ValueError(f"unknown food {key.strip()!r}; see the food list in flypicker/data/foods.json")
        w = float(weight) if weight.strip() else DEFAULT_WEIGHT
        if not 0 < w <= 1:
            raise ValueError(f"match for {key.strip()!r} should be between 0 and 1")
        imitates.append([food["id"], w])
    if not imitates:
        raise ValueError("imitates is empty; name at least one food")
    imitates.sort(key=lambda p: -p[1])
    first = by_key[imitates[0][0]]

    sizes = parse_sizes(row["sizes"]) if row.get("sizes") else list(first["sizes"])
    if row.get("water"):
        water = [w.strip() for w in row["water"].split(";") if w.strip()]
        bad = [w for w in water if w not in waters]
        if bad:
            raise ValueError(f"unknown water {', '.join(bad)}; use {', '.join(sorted(waters))}")
    else:
        water = sorted({w for fid, _ in imitates for w in by_key[fid]["water"]})
    proven = float(row["proven"]) if row.get("proven") else DEFAULT_PROVEN
    if not 0 <= proven <= 1:
        raise ValueError("proven should be between 0 and 1")

    return {"id": fid, "name": row["name"], "family": family, "sizes": sizes, "water": water,
            "proven": proven, "imitates": imitates, "source": "my_flies"}
