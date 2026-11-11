"""What to fish: river plans, the dries call, and the 2-3 fly answer for every other water."""

import json
import shutil
import subprocess

import pytest

from flypicker import advise, catalog, rules
from flypicker.recommend import recommend
from scripts.build_page import ROOT, page_data

SURFACE = ("dry", "topwater")
TROUT = [w for w, v in catalog.load().water_types.items() if v["fish"] == "trout"]


def cond(region, water, month, fly_type="any", **kw):
    return rules.Conditions(region, water, month, fly_type=fly_type, **kw)


def answer(region, water, month, fly_type="any", river=None, **kw):
    cat = catalog.load()
    c = cond(region, water, month, fly_type, **kw)
    return advise.advise(cat, c, rules.score_flies(cat, c), river)


def test_every_plan_names_two_or_three_catalog_flies_for_every_month():
    cat = catalog.load()
    planned = {rid: r for rid, r in cat.rivers.items() if "plan" in r}
    assert {"caney_fork", "elk", "tellico", "hiwassee", "south_holston", "watauga"} <= set(planned)
    for rid, river in planned.items():
        months = sorted(m for p in river["plan"] for m in p["months"])
        assert months == list(range(1, 13)), rid
        for p in river["plan"]:
            assert len(p["picks"]) in (2, 3) and p["src"], (rid, p["months"])
            assert all(k["fly"] in cat.flies for k in p["picks"])


def test_a_plan_never_contradicts_its_own_dries_call():
    cat = catalog.load()
    for rid, river in cat.rivers.items():
        for p in river.get("plan", []):
            surface = [cat.flies[k["fly"]]["family"] in SURFACE for k in p["picks"]]
            if p["dries"] == "no":
                assert not any(surface), (rid, p["months"])  # a "leave the dries home" card names no dry
            if p["dries"] == "yes":
                assert any(surface), (rid, p["months"])


def test_a_river_with_a_plan_answers_from_it_every_month():
    cat = catalog.load()
    for rid in ("tellico", "hiwassee", "south_holston", "watauga", "caney_fork", "elk"):
        river = cat.rivers[rid]
        for month in range(1, 13):
            a = answer(river["region"], river["water_type"], month, river=rid)
            entry = advise.plan_for(river, month)
            assert a["kind"] == "plan" and a["where"] == river["name"] and a["month"] == rules.MONTHS[month - 1]
            assert [p["id"] for p in a["picks"]] == [k["fly"] for k in entry["picks"]]
            assert a["dries"] == {"verdict": entry["dries"], "text": entry["dries_text"]}
            assert a["src"] == entry["src"] and a["facts"] == river.get("facts", [])


def test_tellico_in_november_says_leave_the_dries_home():
    a = answer("south", "freestone", 11, river="tellico")
    assert a["dries"]["verdict"] == "no"
    assert [p["id"] for p in a["picks"]] == ["blood_dot_egg", "zebra_midge", "black_nosed_dace"]
    assert not any(p["family"] in SURFACE for p in a["picks"])


def test_a_chosen_fly_type_skips_the_plan():
    a = answer("south", "freestone", 11, fly_type="dry", river="tellico")
    assert a["kind"] == "model" and a["where"] == "Tellico River"
    assert all(p["family"] in SURFACE for p in a["picks"])


def test_a_water_with_no_plan_gets_up_to_three_flies_from_the_ranking():
    cat = catalog.load()
    for region, water in (("northeast", "freestone"), ("west", "tailwater"), ("south", "tailwater")):
        for month in range(1, 13):
            a = answer(region, water, month)
            assert a["kind"] == "model" and 1 <= len(a["picks"]) <= 3 and a["dries"], (region, water, month)
            assert len({p["id"] for p in a["picks"]}) == len(a["picks"])
            for fam in {p["family"] for p in a["picks"]}:
                assert sum(p["family"] == fam for p in a["picks"]) <= 2
            assert all(p["id"] in cat.flies and "items" in p["sources"] for p in a["picks"])


def test_no_dries_when_nothing_is_on_the_surface():
    a = answer("northeast", "freestone", 1)
    assert a["dries"]["verdict"] == "no" and not any(p["family"] in SURFACE for p in a["picks"])
    asked = answer("northeast", "freestone", 1, fly_type="dry")
    assert asked["dries"]["text"].endswith("You asked for dry flies, so these are the best of them, but expect little.")


def test_a_real_hatch_puts_a_dry_in_the_box():
    a = answer("northeast", "freestone", 6)
    assert a["dries"]["verdict"] == "yes" and any(p["family"] in SURFACE for p in a["picks"])


