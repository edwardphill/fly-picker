from eval import sources as build_sources
from flypicker import catalog, sources
from flypicker.recommend import recommend


def test_sources_json_is_up_to_date():
    # Rebuild with `python -m eval.sources` after editing eval/reports_*.csv or eval/aliases.json.
    assert sources.PATH.read_text() == build_sources.render(build_sources.build())


def test_every_source_links_somewhere():
    for s in sources.load()["sources"]:
        assert s["url"].startswith("http") and s["picks"], s


def test_named_reports_come_first():
    cat = catalog.load()
    cites = sources.cite(cat.flies["zonker"], "south", 2, "caney_fork")
    top = cites["items"][0]
    assert top["named"] and top["place"] == "Caney Fork" and "zonker" in top["said"]
    assert cites["total"] >= len(cites["items"])


def test_kind_of_fly_matches_respect_exclusions():
    cat = catalog.load()
    # "nymphs" in the reports excludes midges, so a zebra midge isn't credited to them.
    said = {c["said"] for c in sources.cite(cat.flies["zebra_midge"], "south", 1)["items"]}
    assert "nymphs" not in said


def test_no_sources_outside_covered_regions():
    cat = catalog.load()
    assert sources.cite(cat.flies["parachute_adams"], "west", 6)["total"] == 0


def test_recommend_attaches_sources():
    res = recommend({"river": "elk", "date": "2026-04-10"}, mode="rules")
    assert res["cited_region"]
    assert all("sources" in f for f in res["flies"])
    assert any(f["sources"]["total"] for f in res["flies"])
