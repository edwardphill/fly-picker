"""The Hatching now section: entomology data, river notes, and the status rules in web/engine.js."""

import json
import shutil
import subprocess

import pytest

from flypicker import catalog
from scripts.build_page import ROOT, page_data

KINDS = {"mayfly", "caddis", "stonefly", "midge", "terrestrial", "other insect", "crustacean", "baitfish", "other"}

NODE = """
const fs = require("fs");
global.DATA = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const FP = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(c => {
  const cond = FP.conditions(c);
  return { hatch: FP.hatching(cond, FP.activeFoods(cond)), chart: FP.hatchChart(cond.region, cond.water_type) };
})));
"""


def test_every_food_has_entomology():
    for fid, food in catalog.load().foods.items():
        assert food["kind"] in KINDS, fid
        assert food["latin"] and food["stages"] and food["time_of_day"] and food["tip"], fid


def test_river_notes_name_their_source():
    for rid, river in catalog.load().rivers.items():
        for note in river.get("hatch_notes", []):
            assert note["source"] and note["date"], rid
            assert note["url"] is None or note["url"].startswith("https://"), rid


@pytest.fixture(scope="module")
def hatch(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("needs node on PATH")
    data = tmp_path_factory.mktemp("page") / "data.json"
    data.write_text(json.dumps(page_data()))

    def run(region, water_type, date, **extra):
        case = dict(region=region, water_type=water_type, date=date, **extra)
        out = subprocess.run(["node", "-e", NODE, str(data), str(ROOT / "web" / "engine.js")],
                             input=json.dumps([case]), capture_output=True, text=True, check=True).stdout
        return json.loads(out)[0]
    return run


def rows(result):
    h = result["hatch"]
    return {r["id"]: r for r in h["insects"] + h["others"]}


def test_status_follows_the_hatch_chart(hatch):
    # Northeast Hendricksons: on in May, peak in June. Sulfurs: peak in June, on in July.
    assert rows(hatch("northeast", "freestone", "2026-05-20"))["hendrickson"]["status"] == "starting"
    assert rows(hatch("northeast", "freestone", "2026-06-10"))["hendrickson"]["status"] == "peak"
    assert rows(hatch("northeast", "freestone", "2026-07-10"))["sulfur"]["status"] == "winding_down"
    april = hatch("northeast", "freestone", "2026-04-20")
    assert "hendrickson" not in rows(april) and "hendrickson" in {r["id"] for r in april["hatch"]["next"]}


def test_rows_are_sorted_and_split(hatch):
    result = hatch("west", "freestone", "2026-10-15")
    insects, others = result["hatch"]["insects"], result["hatch"]["others"]
    assert [r["activity"] for r in insects] == sorted((r["activity"] for r in insects), reverse=True)
    assert all(r["insect"] for r in insects) and not any(r["insect"] for r in others)
    assert rows(result)["bwo"]["status"] == "peak" and rows(result)["bwo"]["latin"] == "Baetis spp."
    assert "sculpin" in {r["id"] for r in others}


def test_cold_water_is_flagged(hatch):
    bwo = rows(hatch("west", "freestone", "2026-11-05", water_temp_f=36))["bwo"]
    assert bwo["temp_note"] == "water's cold for them (40 to 58°F)"


def test_regions_without_a_food_leave_it_out(hatch):
    assert "smelt" not in rows(hatch("south", "tailwater", "2026-04-15"))
    assert "smelt" in rows(hatch("northeast", "tailwater", "2026-05-15"))


def test_year_chart(hatch):
    chart = {r["id"]: r for r in hatch("west", "freestone", "2026-10-15")["chart"]}
    assert chart["bwo"]["months"][9] == "peak" and len(chart["bwo"]["months"]) == 12
    assert "chironomid" not in chart  # a lake food
