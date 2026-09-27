# Fly Picker

Ranks flies for where and when you're fishing. You pick a region, a water type, a date and a fly type (dry, nymph, streamer and so on). It shows what the fish are probably eating and a top 10 of flies to tie on, each with a size and a reason.

This is step 1 of the plan: it works on day one with no training data.

## How it ranks

1. **Conditions.** Region, water type and month, plus water temp, sky, wind and flow. If you give coordinates for today's date, it reads the nearest USGS stream gauge (water temp and flow compared with normal for the day) and Open-Meteo weather. Without them it uses typical water temps for the month.
2. **Hatch chart** (`flypicker/data/foods.json`). 43 food items (mayflies including Isonychia, caddis, stoneflies, midges, smelt, terrestrials, sculpins, crayfish, shrimp, crabs, sand eels and more), each with its season by region, preferred water temp, and how sky and flow change it.
3. **Catalog** (`flypicker/data/flies.json`). 149 patterns, including Tennessee tailwater staples (Kenny, Trout Candy, sowbugs, midges) and Maine smelt streamers (Grey Ghost, Joe's Smelt, Nine-Three), each tagged with the foods it imitates, its hook sizes and the waters it's fished in.
4. **Scoring.**
   - **Jev** (when `TYPESAFE_API_KEY` is set): the best 40 candidates from the rules go to Jev in one parallel call. A `Choice` asks what the fish are eating, and a `Noul` per fly asks whether that fly would catch fish today. Rank = 60% the fly's Noul probability plus 40% how likely its food is.
   - **Hatch-chart rules** (no key, or if Jev fails): how active each food is × how well the fly imitates it × a small "proven pattern" prior.
5. **Catch log.** Every search and every "Caught fish" / "No luck" tap goes into SQLite (`flypicker.db`). That becomes the training data for a later ranker, including the misses that reports never record.

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

API: `POST /api/recommend` with `{"region": "west", "water_type": "freestone", "date": "2026-06-24", "fly_type": "dry", "lat": 45.35, "lon": -111.73}`, then `POST /api/catch` with `{"search_id": 1, "fly_id": "stimulator", "outcome": "caught"}`.

## Test Jev before trusting it

Put real fishing reports in a CSV shaped like `eval/reports_template.csv` (its rows are made-up examples), then:

```bash
python -m eval.backtest eval/reports.csv --jev
```

It prints how often a fly the report named lands in the top 5, for the rules and for Jev.

## Other scripts

- `python -m pytest`: tests. Jev and the USGS and weather services are faked, so no key or network is needed.
- `python -m scripts.build_page`: writes `dist/fly-picker-demo.html`, a standalone demo that runs the rules in the browser.
- `python -m scripts.check_parity`: checks that the browser engine (`web/engine.js`) ranks exactly like `flypicker/rules.py`. It needs node.

## Known gaps

- The catalog is hand-tagged from general knowledge. Kenny and Trout Candy are tagged as soft-hackle wets from how Elk River reports describe them, not from a recipe. It still needs matching to the ~2,087 patterns on flysandguides.com, whose site couldn't be reached from the build environment.
- Hatch timing is broad-brush for three US regions. Per-river charts, the Pacific coast in saltwater, and time of day aren't covered yet.
- The live USGS and weather lookups were tested against canned responses only, because the build environment couldn't reach those services. USGS is moving to a new Water Data API, and `flypicker/conditions.py` notes where to switch.
- The Jev integration was tested against a fake API, not the real service, because no key was available. The SDK doesn't document a limit on questions per call, so candidates go out in chunks of 24 (`FLYPICKER_JEV_CHUNK`).
