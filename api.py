"""PlateRank web app backend (FastAPI). Start everything with:  python run.py

Thin HTTP layer over platerank/ - no scoring logic lives here. Errors come back as
{"detail": "<plain English + what to do next>"}; the UI shows that text as-is.
The React frontend is served from web/dist (prebuilt - no Node needed to run it).
"""
import os, threading, time, uuid
from pathlib import Path

from dotenv import load_dotenv
if not os.getenv("PLATERANK_TESTING"):  # offline checks must never pick up the real key
    load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from platerank import llm, places, pipeline
from platerank.store import list_profiles, save_profile, slugify, load_profile
from platerank.queries import generate_queries
from platerank.discovery import suggest_competitors
from platerank.scrape import read_menu_file, read_menu_from_link

app = FastAPI(title="PlateRank AI")
WEB = Path(__file__).parent / "web" / "dist"


def _plain(status: int):
    async def handler(_req, exc: Exception):
        msg = ("Claude's rate limit was hit. Wait a minute and try again." if isinstance(exc, llm.QuotaError) else str(exc))
        return JSONResponse({"detail": msg}, status_code=status)
    return handler


# Errors we expect come back as a plain sentence the UI shows as-is - never a traceback.
for _exc, _status in ((ValueError, 400), (llm.ClaudeUnavailable, 400), (places.PlacesError, 400), (llm.QuotaError, 429)):
    app.add_exception_handler(_exc, _plain(_status))


@app.exception_handler(Exception)
async def unexpected(_req, exc: Exception):
    return JSONResponse({"detail": f"Something went wrong ({type(exc).__name__}). Try again; if it keeps "
                                   "happening, check the terminal window running PlateRank."}, status_code=500)


def _profile_or_404(slug: str) -> dict:
    p = pipeline.get_profile(slug)
    if p is None:
        raise HTTPException(404, "That restaurant isn't saved yet.")
    return p


# ------------------------------------------------------------------ status + restaurants
@app.get("/api/status")
def status():
    return {"claude_key": llm.has_key(), "gemini_key": bool((os.getenv("GOOGLE_API_KEY") or "").strip()),
            "platforms": pipeline.available_platforms(), "claude_model": llm.default_model(),
            "discovery_model": llm.discovery_model()}


@app.get("/api/restaurants")
def restaurants():
    out = []
    for name in list_profiles():
        p = load_profile(name)
        last = pipeline._read(pipeline.state_dir(slugify(name)) / "last_run.json", None)
        out.append({"slug": slugify(name), "name": name, "cuisine": p.get("cuisine", ""), "area": p.get("area", ""),
                    "competitors": len(p.get("competitors", [])), "last_run": last["meta"]["when"] if last else None,
                    "pinned": bool(p.get("pinned"))})
    out.sort(key=lambda r: not r["pinned"])  # pinned first, otherwise keep A-Z
    ex = pipeline.get_profile(pipeline.EXAMPLE_SLUG)
    return {"restaurants": out, "example": {"slug": pipeline.EXAMPLE_SLUG, "name": ex["name"], "cuisine": ex["cuisine"],
                                            "area": ex["area"], "sample": True}}


@app.get("/api/restaurants/{slug}")
def get_restaurant(slug: str):
    p = _profile_or_404(slug)
    return {"slug": slug, "profile": p, "is_sample": slug == pipeline.EXAMPLE_SLUG,
            "query_count": 30 if slug == pipeline.EXAMPLE_SLUG else len(generate_queries(p))}


class ProfileIn(BaseModel):
    profile: dict
    previous_slug: str | None = None


@app.put("/api/restaurants")
def put_restaurant(body: ProfileIn):
    p = body.profile
    for k in ("name", "cuisine", "area"):
        if not str(p.get(k) or "").strip():
            raise ValueError(f"'{k}' is required.")
    if body.previous_slug == pipeline.EXAMPLE_SLUG or slugify(p["name"]) == pipeline.EXAMPLE_SLUG:
        raise ValueError("The sample restaurant can't be edited - add your own restaurant instead.")
    base = pipeline.get_profile(body.previous_slug) if body.previous_slug else None
    merged = {**(base or {}), **p}
    merged.setdefault("competitors", [])
    merged.setdefault("competitor_menus", {})
    merged.setdefault("menu", {})
    save_profile(merged)
    return {"slug": slugify(merged["name"]), "profile": merged}