def test_dries_call_thresholds():
    cat = catalog.load()
    c = cond("northeast", "freestone", 6)
    call = lambda foods, c=c: advise.dries_call(cat, c, {k: (a, []) for k, a in foods.items()})
    assert call({"caddis": 0.95})["verdict"] == "yes"
    assert call({"caddis": 0.89})["verdict"] == "hatch-only"
    assert call({"caddis": 0.5})["verdict"] == "hatch-only"
    assert call({"caddis": 0.49})["verdict"] == "no"
    assert call({"bwo": 1.0})["verdict"] == "hatch-only"      # olives alone never earn a yes
    assert call({"trico": 1.0, "caddis": 0.3})["verdict"] == "hatch-only"
    assert call({"mouse": 1.0, "frog": 1.0})["verdict"] == "no"  # not dry-fly food
    assert call({"midge": 1.0})["verdict"] == "no"               # not on the surface
    assert call({"caddis": 0.95})["text"] == "Caddisflies are on the surface in June."
    assert advise.dries_call(cat, cond("south", "warm_river", 6), {}) is None  # dries are a trout question


def test_recommend_carries_the_same_answer():
    for req in ({"river": "tellico", "date": "2026-11-10"}, {"river": "androscoggin", "date": "2026-07-10"},
                {"region": "west", "water_type": "freestone", "date": "2026-06-20", "fly_type": "dry"}):
        out = recommend({**req, "use_live": False}, mode="rules")
        cat = catalog.load()
        river = req.get("river")
        spec = cat.rivers[river] if river else req
        c = cond(spec["region"], spec["water_type"], int(req["date"][5:7]), req.get("fly_type", "any"),
                 adjust=cat.rivers[river].get("adjust") if river else None)
        assert out["advice"] == advise.advise(cat, c, rules.score_flies(cat, c), river)
        assert out["advice"]["picks"]


def test_loader_rejects_a_bad_plan():
    cat = catalog.load()
    good = [{"months": list(range(1, 13)), "dries": "no", "dries_text": "Because.",
             "picks": [{"fly": "zebra_midge", "size": "#18", "why": "w"}, {"fly": "copper_john", "size": "#16", "why": "w"}],
             "src": [{"site": "A shop", "url": "https://example.com"}]}]
    catalog._check_plan("x", good, cat.flies)

    def bad(**change):
        entry = {**good[0], **change}
        with pytest.raises(ValueError):
            catalog._check_plan("x", [entry], cat.flies)

    bad(months=list(range(1, 12)))                                    # December has no plan
    bad(months=[0] + list(range(1, 12)))                              # not a month
    bad(dries="sometimes")
    bad(dries_text="")
    bad(picks=good[0]["picks"][:1])                                   # one fly
    bad(picks=good[0]["picks"] + good[0]["picks"])                    # four flies (and repeats)
    bad(picks=[good[0]["picks"][0], {"fly": "no_such_fly", "size": "#1", "why": "w"}])
    bad(picks=[good[0]["picks"][0], {"fly": "copper_john", "size": "", "why": "w"}])
    bad(src=[{"site": "A shop", "url": ""}])
    with pytest.raises(ValueError):                                   # the same month in two entries
        catalog._check_plan("x", [good[0], {**good[0], "months": [1]}], cat.flies)
    with pytest.raises(ValueError):
        catalog._check_facts("x", [{"text": "A rule.", "source": "A shop", "url": ""}])


NODE = """
const fs = require("fs");
global.DATA = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const FP = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(c => FP.advise(c))));
"""


def test_offline_page_gives_the_same_answer():
    """The demo page works the answer out in JS; scripts/check_parity.py compares every case, this samples a few."""
    if not shutil.which("node"):
        pytest.skip("needs node on PATH")
    cat = catalog.load()
    cases = [dict(river="tellico", region="south", water_type="freestone", date="2026-11-10", fly_type="any"),
             dict(river="south_holston", region="south", water_type="tailwater", date="2027-05-12", fly_type="any"),
             dict(river="tellico", region="south", water_type="freestone", date="2026-11-10", fly_type="dry"),
             dict(region="northeast", water_type="freestone", date="2026-06-10", fly_type="any"),
             dict(region="northeast", water_type="freestone", date="2026-01-10", fly_type="any")]
    data = ROOT / "dist" / "advise-test-data.json"
    data.parent.mkdir(exist_ok=True)
    data.write_text(json.dumps(page_data()))
    try:
        out = subprocess.run(["node", "-e", NODE, str(data), str(ROOT / "web" / "engine.js")],
                             input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    finally:
        data.unlink()
    for case, js in zip(cases, json.loads(out)):
        river = cat.rivers.get(case.get("river", ""))
        c = cond(case["region"], case["water_type"], int(case["date"][5:7]), case["fly_type"],
                 adjust=river.get("adjust") if river else None)
        assert json.loads(json.dumps(advise.advise(cat, c, rules.score_flies(cat, c), case.get("river")))) == js
