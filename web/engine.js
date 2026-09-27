// Port of flypicker/rules.py for the offline demo page. Keep in sync with rules.py;
// scripts/check_parity.py compares the two. DATA is injected by scripts/build_page.py
// with water groups already expanded.
const FP = (() => {
  const PEAK = 1.0, ON = 0.55, OFF = 0.04, TEMP_FALLOFF_F = 12.0, TEMP_FLOOR = 0.08;
  const FOOD_REPEAT = 0.3, TYPE_REPEAT = 0.8, MIXED_PLACES = 10;
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];

  function resolvedTemp(cond) {
    if (cond.water_temp_f !== null && cond.water_temp_f !== undefined) return Number(cond.water_temp_f);
    const profile = DATA.water_types[cond.water_type].temp_profile;
    return DATA.typical_temp[cond.region][profile][cond.month - 1];
  }

  function seasonSpec(food, region) {
    const s = food.season;
    if (region in s) return s[region];
    if (region === "south" && s.east && !s.all) {
      const shift = ms => (ms || []).map(m => ((m - 2 + 12) % 12) + 1);
      return { peak: shift(s.east.peak), on: shift(s.east.on) };
    }
    return s.all || null;
  }

  function seasonLevel(food, region, month) {
    const spec = seasonSpec(food, region);
    if (!spec) return [0, "not found in this region"];
    if ((spec.peak || []).includes(month)) return [PEAK, "peak season"];
    if ((spec.on || []).includes(month)) return [ON, "in season"];
    return [food.base !== undefined ? food.base : OFF, "out of season"];
  }

  function tempFit(food, temp) {
    const [lo, hi] = food.temp;
    if (temp >= lo && temp <= hi) return 1.0;
    const gap = temp < lo ? lo - temp : temp - hi;
    return Math.max(TEMP_FLOOR, 1.0 - gap / TEMP_FALLOFF_F);
  }

  function foodActivity(food, cond, temp) {
    const water = food.water[cond.water_type] || 0;
    const [level, seasonNote] = seasonLevel(food, cond.region, cond.month);
    if (water === 0 || level === 0) return [0, []];
    const notes = [`${seasonNote} in ${MONTHS[cond.month - 1]}`];

    const tf = tempFit(food, temp);
    const [lo, hi] = food.temp;
    if (tf < 1) notes.push(`${temp.toFixed(0)}°F water is ${temp < lo ? "cold" : "warm"} for them (${lo}–${hi}°F)`);

    const skyMods = food.sky || {};
    let sky = skyMods[cond.sky] !== undefined ? skyMods[cond.sky] : 1.0;
    if (sky > 1) notes.push(cond.sky === "rain" ? "rain helps" : `${cond.sky} skies help`);
    if (cond.windy) {
      const w = skyMods.windy !== undefined ? skyMods.windy : 1.0;
      sky *= w;
      if (w > 1) notes.push("wind helps");
    }

    const flowMods = food.flow || {};
    let flow = flowMods[cond.flow] !== undefined ? flowMods[cond.flow] : 1.0;
    if (food.stage === "surface") flow *= ({ high: 0.6, low: 1.1 })[cond.flow] || 1.0;
    if (flow > 1 && cond.flow === "high") notes.push("high water helps");

    const boosts = (cond.adjust && cond.adjust.foods) || {};
    const boost = boosts[food.id] !== undefined ? boosts[food.id] : 1.0;
    return [level * water * tf * sky * flow * boost, notes];
  }

  function activeFoods(cond) {
    const temp = resolvedTemp(cond);
    const out = {};
    for (const [fid, food] of Object.entries(DATA.foods)) {
      const [act, notes] = foodActivity(food, cond, temp);
      if (act > 0) out[fid] = [act, notes];
    }
    return out;
  }

  function hookLabel(n) { return n <= 0 ? `${1 - n}/0` : `#${n}`; }
  function sizeRangeLabel([big, small]) {
    if (big === small) return hookLabel(big);
    if (big > 0) return `#${big}–${small}`;
    return `${hookLabel(big)}–${hookLabel(small)}`;
  }

  function recommendedSizes(fly, food) {
    const big = Math.max(fly.sizes[0], food.sizes[0]);
    const small = Math.min(fly.sizes[1], food.sizes[1]);
    return big <= small ? [[big, small], true] : [fly.sizes.slice(), false];
  }

  function strengthLabel(score) {
    if (score >= 0.8) return "strong";
    if (score >= 0.35) return "fair";
    return "long shot";
  }

  function scoreFlies(cond, foods) {
    const results = [];
    for (const fly of Object.values(DATA.flies)) {
      if (!fly.water.includes(cond.water_type)) continue;
      if (cond.fly_type !== "any" && cond.fly_type !== fly.family) continue;
      const parts = fly.imitates
        .filter(([fid]) => foods[fid])
        .map(([fid, w]) => [w * foods[fid][0], fid])
        .sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? 1 : a[1] > b[1] ? -1 : 0));
      if (!parts.length) continue;
      const [best, bestFood] = parts[0];
      let score = best + 0.25 * parts.slice(1, 3).reduce((s, p) => s + p[0], 0);
      const food = DATA.foods[bestFood];
      const [sizes, overlap] = recommendedSizes(fly, food);
      if (!overlap) score *= 0.8;
      score *= 0.75 + 0.25 * fly.proven;
      let reason = `Imitates ${food.name.toLowerCase()}: ` + foods[bestFood][1].join("; ");
      const adjust = cond.adjust || {};
      const flyBoosts = adjust.flies || {}, foodBoosts = adjust.foods || {};
      const boost = flyBoosts[fly.id] !== undefined ? flyBoosts[fly.id] : 1.0;
      score *= boost;
      if (boost * (foodBoosts[bestFood] !== undefined ? foodBoosts[bestFood] : 1.0) >= 1.25) reason += `; favored in ${adjust.name || "local"} reports`;
      results.push({
        _raw: score,
        id: fly.id, name: fly.name, family: fly.family,
        score: Math.round(score * 1e4) / 1e4,
        strength: strengthLabel(score),
        sizes: sizeRangeLabel(sizes),
        food: bestFood, food_name: food.name,
        reason,
      });
    }
    results.sort((a, b) => b._raw - a._raw || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    const mixed = mix(results, MIXED_PLACES, r => r._raw);
    for (const r of mixed) delete r._raw;
    return mixed;
  }

  // Spreads the top places across foods and fly types, as rules.mix does.
  function mix(ranked, places, score) {
    const left = ranked.slice(), out = [], foodCut = {}, typeCut = {};
    while (left.length && out.length < places) {
      let bestI = 0, bestV = -1.0;
      left.forEach((r, i) => {
        const v = score(r) * (foodCut[r.food] !== undefined ? foodCut[r.food] : 1.0) * (typeCut[r.family] !== undefined ? typeCut[r.family] : 1.0);
        if (v > bestV) { bestI = i; bestV = v; }
      });
      const [r] = left.splice(bestI, 1);
      out.push(r);
      foodCut[r.food] = (foodCut[r.food] !== undefined ? foodCut[r.food] : 1.0) * FOOD_REPEAT;
      typeCut[r.family] = (typeCut[r.family] !== undefined ? typeCut[r.family] : 1.0) * TYPE_REPEAT;
    }
    return out.concat(left);
  }

  function foodShares(foods, top = 5) {
    const entries = Object.entries(foods);
    const total = entries.reduce((s, [, [a]]) => s + a, 0) || 1;
    return entries.sort((a, b) => b[1][0] - a[1][0]).slice(0, top)
      .map(([fid, [a]]) => ({ id: fid, name: DATA.foods[fid].name, share: Math.round(a / total * 1000) / 1000 }));
  }

  function recommend(req) {
    const d = req.date ? new Date(req.date + "T12:00:00") : new Date();
    const temp = req.water_temp_f === "" || req.water_temp_f === null || req.water_temp_f === undefined ? null : Number(req.water_temp_f);
    const river = req.river ? DATA.rivers[req.river] : null;  // a home-river preset fixes region and water
    const cond = {
      region: river ? river.region : req.region, water_type: river ? river.water_type : req.water_type,
      month: d.getMonth() + 1,
      fly_type: req.fly_type || "any", water_temp_f: temp,
      temp_source: temp === null ? "typical" : "angler",
      sky: req.sky || "partly", windy: !!req.windy, flow: req.flow || "normal",
      adjust: river && river.adjust ? river.adjust : null,
    };
    const foods = activeFoods(cond);
    const wt = DATA.water_types[cond.water_type];
    return {
      engine: "rules",
      conditions: {
        region: DATA.regions[cond.region], water_type: wt.name, fish: wt.fish,
        date: req.date, fly_type: DATA.fly_types[cond.fly_type],
        water_temp_f: Math.round(resolvedTemp(cond)), temp_source: cond.temp_source,
        sky: cond.sky, windy: cond.windy, flow: cond.flow, gauge: null,
        river: river ? { name: river.name, reports: river.trained_on ? river.trained_on.reports : 0 } : null,
      },
      eating: foodShares(foods),
      flies: scoreFlies(cond, foods).slice(0, 10),
      notes: Object.keys(foods).length ? [] : ["The starter hatch chart doesn't cover this water in this region yet."],
    };
  }

  return { recommend, scoreFlies, activeFoods, foodShares, resolvedTemp };
})();
if (typeof module !== "undefined") module.exports = FP;
