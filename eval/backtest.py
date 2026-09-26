"""Backtest: how often do the flies a fishing report names land in our top 5?

    python -m eval.backtest eval/reports.csv              # rules only
    TYPESAFE_API_KEY=... python -m eval.backtest eval/reports.csv --jev   # rules vs Jev

Each CSV row is one fishing report (see reports_template.csv). 'flies' lists the flies the
report says worked, separated by ';', using catalog ids or names. This is the test to run
before trusting Jev's rankings: it compares Jev against plain hatch-chart rules on real reports.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flypicker import catalog  # noqa: E402
from flypicker.recommend import recommend  # noqa: E402

K = 5


def fly_ids(text: str, cat) -> set[str]:
    by_name = {f["name"].lower(): fid for fid, f in cat.flies.items()}
    out = set()
    for raw in text.split(";"):
        key = raw.strip().lower()
        if key in cat.flies:
            out.add(key)
        elif key in by_name:
            out.add(by_name[key])
        elif key:
            print(f"  unknown fly in report, skipped: {raw.strip()!r}", file=sys.stderr)
    return out


def hit_rate(rows, mode: str, cat) -> tuple[float, int]:
    hits = total = 0
    for row in rows:
        wanted = fly_ids(row["flies"], cat)
        if not wanted:
            continue
        req = {k: row[k] for k in ("region", "water_type", "date") if row.get(k)}
        for k in ("sky", "flow", "fly_type"):
            if row.get(k):
                req[k] = row[k]
        if row.get("water_temp_f"):
            req["water_temp_f"] = float(row["water_temp_f"])
        top = [f["id"] for f in recommend(req, mode=mode)["flies"][:K]]
        hits += bool(wanted & set(top))
        total += 1
    return (hits / total if total else 0.0), total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--jev", action="store_true", help="also score with Jev (needs TYPESAFE_API_KEY)")
    args = ap.parse_args()
    cat = catalog.load()
    with open(args.csv, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if not r.get("region", "").startswith("#")]

    rate, n = hit_rate(rows, "rules", cat)
    print(f"Hatch-chart rules: hit rate@{K} = {rate:.0%} over {n} reports")
    if args.jev:
        rate, n = hit_rate(rows, "jev", cat)
        print(f"Jev:               hit rate@{K} = {rate:.0%} over {n} reports")


if __name__ == "__main__":
    main()