class PinIn(BaseModel):
    pinned: bool


@app.post("/api/restaurants/{slug}/pin")
def pin(slug: str, body: PinIn):
    _profile_or_404(slug)
    p = pipeline.set_pinned(slug, body.pinned)
    return {"slug": slug, "pinned": p["pinned"]}


# ------------------------------------------------------------------ setup helpers
@app.get("/api/cities")
def cities():
    return {"cities": places.cities(), "source": "GeoNames (CC BY 4.0) - every US city/borough with 50,000+ people"}


@app.get("/api/places/search")
def places_search(q: str, city: str | None = None, lat: float | None = None, lon: float | None = None):
    c = places.city_by_id(city)
    if city and c is None:
        raise ValueError("Pick the city from the list first.")
    return {"results": places.search_restaurants(q, lat, lon, city=c)}


@app.get("/api/places/details")
def places_details(osm_type: str, osm_id: int):
    return places.place_details(osm_type, osm_id)


@app.get("/api/places/nearby")
def places_nearby(lat: float, lon: float, radius: int = 800, cuisine: str = "", exclude: str = "",
                  slug: str | None = None, fresh: bool = False):
    return pipeline.nearby(slug, lat, lon, radius, cuisine, exclude, fresh)


class LookupIn(BaseModel):
    name: str
    city: str


@app.post("/api/web-lookup")
def web_lookup(body: LookupIn):
    """Restaurant not on the map: Claude + web search finds its public basics (~$0.05), with sources."""
    c = places.city_by_id(body.city)
    if c is None:
        raise ValueError("Pick the city from the list first.")
    if len(body.name.strip()) < 2:
        raise ValueError("Type the restaurant's name first.")
    return places.web_lookup(body.name.strip(), c)


class FactsIn(BaseModel):
    profile: dict


@app.post("/api/web-facts")
def web_facts(body: FactsIn):
    """Claude + web search: price level, rating, review count... each with its source. Costs ~$0.03-0.08."""
    return places.web_facts(body.profile)


@app.post("/api/restaurants/{slug}/suggest-competitors")
def suggest(slug: str):
    return suggest_competitors(_profile_or_404(slug))


class ListingIn(BaseModel):
    restaurant: str
    rating: float | None = None
    review_count: int | None = None
    price_level: int | None = Field(None, ge=1, le=4)
    source: str


@app.post("/api/restaurants/{slug}/listings")
def save_listing(slug: str, body: ListingIn):
    _profile_or_404(slug)
    return pipeline.save_listing(slug, body.restaurant, {"rating": body.rating, "review_count": body.review_count,
                                                         "price_level": body.price_level}, body.source)


@app.post("/api/restaurants/{slug}/listings/auto")
def auto_listings(slug: str):
    """Claude web search for the restaurant + each competitor's public Google rating / reviews / price level.
    Returned for the owner to check - saved only through POST .../listings."""
    p = _profile_or_404(slug)
    out = []
    for c in [p] + p.get("competitors", []):
        prof = {"name": c["name"], "address": c.get("address") or p.get("address"), "area": p.get("area"),
                "city": p.get("city")}
        try:
            f = places.web_facts(prof)
            out.append({"restaurant": c["name"], "rating": f.get("google_rating"),
                        "review_count": f.get("google_review_count"), "price_level": f.get("price_level"),
                        "sources": f.get("sources") or {}, "cost_usd": f.get("_cost_usd", 0)})
        except Exception as e:
            out.append({"restaurant": c["name"], "error": str(e)})
    return {"results": out}


@app.post("/api/restaurants/{slug}/menu/read")
async def menu_read(slug: str, file: UploadFile | None = File(None), url: str = Form("")):
    _profile_or_404(slug)
    if file is not None:
        data = await file.read()
        items = read_menu_file(data, file.content_type or "application/pdf")
        return {"items": items, "source": f"uploaded file '{file.filename}'"}
    if url.strip():
        items, src = read_menu_from_link(url.strip())
        return {"items": items, "source": src}
    raise ValueError("Upload a menu photo/PDF or paste a menu link.")


