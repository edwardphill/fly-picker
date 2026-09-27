"""Builds the web page from web/page.html, web/engine.js and the catalog data.

    python -m scripts.build_page            # writes dist/fly-picker-demo.html (offline demo, rules only)

The app serves the same page with server=True, so the page calls the API instead of the
in-browser engine.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flypicker import catalog  # noqa: E402


def page_data() -> dict:
    cat = catalog.load()
    return {
        "regions": cat.regions,
        "water_types": cat.water_types,
        "typical_temp": cat.typical_temp,
        "fly_types": catalog.FLY_TYPES,
        "foods": cat.foods,
        "flies": {k: {**v, "water": sorted(v["water"])} for k, v in cat.flies.items()},
        "rivers": cat.rivers,
    }


def build(server: bool = False) -> str:
    html = (ROOT / "web" / "page.html").read_text()
    engine = (ROOT / "web" / "engine.js").read_text()
    data = json.dumps(page_data(), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page = (html.replace("/*__DATA__*/null", data)
                .replace("/*__SERVER__*/false", "true" if server else "false")
                .replace("/*__ENGINE__*/", engine))
    if server:
        # The artifact host adds this skeleton for the demo; the app serves the page itself.
        page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                '</head><body>' + page + "</body></html>")
    return page


if __name__ == "__main__":
    out = ROOT / "dist" / "fly-picker-demo.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(server=False))
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
