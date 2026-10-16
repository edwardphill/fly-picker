"""Checks that web/engine.js ranks flies the same as flypicker/rules.py.

    python -m scripts.check_parity      # needs node on PATH
"""

import itertools
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flypicker import catalog, rules, sources  # noqa: E402
from scripts.build_page import page_data  # noqa: E402

NODE = """
const fs = require("fs");
global.DATA = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const FP = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map(c => {
  const foods = FP.activeFoods(c);
  return FP.scoreFlies(c, foods).map(f => [f.id, f.score, f.sizes, f.reason]);
});
process.stdout.write(JSON.stringify(out));
"""

NODE_SOURCES = """
const fs = require("fs");
global.DATA = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const FP = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(([fid, region, month, river]) => FP.citations(DATA.flies[fid], region, month, river))));
"""


# Checks the JS port of learned river adjustments even when no preset carries any.
SAMPLE_ADJUST = {"name": "Sample River", "foods": {"leech": 2.0, "midge": 0.7, "sculpin": 1.4},
                 "flies": {"woolly_bugger": 1.6, "zebra_midge": 0.8}}


def cases(cat):
    for region, water, month, fly_type, sky, windy, flow, temp in itertools.product(
        cat.regions, cat.water_types, range(1, 13), ["any", "dry", "nymph", "streamer"],
        ["partly", "overcast"], [False, True], ["normal", "high"], [None, 61],
    ):
        yield dict(region=region, water_type=water, month=month, fly_type=fly_type,
                   sky=sky, windy=windy, flow=flow, water_temp_f=temp)
    # Home rivers, with their learned adjustments (or the sample set).
    for river, month, fly_type, sky, flow in itertools.product(
        cat.rivers.values(), range(1, 13), ["any", "dry", "nymph", "streamer"],
        ["partly", "overcast", "rain"], ["low", "normal", "high"],
    ):
        yield dict(region=river["region"], water_type=river["water_type"], month=month, fly_type=fly_type,
                   sky=sky, windy=False, flow=flow, water_temp_f=None, adjust=river.get("adjust") or SAMPLE_ADJUST)


def source_cases(cat):
    """Every fly, every month, in each region with reports, with and without each of its rivers."""
    regions = {s["region"] for s in sources.load()["sources"]}
    for region in sorted(regions):
        for river in [None] + [k for k, r in cat.rivers.items() if r["region"] == region]:
            for month in range(1, 13):
                for fid in cat.flies:
                    yield [fid, region, month, river]


def run_node(script: str, cases: list) -> list:
    data_path = ROOT / "dist" / "parity-data.json"
    data_path.parent.mkdir(exist_ok=True)
    data_path.write_text(json.dumps(page_data()))
    try:
        return json.loads(subprocess.run(
            ["node", "-e", script, str(data_path), str(ROOT / "web" / "engine.js")],
            input=json.dumps(cases), capture_output=True, text=True, check=True,
        ).stdout)
    finally:
        data_path.unlink()


def check_sources(cat) -> int:
    all_cases = list(source_cases(cat))
    js = run_node(NODE_SOURCES, all_cases)
    mismatches = 0
    for (fid, region, month, river), js_cites in zip(all_cases, js):
        if sources.cite(cat.flies[fid], region, month, river) != js_cites:
            mismatches += 1
            if mismatches <= 3:
                print("SOURCES MISMATCH", fid, region, month, river)
    print(f"{len(all_cases)} fly citation lists compared, {mismatches} mismatches")
    return mismatches


def main() -> int:
    cat = catalog.load()
    all_cases = list(cases(cat))
    js = run_node(NODE, all_cases)

    mismatches = 0
    for case, js_rows in zip(all_cases, js):
        py = rules.score_flies(cat, rules.Conditions(**case))
        py_rows = [[f["id"], f["score"], f["sizes"], f["reason"]] for f in py]
        same = (len(py_rows) == len(js_rows) and all(
            p[0] == j[0] and abs(p[1] - j[1]) < 2e-4 and p[2] == j[2] and p[3] == j[3]
            for p, j in zip(py_rows, js_rows)))
        if not same:
            mismatches += 1
            if mismatches <= 3:
                i = next((k for k, (p, j) in enumerate(zip(py_rows, js_rows)) if p != j and not (p[0] == j[0] and abs(p[1] - j[1]) < 2e-4 and p[2:] == j[2:])), min(len(py_rows), len(js_rows)))
                print("MISMATCH", case, "\n  py:", py_rows[i:i + 2], "\n  js:", js_rows[i:i + 2])
    print(f"{len(all_cases)} condition sets compared, {mismatches} mismatches")
    mismatches += check_sources(cat)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
