"""Fly Picker web app.  Run:  uvicorn app:app --reload   then open http://localhost:8000"""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from flypicker import catalog, catchlog, jev
from flypicker.recommend import BadRequest, recommend

ROOT = Path(__file__).parent
app = FastAPI(title="Fly Picker")


class SearchIn(BaseModel):
    river: str | None = None  # a home-river preset from flypicker/data/rivers.json; sets region and water type
    region: str | None = None
    water_type: str | None = None
    date: str | None = None
    fly_type: str = "any"
    water_temp_f: float | None = None
    sky: str | None = None
    windy: bool = False
    flow: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None
    engine: Literal["auto", "rules", "jev"] = "auto"


class CatchIn(BaseModel):
    search_id: int
    fly_id: str
    outcome: Literal["caught", "no_luck"]
    fish_count: int | None = None
    notes: str | None = None


def page() -> str:
    """The same page as the offline demo, but told to call this server."""
    from scripts.build_page import build
    return build(server=True)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return page()


@app.get("/api/options")
def options() -> dict:
    cat = catalog.load()
    return {
        "regions": cat.regions,
        "water_types": {k: v["name"] for k, v in cat.water_types.items()},
        "fly_types": catalog.FLY_TYPES,
        "rivers": {k: v["label"] for k, v in cat.rivers.items()},
        "jev": jev.available(),
    }


@app.post("/api/recommend")
def api_recommend(body: SearchIn) -> dict:
    req = body.model_dump(exclude={"engine"})
    try:
        result = recommend(req, mode=body.engine)
    except BadRequest as e:
        raise HTTPException(400, str(e))
    result["search_id"] = catchlog.log_search(req, result)
    return result


@app.post("/api/catch")
def api_catch(body: CatchIn) -> dict:
    if body.fly_id not in catalog.load().flies:
        raise HTTPException(400, "Unknown fly")
    try:
        catchlog.log_outcome(body.search_id, body.fly_id, body.outcome, body.fish_count, body.notes)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}
