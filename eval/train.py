"""Learns per-river adjustments to the hatch-chart rules from fishing reports.

    python -m eval.train eval/reports_tn.csv            # fit on older reports, test on the newest
    python -m eval.train eval/reports_tn.csv --write    # then refit on all reports, same settings, and save flypicker/data/rivers.json
    python -m eval.train eval/reports_tn.csv --mixing   # how the list-mixing strength in rules.py was picked

The rules themselves don't change. Training learns two kinds of multipliers per river: how much
more or less each food matters there than the hatch chart says, and a nudge for individual flies
the reports name. For each river it holds out the newest third of the reports, fits on the older
ones, and scores the held-out reports with the real scorer, so the "after" numbers are on reports
the fit never saw. Settings (regularization and softmax temperature) are picked the same way on
the training reports alone, and --write refits on every report with those same settings. A river
only gets its adjustments written when they beat the plain mixed list on its newest reports.

The loss is listwise: a softmax over each report's candidate flies, pushing up the share that goes
to flies the report says worked. Hit counts use the app's mixed list order (rules.mix), since that
is what an angler sees. Pure Python, no numpy; under a minute for both rivers.
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.backtest import K, conditions, load_aliases, load_rows, places, rate, scorable  # noqa: E402
from flypicker import catalog, rules  # noqa: E402

RIVERS_PATH = ROOT / "flypicker" / "data" / "rivers.json"
GRID = [(lam, tau) for lam in (0.01, 0.03, 0.1, 0.3, 1.0) for tau in (1.0, 3.0)]
MIX_GRID = [(food, kind) for food in (1.0, 0.7, 0.5, 0.3, 0.0) for kind in (1.0, 0.8, 0.6, 0.4)]
MIXED = (rules.FOOD_REPEAT, rules.TYPE_REPEAT)
STEPS, LR, LIMIT = 250, 0.05, 3.0  # Adam steps, step size, and a cap on |log multiplier|


@dataclass
class Cand:
    fly: str
    name: str
    family: str
    parts: list  # (fly weight x food activity, food id) for the foods active in this report
    overlap: dict  # food id -> whether the fly comes in that food's sizes
    static: float  # proven-pattern factor


@dataclass
class Example:
    row: dict
    cands: list
    wanted: set  # indexes into cands


def examples(pairs, cat) -> list[Example]:
    out = []
    for row, ids in pairs:
        cond = conditions(row, cat)
        foods = rules.active_foods(cat, cond)
        cands = []
        for fly in cat.flies.values():
            if not rules.fly_matches(fly, cond):
                continue
            parts = [(w * foods[fid][0], fid) for fid, w in fly["imitates"] if fid in foods]
            if parts:
                cands.append(Cand(fly["id"], fly["name"], fly["family"], parts,
                                  {fid: rules.recommended_sizes(fly, cat.foods[fid])[1] for _, fid in parts},
                                  0.75 + 0.25 * fly["proven"]))
        out.append(Example(row, cands, {i for i, c in enumerate(cands) if c.fly in ids}))
    return out


def score(c: Cand, beta: dict, gamma: dict) -> tuple[float, list]:
    """Same arithmetic as rules.score_flies with adjust = exp(beta), exp(gamma)."""
    top = sorted(((v * math.exp(beta.get(fid, 0.0)), fid) for v, fid in c.parts), reverse=True)[:3]
    s = top[0][0] + 0.25 * sum(p for p, _ in top[1:])
    if not c.overlap[top[0][1]]:
        s *= 0.8
    return s * c.static * math.exp(gamma.get(c.fly, 0.0)), top


def ranked(ex: Example, beta: dict, gamma: dict, steps: tuple | None = MIXED) -> list[str]:
    """Fly ids in the app's list order: mixed with steps = (food repeat, type repeat), or score order with None."""
    scored = []
    for c in ex.cands:
        s, top = score(c, beta, gamma)
        scored.append({"raw": s, "name": c.name, "id": c.fly, "food": top[0][1], "family": c.family})
    scored.sort(key=lambda r: (-r["raw"], r["name"]))
    if steps:
        scored = rules.mix(scored, score=lambda r: r["raw"], food_repeat=steps[0], type_repeat=steps[1])
    return [r["id"] for r in scored]