class ReviewsIn(BaseModel):
    restaurant: str
    avg_rating: float = Field(..., ge=1, le=5)
    review_count: int | None = None
    source: str
    text: str


@app.post("/api/restaurants/{slug}/reviews")
def reviews(slug: str, body: ReviewsIn):
    _profile_or_404(slug)
    return pipeline.save_reviews_text(slug, body.restaurant, body.avg_rating, body.review_count, body.source, body.text)


# ------------------------------------------------------------------ discovery jobs
JOBS: dict[str, dict] = {}


class RunIn(BaseModel):
    runs: int = Field(1, ge=1, le=3)
    reuse: bool = True
    web_search: bool = True
    platforms: list[str] | None = None


@app.get("/api/restaurants/{slug}/estimate")
def estimate(slug: str, runs: int = 1):
    _profile_or_404(slug)
    return pipeline.estimate_calls(slug, runs, pipeline.available_platforms())


@app.post("/api/restaurants/{slug}/run")
def start_run(slug: str, body: RunIn):
    _profile_or_404(slug)
    if any(j["slug"] == slug and j["state"] == "running" for j in JOBS.values()):
        raise ValueError("A check is already running for this restaurant.")
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "slug": slug, "state": "running", "done": 0, "total": 0, "note": "Starting…",
           "error": None, "meta": None, "stop": False, "started": time.time()}
    JOBS[jid] = job

    def progress(done, total, note):
        job.update(done=done, total=total, note=note)

    def work():
        try:
            job["meta"] = pipeline.run(slug, body.runs, body.reuse, body.platforms, body.web_search,
                                       progress=progress, should_stop=lambda: job["stop"])
            job["state"] = "done"
        except Exception as e:
            job["error"] = str(e) if isinstance(e, (ValueError, llm.ClaudeUnavailable)) else \
                f"The check stopped ({type(e).__name__}). Answers that arrived were saved - run again to continue."
            job["state"] = "failed"

    threading.Thread(target=work, daemon=True).start()
    return job


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "That check isn't running any more.")
    return JOBS[jid]


@app.post("/api/jobs/{jid}/stop")
def stop(jid: str):
    if jid in JOBS:
        JOBS[jid]["stop"] = True
    return {"ok": True}


# ------------------------------------------------------------------ results + actions
@app.get("/api/restaurants/{slug}/results")
def get_results(slug: str):
    _profile_or_404(slug)
    # before the first check: only "Make the changes" (FAQ, email, content pack) - marked no_run
    return pipeline.results(slug) or pipeline.make_before_run(slug)


@app.post("/api/restaurants/{slug}/site-audit")
def site_audit(slug: str):
    _profile_or_404(slug)
    return pipeline.run_site_audit(slug)


class ApproveIn(BaseModel):
    key: str
    text: str = ""
    undo: bool = False


@app.post("/api/restaurants/{slug}/approve")
def approve(slug: str, body: ApproveIn):
    _profile_or_404(slug)
    return (pipeline.remove_approval(slug, body.key) if body.undo else pipeline.save_approval(slug, body.key, body.text))


class PackIn(BaseModel):
    regenerate: bool = False


@app.post("/api/restaurants/{slug}/content-pack")
def content_pack(slug: str, body: PackIn):
    """Claude writes the pack's wording once (cached); regenerate=true asks again."""
    _profile_or_404(slug)
    pipeline.generate_content_pack(slug, body.regenerate)
    return {"ok": True}


@app.get("/api/restaurants/{slug}/website-pack.zip")
def website_pack(slug: str):
    p = _profile_or_404(slug)
    return Response(pipeline.website_pack(slug), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{slugify(p["name"])}-website-pack.zip"'})


# ------------------------------------------------------------------ frontend
if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Unknown API route.")
    f = WEB / path
    if path and f.is_file():
        return FileResponse(f)
    if (WEB / "index.html").exists():
        return FileResponse(WEB / "index.html")
    return JSONResponse({"detail": "Frontend not built. Run:  cd web && npm install && npm run build"}, status_code=503)
