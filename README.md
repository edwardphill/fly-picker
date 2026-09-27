# Fly Picker

Ranks flies for where and when you're fishing. You pick a region, a water type, a date and a fly type (dry, nymph, streamer and so on). It shows what the fish are probably eating and a top 10 of flies to tie on, each with a size and a reason.

This is step 1 of the plan: it works on day one with no training data.

## How it ranks

1. **Conditions.** Region, water type and month, plus water temp, sky, wind and flow. If you give coordinates for today's date, it reads the nearest USGS stream gauge (water temp and flow compared with normal for the day) and Open-Meteo weather. Without them it uses typical water temps for the month.
2. **Hatch chart** (`flypicker/data/foods.json`). 43 food items (mayflies including Isonychia, caddis, stoneflies, midges, smelt, terrestrials, sculpins, crayfish, shrimp, crabs, sand eels and more), each with its season by region (West, Northeast, East and South), preferred water temp, and how sky and flow change it.
3. **Catalog** (`flypicker/data/flies.json`). 149 patterns, including Tennessee tailwater staples (Kenny, Trout Candy, sowbugs, midges) and Maine smelt streamers (Grey Ghost, Joe's Smelt, Nine-Three), each tagged with the foods it imitates, its hook sizes and the waters it's fished in.
4. **Scoring.**
   - **Jev** (when `TYPESAFE_API_KEY` is set): the best 40 candidates from the rules go to Jev in one parallel call. A `Choice` asks what the fish are eating, and a `Noul` per fly asks whether that fly would catch fish today. Rank = 60% the fly's Noul probability plus 40% how likely its food is.
   - **Hatch-chart rules** (no key, or if Jev fails): how active each food is × how well the fly imitates it × a small "proven pattern" prior.
5. **List order.** The top 10 is spread across foods and fly types, so one hatch can't fill it. Each place goes to the best remaining fly after a cut for the flies already listed: 30% of its score for each one with the same food, 80% for each one of the same type. The scores shown don't change. Fishing reports mostly name fly types ("midges", "streamers", "nymphs"), and a mixed list covers far more of them.
6. **Home rivers** (`flypicker/data/rivers.json`). Picking the Caney Fork or the Elk River (Tennessee tailwaters), or the Magalloway (below Aziscohos Dam) or the Androscoggin (Gilead to Bethel) in Maine, sets the region, water type and gauge location. A river can also carry multipliers learned from its fishing reports, for foods and flies its reports favor more or less than the hatch chart does. See "Test on real fishing reports" below. The Maine rivers use the Northeast hatch chart (see "Maine and North Country reports" below) and have no adjustments of their own.
7. **Catch log.** Every search and every "Caught fish" / "No luck" tap goes into SQLite (`flypicker.db`). That becomes the training data for a later ranker, including the misses that reports never record.

## Add your own flies

Add a line to `flypicker/data/my_flies.csv` (it opens in Excel, Numbers, Google Sheets, or GitHub's web editor). Only `name`, `type` and `imitates` are required:

```csv
name,type,imitates,sizes,water,proven,notes
Olive Kenny,wet,caddis:0.6; sowbug:0.5,12-16,tailwater,0.8,Tim's Flies and Lies
Green Eyed Demon,nymph,caddis,,,,
```

- `type`: dry, emerger, nymph, wet, streamer, topwater or flats.
- `imitates`: foods separated by `;`, each with an optional 0-1 match after `:` (0.8 if left off). Use a food id or name from `flypicker/data/foods.json`, such as midge, bwo, sulfur, caddis, isonychia, scud, sowbug, worm, egg, leech, sculpin, smelt or baitfish_fw.
- `sizes`: like `12-16`, `14` or `2/0-4`. Blank uses the first food's sizes.
- `water`: water types or groups separated by `;` (tailwater, freestone, RIVER, LAKE, WARM, SALT and so on). Blank means wherever its foods live.
- `proven`: 0-1, how much you trust it. Blank is 0.7.

Rows starting with `#` are skipped. A bad row stops the app with a message naming the row and what's wrong, and `python -m pytest` catches it too.

## Run it

```bash
pip install -r requirements.txt
export TYPESAFE_API_KEY=...        # optional; without it the app uses the rules
uvicorn app:app --reload           # open http://localhost:8000
```

API: `POST /api/recommend` with `{"region": "west", "water_type": "freestone", "date": "2026-06-24", "fly_type": "dry", "lat": 45.35, "lon": -111.73}` (or `{"river": "caney_fork", "date": "2026-06-24"}` for a home river), then `POST /api/catch` with `{"search_id": 1, "fly_id": "stimulator", "outcome": "caught"}`.

## Test on real fishing reports

`eval/reports_tn.csv` holds 93 dated reports from the Caney Fork and the Elk River: shop and guide reports and trip write-ups from 2007 to 2026, each with the flies it says worked, the conditions it gives and a link to the source. `eval/aliases.json` maps report phrases ("chartreuse woolly", "nymphs", "shad pattern") to catalog flies, foods or fly types, and lists local patterns the catalog doesn't have.

```bash
python -m eval.backtest eval/reports_tn.csv         # hit rate by river and report kind
python -m eval.train eval/reports_tn.csv            # learn river adjustments on older reports, test on the newest
python -m eval.train eval/reports_tn.csv --write    # then refit on all reports and update rivers.json
python -m eval.train eval/reports_tn.csv --mixing   # how the list-order cuts in rules.py were picked
TYPESAFE_API_KEY=... python -m eval.backtest eval/reports_tn.csv --jev   # compare Jev once there's a key
```

A hit means at least one fly the report says worked is in the top 5 (or top 3). The list-order cuts and the river adjustments were picked on the older two thirds of each river's reports. On the newest third, which none of that saw:

| List | Caney Fork, top 5 | Caney Fork, top 3 | Elk River, top 5 | Elk River, top 3 |
|---|---|---|---|---|
| Hatch-chart rules in score order | 72% | 61% | 64% | 57% |
| Hatch-chart rules, mixed list (the app) | 100% | 89% | 100% | 86% |
| Mixed list + that river's adjustments | 100% | 83% | 100% | 64% |
| The same 5 flies every time, the ones older reports name most | 100% | 100% | 100% | 36% |

That's 18 Caney Fork reports and 14 Elk River reports. Read these with care. The samples are small, and dates are often post dates. Most rows are weekly shop or guide reports that name fly types ("midges", "streamers on high water", "nymphs") rather than patterns, which is why the mixed list catches them. It also means these reports can no longer tell a good list from a better one; the catch log, which records specific flies, is the test from here.

`--write` keeps a river's adjustments only when they beat the mixed list on that river's newest reports: more top-5 hits, or as many with the flies that worked placed higher on average. The Elk River's didn't. They put woolly buggers first every month, as the 2009 trip reports do, while newer reports mostly name nymphs and midges. So the Elk has none. The Caney Fork's passed narrowly and are mild (sculpins and minnows up about 14%). The Elk's staple flies, the Kenny and Trout Candy from the Lynchburg fly shop, aren't in the catalog. Other reports can go in a CSV shaped like `eval/reports_template.csv`.

### Maine and North Country reports

`eval/reports_me.csv` holds 59 reports from 2006 to 2026, from within about 100 miles of the Magalloway and the Androscoggin: the Rangeley Region Sports Shop's weekly reports, Orvis reports from New Hampshire shops (Androscoggin at Errol, Saco, Upper Connecticut), North Country Angler, New Hampshire's weekly fishing reports, the Sun Journal, a Rapid River trip and a fly shop's word that September 2026 is streamer season on the Androscoggin, plus All Points Fly Shop's Maine reports, which before 2026 cover the whole state. 34 name flies; the rest are kept for their dates and water temps.

What they show, and what the Northeast region's chart now follows:

- Water is near 40°F at ice-out in late April and in the mid 40s through mid May. Smelt runs (April to mid May) make smelt streamers the main spring fly, with worms, pheasant tails and zebra midges fished deep.
- Suckers spawn in mid to late May. The first mayflies show around May 20; Hendricksons and March browns last into mid June.
- Caddis start when the water nears 60°F in mid June and carry the summer, with stoneflies, yellow sallies and drakes in late June and July.
- Late summer water runs in the 60s and is often low. September brings the fall spawning runs, streamers and small BWOs.

The Northeast chart follows that timing instead of the East's, with minnow streamers peaking in spring and fall. It adds northern water temps and drops scuds and sowbugs, which none of these reports name. Foods it doesn't list keep the East's months.

```bash
python -m eval.backtest eval/reports_me.csv                # the Northeast chart
python -m eval.backtest eval/reports_me.csv --region east  # the same reports on the East's chart
```

| Chart, mixed list | Top 5 | Top 3 | A named fly first |
|---|---|---|---|
| East (what the Maine rivers used before) | 88% | 82% | 32% |
| Northeast | 91% | 88% | 65% |

The Northeast months were set while reading these same reports, so this shows the chart matches them; it isn't a test on reports the chart never saw. Two big northern hatches aren't in the catalog yet: alder flies (early July, the Rapid River's biggest hatch) and Hex (late June and July). Maine smelt streamers such as the Gray Ghost and Black Ghost count as minnow imitations here.

## Other scripts

- `python -m pytest`: tests. Jev and the USGS and weather services are faked, so no key or network is needed.
- `python -m scripts.build_page`: writes `dist/fly-picker-demo.html`, a standalone demo that runs the rules in the browser.
- `python -m scripts.check_parity`: checks that the browser engine (`web/engine.js`) ranks exactly like `flypicker/rules.py`. It needs node.

## Known gaps

- The catalog is hand-tagged from general knowledge. Kenny and Trout Candy are tagged as soft-hackle wets from how Elk River reports describe them, not from a recipe. It still needs matching to the ~2,087 patterns on flysandguides.com, whose site couldn't be reached from the build environment.
- Hatch timing is broad-brush for four US regions. Per-river charts, the Pacific coast in saltwater, and time of day aren't covered yet.
- The live USGS and weather lookups were tested against canned responses only, because the build environment couldn't reach those services. USGS is moving to a new Water Data API, and `flypicker/conditions.py` notes where to switch.
- The Jev integration was tested against a fake API, not the real service, because no key was available. The SDK doesn't document a limit on questions per call, so candidates go out in chunks of 24 (`FLYPICKER_JEV_CHUNK`).
