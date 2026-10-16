"""Builds flypicker/data/sources.json: the fishing reports behind each fly, with links.

    python -m eval.sources      # after editing eval/reports_*.csv or eval/aliases.json

Every report row that names flies becomes a source the app can cite. Each fly phrase keeps the
words the report used ("pearl zonker", "streamers") and the alias tokens it maps to, so a pick can
link to the reports that named it, or that called for its kind of fly. Phrases aliases.json lists
as uncataloged are left out, since no fly in the catalog stands for them.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.backtest import load_aliases, load_rows  # noqa: E402
from flypicker import catalog  # noqa: E402

REPORTS = sorted((ROOT / "eval").glob("reports_*.csv"))
OUT = ROOT / "flypicker" / "data" / "sources.json"
# Report places that aren't home-river presets.
PLACES = {
    "rangeley_region": "Rangeley region", "rangeley_river": "Rangeley River", "maine_statewide": "Maine",
    "saco": "Saco River", "rapid": "Rapid River", "upper_connecticut": "Upper Connecticut",
    "kennebago": "Kennebago River", "androscoggin_nh": "Androscoggin (NH)",
}


def expand(token: str, aliases: dict) -> list[str]:
    """A token with its groups expanded, so the app needs only fly ids, food: and family: terms."""
    if token in aliases["groups"]:
        return [t for g in aliases["groups"][token] for t in expand(g, aliases)]
    return [token]


def picks(text: str, cat, aliases: dict) -> list[dict]:
    by_name = {f["name"].lower(): fid for fid, f in cat.flies.items()}
    out = []
    for raw in text.split(";"):
        key = " ".join(raw.strip().lower().split())
        if not key or key in aliases["uncataloged"]:
            continue
        if key in cat.flies or key in by_name:
            tokens = [by_name.get(key, key)]
        elif key in aliases["phrases"]:
            tokens = [t for tok in aliases["phrases"][key] for t in expand(tok, aliases)]
        else:
            raise ValueError(f"add {key!r} to eval/aliases.json")
        out.append({"said": raw.strip(), "match": tokens, "named": all(t in cat.flies for t in tokens)})
    return out


def build() -> dict:
    cat, aliases = catalog.load(), load_aliases()
    places = {**PLACES, **{k: v["name"] for k, v in cat.rivers.items()}}
    sources = []
    for path in REPORTS:
        for row in load_rows(path):
            if not row.get("url") or not row.get("flies", "").strip():
                continue
            found = picks(row["flies"], cat, aliases)
            if not found:
                continue
            if row["river"] not in places:
                raise ValueError(f"{path.name}: add a label for {row['river']!r} to PLACES in eval/sources.py")
            sources.append({
                "place": row["river"], "region": row["region"], "date": row["date"],
                "kind": row.get("kind") or "report", "site": row["source"], "url": row["url"], "picks": found,
            })
    sources.sort(key=lambda s: (s["date"], s["url"]), reverse=True)
    return {
        "_about": "Built by `python -m eval.sources` from eval/reports_*.csv and eval/aliases.json; don't edit by hand. "
                  "Each source is a fishing report or trip write-up and the flies it said to use. 'said' is the report's "
                  "own words; 'match' is the catalog flies it stands for (a fly id, food:<id> for flies imitating that food "
                  "at 0.5 or more, family:<type>; terms joined by spaces must all match, ! excludes). 'named' means the "
                  "report named the pattern itself rather than a kind of fly.",
        "places": {k: places[k] for k in sorted({s["place"] for s in sources})},
        "sources": sources,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    data = build()
    OUT.write_text(render(data))
    named = sum(p["named"] for s in data["sources"] for p in s["picks"])
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(data['sources'])} reports, "
          f"{sum(len(s['picks']) for s in data['sources'])} fly mentions ({named} name a catalog pattern)")
