import math
import random
from pathlib import Path

from eval import backtest, train
from flypicker import catalog, rules

CSV = Path(__file__).resolve().parent.parent / "eval" / "reports_tn.csv"


def setup():
    cat, aliases = catalog.load(), backtest.load_aliases()
    return cat, aliases, backtest.scorable(backtest.load_rows(CSV), cat, aliases)


def test_every_report_phrase_is_mapped_or_a_known_gap():
    cat, aliases, pairs = setup()  # scorable() raises on a phrase aliases.json doesn't know
    assert len(pairs) == len(backtest.load_rows(CSV))


def test_alias_tokens_resolve():
    cat, aliases, _ = setup()
    for phrase, tokens in aliases["phrases"].items():
        for token in tokens:
            assert backtest.resolve(token, cat, aliases), (phrase, token)
    nymphs = backtest.resolve("nymphs", cat, aliases)
    assert {"pheasant_tail", "tan_scud"} <= nymphs
    assert not nymphs & {"zebra_midge", "san_juan_worm", "glo_bug", "woolly_bugger"}


def test_trainer_scores_like_the_rules():
    cat, _, pairs = setup()
    rnd = random.Random(0)
    beta = {k: rnd.uniform(-1, 1) for k in cat.foods}
    gamma = {k: rnd.uniform(-1, 1) for k in cat.flies}
    adj = {"name": "Test", "foods": {k: math.exp(v) for k, v in beta.items()},
           "flies": {k: math.exp(v) for k, v in gamma.items()}}
    for ex in train.examples(pairs[::5], cat):
        real = rules.score_flies(cat, backtest.conditions(ex.row, cat, adj))
        assert train.ranked(ex, beta, gamma) == [f["id"] for f in real]
        mine = {c.fly: train.score(c, beta, gamma)[0] for c in ex.cands}
        assert all(abs(mine[f["id"]] - f["score"]) < 1e-4 for f in real)


def test_training_learns_what_reports_favor():
    # A made-up river whose reports name a woolly bugger every month.
    cat = catalog.load()
    rows = [{"river": "x", "date": f"2020-{m:02d}-15", "region": "south", "water_type": "tailwater",
             "flies": "woolly bugger", "kind": "trip"} for m in range(1, 13)]
    exs = train.examples([(r, {"woolly_bugger"}) for r in rows], cat)
    beta, gamma = train.fit(exs, 0.1, 3.0)
    assert train.hit_count(exs, {}, {}) < 12 and train.hit_count(exs, beta, gamma) == 12


def test_time_split_keeps_same_day_reports_together():
    days = ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01", "2020-04-01", "2020-05-01"]
    older, newer = train.time_split(days, lambda d: d)
    assert older == days[:3] and newer == days[3:]