def loss_and_grad(exs, beta, gamma, lam, tau):
    total, gb, gg = 0.0, defaultdict(float), defaultdict(float)
    for ex in exs:
        scored = [score(c, beta, gamma) for c in ex.cands]
        z = [tau * math.log(s) for s, _ in scored]
        m = max(z)
        e = [math.exp(v - m) for v in z]
        zall, zwant = sum(e), sum(e[i] for i in ex.wanted)
        total -= math.log(zwant / zall)
        for i, (c, (_, top)) in enumerate(zip(ex.cands, scored)):
            d = tau * (e[i] / zall - (e[i] / zwant if i in ex.wanted else 0.0)) / len(exs)
            gg[c.fly] += d
            s = top[0][0] + 0.25 * sum(p for p, _ in top[1:])
            for j, (p, fid) in enumerate(top):
                gb[fid] += d * (1.0 if j == 0 else 0.25) * p / s
    total /= len(exs)
    for params, grad in ((beta, gb), (gamma, gg)):
        for key in set(params) | set(grad):
            total += lam * params.get(key, 0.0) ** 2
            grad[key] += 2 * lam * params.get(key, 0.0)
    return total, gb, gg


def fit(exs, lam, tau) -> tuple[dict, dict]:
    exs = [ex for ex in exs if ex.wanted]  # reports whose flies can't be candidates teach nothing
    beta, gamma, m, v = {}, {}, defaultdict(float), defaultdict(float)
    if not exs:
        return beta, gamma
    for t in range(1, STEPS + 1):
        _, gb, gg = loss_and_grad(exs, beta, gamma, lam, tau)
        for tag, params, grad in (("b", beta, gb), ("g", gamma, gg)):
            for key, g in grad.items():
                k = (tag, key)
                m[k] = 0.9 * m[k] + 0.1 * g
                v[k] = 0.999 * v[k] + 0.001 * g * g
                step = LR * (m[k] / (1 - 0.9 ** t)) / (math.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
                params[key] = max(-LIMIT, min(LIMIT, params.get(key, 0.0) - step))
    return beta, gamma


def hit_count(exs, beta, gamma, steps: tuple | None = MIXED) -> int:
    return sum(bool({ex.cands[i].fly for i in ex.wanted} & set(ranked(ex, beta, gamma, steps)[:K])) for ex in exs)


def quality(exs, beta, gamma) -> tuple[int, float]:
    """Hits in the top K, then the mean of 1/place of the first fly that worked, which still tells
    settings apart when the mixed top K catches nearly every report."""
    inv = 0.0
    for ex in exs:
        want = {ex.cands[i].fly for i in ex.wanted}
        inv += next((1 / (i + 1) for i, fly in enumerate(ranked(ex, beta, gamma)) if fly in want), 0.0)
    return hit_count(exs, beta, gamma), inv / max(len(exs), 1)


def time_split(items, date_of, frac=1 / 3):
    """Oldest part and newest part; reports from the same day stay together."""
    items = sorted(items, key=date_of)
    cut = date_of(items[int(len(items) * (1 - frac))])
    return [x for x in items if date_of(x) < cut], [x for x in items if date_of(x) >= cut]


def choose_and_fit(exs) -> tuple[dict, dict, tuple]:
    """Pick (lambda, tau) on a time split of these reports, then refit on all of them.
    Ties go to the stronger regularization."""
    older, newer = time_split(exs, lambda ex: ex.row["date"])
    best = max(GRID, key=lambda cfg: (*quality(newer, *fit(older, *cfg)), cfg[0]))
    return (*fit(exs, *best), best)


def choose_mixing(exs) -> tuple[tuple, dict]:
    """List-mixing strength for rules.py, picked on these reports with the plain rules: the gentlest
    setting (largest repeat shares, so closest to score order) within one standard error of the best."""
    counts = {cfg: hit_count(exs, {}, {}, cfg) for cfg in MIX_GRID}
    best = max(counts.values())
    p = best / len(exs)
    floor = best - math.sqrt(p * (1 - p) * len(exs))
    return max((cfg for cfg, n in counts.items() if n >= floor), key=lambda cfg: (sum(cfg), cfg)), counts


def merit(found: list) -> tuple[int, float]:
    """Held-out comparison: hits in the top K, then the summed 1/place of the first fly that worked."""
    return sum(p is not None and p <= K for p in found), sum(1 / p for p in found if p)


def adjust(name: str, beta: dict, gamma: dict) -> dict:
    keep = lambda d: {k: round(math.exp(x), 3) for k, x in sorted(d.items()) if abs(x) >= 0.01}
    return {"name": name, "foods": keep(beta), "flies": keep(gamma)}


def popularity(train_pairs, cat) -> list[str]:
    """The flies the training reports name most, ignoring conditions: the no-model baseline."""
    credit = Counter()
    for row, ids in train_pairs:
        ids = [fid for fid in ids if row["water_type"] in cat.flies[fid]["water"]]
        for fid in ids:
            credit[fid] += 1 / len(ids)
    return [fid for fid, _ in sorted(credit.items(), key=lambda kv: (-kv[1], cat.flies[kv[0]]["name"]))[:K]]


def changes(adj: dict, cat, n: int = 4) -> str:
    items = [(x, cat.foods[k]["name"].lower()) for k, x in adj["foods"].items()]
    items += [(x, cat.flies[k]["name"]) for k, x in adj["flies"].items()]
    items.sort(key=lambda t: -abs(math.log(t[0])))
    return ", ".join(f"{name} x{x:.2f}" for x, name in items[:n])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--write", action="store_true", help=f"refit on all reports and write {RIVERS_PATH.relative_to(ROOT)}")
    ap.add_argument("--mixing", action="store_true", help="show how the list-mixing strength in rules.py was picked")
    args = ap.parse_args()
    cat, aliases = catalog.load(), load_aliases()
    pairs = scorable(load_rows(args.csv), cat, aliases)
    by_river = defaultdict(list)
    for pair in pairs:
        by_river[pair[0]["river"]].append(pair)

    splits = {r: time_split(ps, lambda p: p[0]["date"]) for r, ps in by_river.items()}
    if args.mixing:
        older = examples([p for tr, _ in splits.values() for p in tr], cat)
        pick, counts = choose_mixing(older)
        print(f"List mixing on the {len(older)} older reports (plain rules), hits in the top {K}:")
        for (food, kind), n in sorted(counts.items(), key=lambda kv: (-kv[1], -sum(kv[0]))):
            print(f"  same food x{food:.1f}, same type x{kind:.1f}: {n}/{len(older)}{'  <- picked' if (food, kind) == pick else ''}")
        print(f"rules.py uses x{rules.FOOD_REPEAT} and x{rules.TYPE_REPEAT}" + ("." if pick == MIXED else ", which differs from the pick."))
        return
    pooled_beta, pooled_gamma, pooled_cfg = choose_and_fit(examples([p for tr, _ in splits.values() for p in tr], cat))
    settings, keep = {}, {}
    for river, (train, test) in splits.items():
        name = cat.rivers.get(river, {}).get("name", river)
        beta, gamma, cfg = choose_and_fit(examples(train, cat))
        settings[river] = cfg
        own = adjust(name, beta, gamma)
        pooled = adjust("Middle Tennessee", pooled_beta, pooled_gamma)
        pop = popularity(train, cat)
        print(f"\n{name}: fit on {len(train)} reports ({train[0][0]['date']} to {train[-1][0]['date']}), "
              f"tested on the newest {len(test)} ({test[0][0]['date']} to {test[-1][0]['date']})")
        print(f"  {'':32} {'top ' + str(K):14} top 3")
        found = {}
        for key, label, pl in (
            ("score", "rules in score order", places(test, cat, mixed=False)),
            ("mixed", "rules, mixed list", places(test, cat)),
            ("own", f"mixed + {name} adjustments", places(test, cat, lambda row: own)),
            ("pooled", "mixed + both rivers pooled", places(test, cat, lambda row: pooled)),
            ("pop", "most-named flies in training", [next((i + 1 for i, f in enumerate(pop) if f in ids), None) for _, ids in test]),
        ):
            found[key] = pl
            print(f"  {label:32} {rate([p is not None and p <= K for p in pl]):14} {rate([p is not None and p <= 3 for p in pl])}")
        keep[river] = merit(found["own"]) > merit(found["mixed"])
        print(f"  learned (lambda={cfg[0]}, tau={cfg[1]}): {changes(own, cat)}")
        if not keep[river]:
            print("  --write leaves these off: they don't beat the mixed list alone on the newest reports.")
    print(f"\nPooled (lambda={pooled_cfg[0]}, tau={pooled_cfg[1]}): {changes(adjust('', pooled_beta, pooled_gamma), cat)}")

    if args.write:
        # Same settings as the tested fit, refit on every report: the shipped version is the tested recipe.
        presets = json.loads(RIVERS_PATH.read_text())
        source = Path(args.csv).resolve()
        source = str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source)
        for river, ps in by_river.items():
            preset = presets["rivers"].get(river)
            if preset is None:
                print(f"\nSkipped {river}: add its region, water type and location to rivers.json first.")
                continue
            if not keep[river]:
                preset.pop("adjust", None)
                preset.pop("trained_on", None)
                print(f"\n{preset['name']}: no adjustments, since they didn't beat the mixed list on its newest reports.")
                continue
            ps, cfg = sorted(ps, key=lambda p: p[0]["date"]), settings[river]
            beta, gamma = fit(examples(ps, cat), *cfg)
            preset["adjust"] = adjust(preset["name"], beta, gamma)
            preset["trained_on"] = {"reports": len(ps), "from": ps[0][0]["date"], "to": ps[-1][0]["date"],
                                    "lambda": cfg[0], "tau": cfg[1], "source": source}
        RIVERS_PATH.write_text(json.dumps(presets, indent=2) + "\n")
        print(f"\nWrote {RIVERS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
