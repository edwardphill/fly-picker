from flypicker import catalog, rules
from flypicker.rules import Conditions


def top(cond, n=5):
    cat = catalog.load()
    return [f["id"] for f in rules.score_flies(cat, cond)[:n]]


def test_catalog_loads_and_links():
    cat = catalog.load()
    assert len(cat.flies) >= 80 and len(cat.foods) >= 40
    for fly in cat.flies.values():
        assert fly["water"], fly["id"]


def test_hook_labels():
    assert catalog.size_range_label([16, 22]) == "#16–22"
    assert catalog.size_range_label([-2, 4]) == "3/0–#4"
    assert catalog.size_range_label([0, 0]) == "1/0"


def test_winter_tailwater_is_midges():
    assert "zebra_midge" in top(Conditions("west", "tailwater", 1))


def test_june_freestone_west_is_stoneflies():
    ids = top(Conditions("west", "freestone", 6))
    assert "pats_rubber_legs" in ids or "foam_salmonfly" in ids


def test_overcast_april_east_dries_are_bwo():
    assert top(Conditions("east", "freestone", 4, fly_type="dry", sky="overcast"), 1) == ["bwo_parachute"]


def test_windy_august_dries_are_hoppers():
    assert top(Conditions("west", "freestone", 8, fly_type="dry", sky="sunny", windy=True), 1)[0] in {"morrish_hopper", "parachute_hopper"}


def test_high_water_boosts_worms():
    cat = catalog.load()
    normal = rules.active_foods(cat, Conditions("east", "freestone", 4, flow="normal"))["worm"][0]
    high = rules.active_foods(cat, Conditions("east", "freestone", 4, flow="high"))["worm"][0]
    assert high > 2 * normal


def test_fly_type_filter():
    cat = catalog.load()
    res = rules.score_flies(cat, Conditions("west", "freestone", 9, fly_type="streamer"))
    assert res and all(f["family"] == "streamer" for f in res)


def test_saltwater_flats_and_surf():
    assert top(Conditions("south", "flats", 4), 2)[0] in {"gotcha", "merkin_crab"}
    assert top(Conditions("east", "surf", 10), 1)[0] in {"surf_candy", "clouser_minnow", "lefty_deceiver"}


def test_uncovered_water_returns_nothing():
    assert top(Conditions("west", "surf", 6)) == []


def test_cold_water_note():
    cat = catalog.load()
    res = rules.score_flies(cat, Conditions("west", "freestone", 6, fly_type="dry", water_temp_f=40))
    assert any("cold for them" in f["reason"] for f in res)


def test_south_borrows_east_months_one_earlier():
    cat = catalog.load()
    level, _ = rules.season_level(cat.foods["hendrickson"], "south", 3)
    assert level == rules.PEAK


def test_null_region_rules_a_food_out():
    # Smelt have an East chart, but none live in the South, so the South mustn't borrow it.
    cat = catalog.load()
    assert rules.season_level(cat.foods["smelt"], "south", 4) == (0.0, "not found in this region")
    assert not {"grey_ghost", "joes_smelt"} & set(top(Conditions("south", "tailwater", 4), 10))


def test_river_adjustments_change_the_ranking():
    cat = catalog.load()
    assert "woolly_bugger" not in top(Conditions("south", "tailwater", 9))
    tuned = Conditions("south", "tailwater", 9,
                       adjust={"name": "Elk River", "foods": {"leech": 3.0}, "flies": {"woolly_bugger": 2.0}})
    best = rules.score_flies(cat, tuned)[0]
    assert best["id"] == "woolly_bugger" and best["reason"].endswith("; favored in Elk River reports")


def test_home_river_presets():
    cat = catalog.load()
    assert {"caney_fork", "elk"} <= set(cat.rivers)
    for river in cat.rivers.values():
        assert river["region"] == "south" and river["water_type"] == "tailwater"
        # Learned adjustments are optional, and always come with a record of what they were fit on.
        assert ("adjust" in river) == ("trained_on" in river)


def test_mixed_list_spreads_foods_and_types():
    cat = catalog.load()
    cond = Conditions("south", "tailwater", 2)
    plain, mixed = rules.score_flies(cat, cond, mixed=False), rules.score_flies(cat, cond)
    assert [f["food"] for f in plain[:5]].count("midge") >= 3
    assert len({f["food"] for f in mixed[:5]}) >= 4 and len({f["family"] for f in mixed[:5]}) >= 3
    assert mixed[0] == plain[0]
    assert sorted(mixed, key=lambda f: f["id"]) == sorted(plain, key=lambda f: f["id"])  # same flies and scores
    assert rules.mix(plain, food_repeat=1.0, type_repeat=1.0) == plain
