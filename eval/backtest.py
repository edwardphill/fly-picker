"""Backtest: how often does a fly the fishing report says worked land in our top 5?

    python -m eval.backtest eval/reports_tn.csv            # hatch-chart rules, by river and report kind
    python -m eval.backtest eval/reports_tn.csv --rivers   # also with the trained river adjustments
    TYPESAFE_API_KEY=... python -m eval.backtest eval/reports_tn.csv --jev   # rules vs Jev

Each CSV row is one fishing report (see reports_tn.csv, or reports_template.csv for the minimum
columns). 'flies' lists what the report says worked, separated by ';'. Catalog ids and names match
directly; other phrases go through eval/aliases.json, which maps them to catalog flies, foods or
fly types. Phrases it lists as uncataloged count as catalog gaps: a row whose flies are all gaps
is skipped, since no ranking could hit it.
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flypicker import catalog, rules  # noqa: E402
from flypicker.recommend import _parse, recommend  # noqa: E402

K = 5
ALIASES = Path(__file__).parent / "aliases.json"
FOOD_MATCH = 0.5  # food:<id> matches flies that imitate it at least this well


def load_rows(path) -> list[dict]:
    with open(path, newline="") as fh:
        return [r for r in csv.DictReader(fh) if not (r.get("river") or r.get("region") or "").startswith("#")]


def load_aliases(path=ALIASES) -> dict:
    return json.loads(Path(path).read_text())


def resolve(token: str, cat, aliases: dict) -> set[str]:
    """Fly ids a token matches. See the _about note in aliases.json for the token forms."""
    if token in aliases["groups"]:
        return set().union(*(resolve(t, cat, aliases) for t in aliases["groups"][token]))
    out = set(cat.flies)
    for term in token.split():
        neg, term = term.startswith("!"), term.lstrip("!")
        kind, _, name = term.partition(":")
        if kind == "food" and name in cat.foods:
            match = {fid for fid, f in cat.flies.items() if any(food == name and w >= FOOD_MATCH for food, w in f["imitates"])}
        elif kind == "family" and name in catalog.FLY_TYPES:
            match = {fid for fid, f in cat.flies.items() if f["family"] == name}
        elif term in cat.flies:
            match = {term}
        else:
            raise ValueError(f"aliases.json: unknown token term {term!r}")
        out = out - match if neg else out & match
    return out


def wanted(text: str, cat, aliases: dict) -> tuple[set[str], list[str], list[str]]:
    """(fly ids the report's flies match, uncataloged phrases, unknown phrases)."""
    by_name = {f["name"].lower(): fid for fid, f in cat.flies.items()}
    ids, gaps, unknown = set(), [], []
    for raw in text.split(";"):
        key = " ".join(raw.strip().lower().split())
        if not key:
            continue
        if key in cat.flies or key in by_name:
            ids.add(by_name.get(key, key))
        elif key in aliases["phrases"]:
            for token in aliases["phrases"][key]:
                ids |= resolve(token, cat, aliases)
        elif key in aliases["uncataloged"]:
            gaps.append(key)
        else:
            unknown.append(key)
    return ids, gaps, unknown


def request(row: dict) -> dict:
    req = {k: row[k] for k in ("region", "water_type", "date", "sky", "flow", "fly_type") if row.get(k)}
    if row.get("water_temp_f"):
        req["water_temp_f"] = float(row["water_temp_f"])
    if row.get("windy", "").lower() in ("yes", "true", "1"):
        req["windy"] = True
    return req


def conditions(row: dict, cat, adjust: dict | None = None) -> rules.Conditions:
    cond, _ = _parse(request(row), cat)
    cond.adjust = adjust
    return cond


def top_ids(row: dict, cat, adjust: dict | None = None, mode: str = "rules", k: int = K) -> list[str]:
    if mode == "jev":
        return [f["id"] for f in recommend(request(row), mode="jev")["flies"][:k]]
    return [f["id"] for f in rules.score_flies(cat, conditions(row, cat, adjust))[:k]]


def scorable(rows, cat, aliases) -> list[tuple[dict, set[str]]]:
    """Rows with at least one fly the catalog can represent, paired with the fly ids they accept."""
    out = []
    for row in rows:
        ids, _, unknown = wanted(row["flies"], cat, aliases)
        if unknown:
            raise ValueError(f"{row['date']} {row.get('river', '')}: add these phrases to aliases.json: {unknown}")
        if ids:
            out.append((row, ids))
    return out


def hits(pairs, cat, adjust_for=lambda row: None, mode: str = "rules") -> list[bool]:
    return [bool(ids & set(top_ids(row, cat, adjust_for(row), mode))) for row, ids in pairs]


def rate(flags) -> str:
    return f"{sum(flags) / len(flags):4.0%} ({sum(flags)}/{len(flags)})" if flags else "   - (0)"


def report(pairs, flags, label: str) -> None:
    groups = defaultdict(list)
    for (row, _), hit in zip(pairs, flags):
        river = row.get("river") or "all"
        groups[(river, "all")].append(hit)
        groups[(river, row.get("kind") or "report")].append(hit)
    print(f"{label}: hit rate@{K} = {rate(flags)}")
    for (river, kind), fl in sorted(groups.items()):
        if len(groups) > 2:
            print(f"  {river:12} {kind:7} {rate(fl)}")


def rivers_adjust(row: dict) -> dict | None:
    river = catalog.load().rivers.get(row.get("river", ""))
    return river and river.get("adjust")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--rivers", action="store_true", help="also score with the trained river adjustments")
    ap.add_argument("--jev", action="store_true", help="also score with Jev (needs TYPESAFE_API_KEY)")
    args = ap.parse_args()
    cat, aliases = catalog.load(), load_aliases()
    rows = load_rows(args.csv)
    pairs = scorable(rows, cat, aliases)

    gaps = Counter(g for row in rows for g in wanted(row["flies"], cat, aliases)[1])
    print(f"{len(rows)} reports, {len(pairs)} name at least one fly the catalog covers.")
    if gaps:
        print("Flies the catalog doesn't have (reports naming them):", ", ".join(f"{g} ({n})" for g, n in gaps.most_common()))
    report(pairs, hits(pairs, cat), "Hatch-chart rules")
    if args.rivers:
        report(pairs, hits(pairs, cat, rivers_adjust), "Rules + river adjustments")
        sources = {r.get("trained_on", {}).get("source") for r in cat.rivers.values()}
        if any(src and (ROOT / src).resolve() == Path(args.csv).resolve() for src in sources):
            print("  (The river adjustments were trained on this file, so that line is not a fair test. "
                  "python -m eval.train holds out the newest reports.)")
    if args.jev:
        report(pairs, hits(pairs, cat, mode="jev"), "Jev")


if __name__ == "__main__":
    main()
