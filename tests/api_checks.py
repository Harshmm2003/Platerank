"""Offline checks for the web app backend + Claude helper + map search. No API calls, no internet.
Claude, OpenStreetMap and website fetches are replaced by fakes. Run from the project root."""
import os, sys, shutil, tempfile, time, json
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0, str(Path.cwd()))
os.environ["PLATERANK_TESTING"] = "1"      # api.py then skips loading the real .env
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + (f": {detail}" if detail and not cond else "")); ok += bool(cond); fail += not cond

from platerank import llm, places, pipeline, store, discovery, evidence

# ---- every cited page is a FAKE: the checks never fetch the real web
import requests as _requests_mod
class FakePage:
    def __init__(self, text, status=200, ctype="text/html"): self.text, self.status_code, self.headers = text, status, {"content-type": ctype}
FILLER = " Lorem ipsum menu reservations directions parking gift cards catering private dining. " * 8
FAKE_PAGES = {
    "https://cafeathena.com": FakePage("<html><head><title>Caf&eacute; Athena - Pacific Beach</title><script>var x='4.9';</script></head><body>"
        "<h1>Café Athena</h1><p>Greek &amp; Mediterranean in Pacific Beach since 1990.</p><p>1846 Garnet Avenue, San Diego, CA 92109</p>"
        "<p>Sun–Thu 11:00 AM – 9:00 PM · Fri–Sat 11:00 AM – 9:30 PM</p><p>Rated 4.5 by 1,234 diners. $$</p>"
        "<p>“Cafe Athena’s lamb gyro is the best thing on Garnet” - a regular</p>" + FILLER + "</body></html>"),
    "https://slow.example": "timeout",
    "https://blocked.example": FakePage("Forbidden", status=403),
    "https://jsapp.example": FakePage("<html><body><div id=root></div><script>render()</script></body></html>"),
    "https://other.example/list": FakePage("<html><body><h2>Best Greek in PB</h2><p>Olive Tree Taverna and Athens Market are favourites.</p>" + FILLER + "</body></html>"),
}
def fake_fetch(url, timeout=None, headers=None):
    assert timeout == 8 and "PlateRank" in headers["User-Agent"], (timeout, headers)
    page = FAKE_PAGES.get(url)
    if page == "timeout": raise _requests_mod.exceptions.ReadTimeout("fake slow page")
    if page is None: raise _requests_mod.exceptions.ConnectionError("fake: no such page")
    return page
evidence.FETCH = fake_fetch

# ---- work on a COPY of data/ so checks never touch real saved data
real_data = store.DATA
tmp = Path(tempfile.mkdtemp()) / "data"
shutil.copytree(real_data, tmp, ignore=shutil.ignore_patterns("runs.db", "last_run.json", "example_state"))
for mod in (store, pipeline):
    mod.DATA = tmp
store.LIVE, store.DB, store.EXAMPLE_PROFILE = tmp / "live", tmp / "runs.db", tmp / "example_profile.json"
pipeline.EXAMPLE_DIR = tmp / "example_state"
import platerank.creators as creators_mod
creators_mod.LIVE = tmp / "live" / "creators_live.json"

# ---- llm: response parsing, cost, errors (fake SDK response objects)
fake_msg = NS(model="claude-sonnet-5-5", stop_reason="end_turn",
              content=[NS(type="server_tool_use"),
                       NS(type="web_search_tool_result", content=[NS(url="https://www.eater.com/x", title="Eater"),
                                                                  NS(url="https://reddit.com/r/nyc", title="Reddit")]),
                       NS(type="text", text="1. **Sushi A**", citations=[NS(url="https://www.eater.com/x", title="Eater")])],
              usage=NS(input_tokens=10000, output_tokens=1000, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                       server_tool_use=NS(web_search_requests=2, web_fetch_requests=0)))
class FakeClient:
    def __init__(self): self.messages = NS(create=self.create); self.kwargs = None
    def create(self, **kw): self.kwargs = kw; return fake_msg
fc = FakeClient()
llm._client = fc
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
r = llm.claude_call("hi", model="claude-sonnet-5-5", tools=[llm.web_search_tool(location={"city": "New York"})])
check("llm: text + sources parsed", r.text == "1. **Sushi A**" and [s["url"] for s in r.sources] == ["https://www.eater.com/x", "https://reddit.com/r/nyc"], r)
check("llm: cost = tokens + searches", abs(r.cost_usd - (0.02 + 0.01 + 0.02)) < 1e-6, r.cost_usd)
check("llm: web search tool sent with location", fc.kwargs["tools"][0]["user_location"]["city"] == "New York", fc.kwargs)
check("llm: refusal fallbacks sent in the body (works on old + new SDKs)",
      fc.kwargs["extra_body"].get("fallbacks") == "default" and "fallbacks" not in fc.kwargs
      and fc.kwargs["extra_headers"]["anthropic-beta"].startswith("server-side-fallback"), fc.kwargs)
llm.claude_call("hi", model="claude-haiku-5-5", effort=None)
check("llm: no fallbacks / effort for haiku when not asked", not fc.kwargs["extra_body"] and not fc.kwargs["extra_headers"], fc.kwargs)
import anthropic, inspect
real_params = set(inspect.signature(anthropic.Anthropic(api_key="x").messages.create).parameters)
llm.claude_call("hi", model="claude-opus-5-5", tools=[llm.web_search_tool()], tool_choice={"type": "any"})
unknown = set(fc.kwargs) - real_params
check("llm: only arguments this anthropic package version accepts", not unknown, unknown)
check("llm: location_for NYC", llm.location_for({"city": "New York"})["timezone"] == "America/New_York")
check("llm: json_from tolerates fences", llm.json_from('```json\n[{"a":1}]\n```') == [{"a": 1}])
del os.environ["ANTHROPIC_API_KEY"]

class NoRealCalls:
    """Any Claude call after this point is a bug in the checks - fail loudly instead of spending money."""
    @property
    def messages(self): raise AssertionError("an offline check tried to call Claude")
llm._client = NoRealCalls()
try:
    llm.claude_call("hi"); check("llm: no key -> plain error", False)
except llm.ClaudeUnavailable as e:
    check("llm: no key -> plain error", "ANTHROPIC_API_KEY" in str(e))

# ---- discovery with Claude-style answers (answer, model, sources, cost)
from platerank.queries import Query
discovery.ASK["fakeclaude"] = lambda q, **kw: (f"Try YONO Sushi ({q})", "fake", [{"url": "https://eater.com/a", "title": "Eater"}], 0.05)
cache = Path(tempfile.mkdtemp()) / "answers.json"
rows = discovery.run_discovery([Query("q1", "generic")], "YONO Sushi", [], "fakeclaude", cache_path=cache, ask_opts={"web_search": True})
check("discovery: sources + cost kept on the row", rows[0]["sources"][0]["url"] == "https://eater.com/a" and rows[0]["cost_usd"] == 0.05, rows[0])
check("discovery: sources saved in cache", "eater.com" in cache.read_text())
rows = discovery.run_discovery([Query("q1", "generic")], "YONO Sushi", [], "fakeclaude", cache_path=cache)
check("discovery: cached row keeps its sources", rows[0]["status"] == "CACHED" and rows[0]["sources"], rows[0])
def bad_key(q, **kw): raise llm.ClaudeUnavailable("The Claude key in .env was rejected.")
discovery.ASK["badkey"] = bad_key
rows = discovery.run_discovery([Query(f"q{i}", "generic") for i in range(3)], "X", [], "badkey", cache_path=None)
check("discovery: bad key stops the run, plain reason on every row", all(r["status"] == "FAILED" and "rejected" in r["note"] for r in rows), [r["note"] for r in rows])

# ---- places (fake HTTP)
class Resp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data
places.requests.get = lambda *a, **k: Resp({"features": [{"properties": {"name": "YONO Sushi", "osm_type": "N", "osm_id": 7, "osm_value": "restaurant",
                                                                          "street": "8th Ave", "housenumber": "421", "city": "New York"},
                                                           "geometry": {"coordinates": [-73.9965, 40.7505]}}]})
hits = places.search_restaurants("YONO")
check("places: search -> dropdown rows", hits and hits[0]["name"] == "YONO Sushi" and hits[0]["osm_type"] == "node" and "421 8th Ave" in hits[0]["address"], hits)
places.requests.post = lambda *a, **k: Resp({"elements": [
    {"type": "node", "id": 1, "lat": 40.751, "lon": -73.997, "tags": {"name": "Sushi Near", "cuisine": "sushi;japanese"}},
    {"type": "node", "id": 2, "lat": 40.760, "lon": -73.990, "tags": {"name": "Pizza Far", "cuisine": "pizza"}},
    {"type": "way", "id": 3, "center": {"lat": 40.752, "lon": -73.996}, "tags": {"name": "Ramen Spot", "cuisine": "ramen"}},
    {"type": "node", "id": 4, "lat": 40.7505, "lon": -73.9965, "tags": {"name": "YONO Sushi", "cuisine": "sushi"}}]})
near = places.nearby_restaurants(40.7505, -73.9965, 800, "sushi", exclude_name="YONO Sushi")
check("places: radius search, same cuisine first, excludes itself", [n["name"] for n in near] == ["Sushi Near", "Pizza Far", "Ramen Spot"] or
      ([n["name"] for n in near][0] == "Sushi Near" and "YONO Sushi" not in [n["name"] for n in near]), near)
check("places: distance in metres", near[0]["distance_m"] and near[0]["distance_m"] < 200, near[0])
check("places: cuisine words", places.cuisine_words("sushi") == ["sushi", "japanese"])

# ---- city list + city-filtered search
cs = places.cities()
check("cities: full US list (50k+ people), biggest first", len(cs) > 800 and cs[0]["id"] == "New York City|NY", (len(cs), cs[0]))
check("cities: boroughs + small cities included", all(places.city_by_id(i) for i in ("Brooklyn|NY", "Manhattan|NY", "Boulder|CO")))
seen_params = {}
def fake_get(url, params=None, **k):
    seen_params["p"] = params
    return Resp({"features": [
        {"properties": {"name": "Sushi In Town", "osm_type": "N", "osm_id": 1, "osm_value": "restaurant", "city": "New York"},
         "geometry": {"coordinates": [-73.99, 40.75]}},
        {"properties": {"name": "Sushi In LA", "osm_type": "N", "osm_id": 2, "osm_value": "restaurant", "city": "Los Angeles"},
         "geometry": {"coordinates": [-118.24, 34.05]}}]})
places.requests.get = fake_get
hits = places.search_restaurants("sushi", city=places.city_by_id("New York City|NY"))
check("search: only restaurants inside the chosen city", [h["name"] for h in hits] == ["Sushi In Town"], hits)
check("search: city area sent to the map service", any(k == "bbox" for k, _ in seen_params["p"]), seen_params)
places.requests.get = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline"))
try:
    places.search_restaurants("YONO"); check("places: offline -> plain error", False)
except places.PlacesError as e:
    check("places: offline -> plain error", "type the restaurant in by hand" in str(e))

# ---- API (FastAPI test client)
from fastapi.testclient import TestClient
import api
api.pipeline = pipeline
check("api: checks never load the real key from .env", not llm.has_key())
c = TestClient(api.app)
s = c.get("/api/status").json()
check("api: status reports no key", s["claude_key"] is False and s["platforms"] == [], s)
lst = c.get("/api/restaurants").json()
check("api: lists saved restaurants + sample", lst["example"]["slug"] == "example" and any(x["slug"] == "yono_sushi" for x in lst["restaurants"]), lst)
check("api: unknown restaurant -> 404 plain", c.get("/api/restaurants/nope").json()["detail"].startswith("That restaurant"))
bad = c.put("/api/restaurants", json={"profile": {"name": "X", "cuisine": "", "area": "y"}})
check("api: missing required field -> 400 plain", bad.status_code == 400 and "cuisine" in bad.json()["detail"], bad.json())
check("api: sample can't be overwritten", c.put("/api/restaurants", json={"profile": {"name": "N", "cuisine": "c", "area": "a"}, "previous_slug": "example"}).status_code == 400)
new = c.put("/api/restaurants", json={"profile": {"name": "Check Diner", "cuisine": "diner", "area": "Union Square", "city": "New York",
                                                   "competitors": [{"name": "Other Diner"}]}}).json()
check("api: save new restaurant", new["slug"] == "check_diner" and (tmp / "live" / "check_diner" / "profile.json").exists(), new)
check("api: never wrote into the real data folder", not (real_data / "live" / "check_diner").exists())

# pin / unpin: stored in profile.json, pinned listed first, survives an edit, sample can't be pinned
pn = c.post("/api/restaurants/check_diner/pin", json={"pinned": True})
check("pin: saved in profile.json", pn.json()["pinned"] is True and
      json.loads((tmp / "live" / "check_diner" / "profile.json").read_text(encoding="utf-8"))["pinned"] is True, pn.json())
lst = c.get("/api/restaurants").json()["restaurants"]
check("pin: pinned restaurant listed first, others unpinned", lst[0]["slug"] == "check_diner" and lst[0]["pinned"]
      and not any(r["pinned"] for r in lst[1:]), [(r["slug"], r["pinned"]) for r in lst])
# Setup sends a partial profile (no "pinned") - the saved pin must survive the merge
c.put("/api/restaurants", json={"profile": {"name": "Check Diner", "cuisine": "diner", "area": "Union Sq"}, "previous_slug": "check_diner"})
check("pin: editing the profile keeps the pin", c.get("/api/restaurants/check_diner").json()["profile"].get("pinned") is True)
c.post("/api/restaurants/check_diner/pin", json={"pinned": False})
check("pin: unpin saved", not any(r["pinned"] for r in c.get("/api/restaurants").json()["restaurants"]))
sp = c.post("/api/restaurants/example/pin", json={"pinned": True})
check("pin: sample can't be pinned -> plain 400", sp.status_code == 400 and "sample" in sp.json()["detail"], sp.json())
check("pin: unknown restaurant -> 404", c.post("/api/restaurants/nope/pin", json={"pinned": True}).status_code == 404)
check("pin: never wrote into the real data folder", not (real_data / "live" / "check_diner").exists())

def wait(jid):
    for _ in range(100):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] != "running": return j
        time.sleep(0.05)
    return j
j = wait(c.post("/api/restaurants/example/run", json={}).json()["id"])
check("api: sample run finishes", j["state"] == "done" and j["meta"]["counts"]["DEMO"] == 30, j)
res = c.get("/api/restaurants/example/results").json()
check("api: results have all 5 owner questions", all(k in res for k in ("rank", "why", "change", "make", "improve")), list(res))
check("api: sample is labelled", res["is_sample"] is True)
check("api: sample mention rate 17%", res["rank"]["mention_rate"] == 0.17, res["rank"]["mention_rate"])
check("api: gaps routed to engines", {g["action"] for g in res["why"]["gaps"]} <= {"standard", "creator", "vfm"} and res["why"]["gaps"])
check("api: drafts ready for approval (old schema card replaced by the content pack)", [d["key"] for d in res["make"]["drafts"]] == ["faq_page", "outreach_email"], [d["key"] for d in res["make"]["drafts"]])
c.post("/api/restaurants/example/approve", json={"key": "faq_page", "text": "edited FAQ"})
check("api: approval recorded", c.get("/api/restaurants/example/results").json()["approvals"]["faq_page"]["text"] == "edited FAQ")
c.post("/api/restaurants/example/approve", json={"key": "faq_page", "undo": True})
check("api: approval undone", "faq_page" not in c.get("/api/restaurants/example/results").json()["approvals"])
au = c.post("/api/restaurants/example/site-audit").json()
check("api: sample site audit uses SAMPLE records", all(v["source"] == "SAMPLE record" for v in au.values()), au)

# YONO with no key: saved Gemini answers can still be shown, missing ones are FAILED (not faked)
j = wait(c.post("/api/restaurants/yono_sushi/run", json={"runs": 1}).json()["id"])
check("api: no key -> saved answers only, rest FAILED", j["state"] == "done" and j["meta"]["counts"]["LIVE"] == 0 and j["meta"]["counts"]["CACHED"] > 0, j)
yr = c.get("/api/restaurants/yono_sushi/results").json()
check("api: FAILED rows excluded from numbers", yr["rank"]["answers"] == j["meta"]["counts"]["CACHED"], (yr["rank"]["answers"], j["meta"]["counts"]))
rv = c.post("/api/restaurants/check_diner/reviews", json={"restaurant": "Check Diner", "avg_rating": 4.2, "source": "Google Maps",
                                                            "text": "5 | Great pancakes, fair price.\nnot a review line\n2 | Too loud."})
check("api: reviews pasted (bad lines skipped)", rv.json() == {"saved": 2, "skipped_lines": 1}, rv.json())
check("api: reviews need a source", c.post("/api/restaurants/check_diner/reviews", json={"restaurant": "Check Diner", "avg_rating": 4, "source": " ", "text": "5 | ok"}).status_code == 400)
check("api: unknown api route -> 404 json", c.get("/api/nope").status_code == 404)
check("api: city list served", len(c.get("/api/cities").json()["cities"]) > 800)
bad_city = c.get("/api/places/search?q=sushi&city=Atlantis|ZZ")
check("api: unknown city -> plain 400", bad_city.status_code == 400 and "city" in bad_city.json()["detail"], bad_city.json())
places.requests.get = fake_get
ok_city = c.get("/api/places/search?q=sushi&city=New York City|NY").json()["results"]
check("api: search filtered by city", [h["name"] for h in ok_city] == ["Sushi In Town"], ok_city)
# restaurant not on the map -> web lookup (fake Claude) + address placed on the map (fake Photon)
places.requests.get = lambda *a, **k: Resp({"features": [{"properties": {"name": "Garnet Avenue", "osm_key": "highway"},
                                                           "geometry": {"coordinates": [-117.2388, 32.8002]}}]})
real_call = llm.claude_call
llm.claude_call = lambda *a, **k: llm.ClaudeResult(text='{"name": "Café Athena", "address": "1846 Garnet Ave, San Diego, CA 92109", '
    '"neighbourhood": "Pacific Beach", "cuisine": "Greek", "found": true, "sources": {"name": "https://cafeathena.com", '
    '"address": "https://cafeathena.com", "neighbourhood": "https://cafeathena.com", "cuisine": "https://cafeathena.com"}}', model="fake")
wl = c.post("/api/web-lookup", json={"name": "Cafe Athena", "city": "San Diego|CA"}).json()
check("web lookup: basics + sources + map point", wl["name"] == "Café Athena" and wl["sources"]["address"] and
      abs(wl["_point"]["lat"] - 32.8002) < 1e-3 and wl["_point"]["precision"].startswith("street"), wl)
llm.claude_call = lambda *a, **k: llm.ClaudeResult(text='{"found": false}', model="fake")
nf = c.post("/api/web-lookup", json={"name": "Nowhere Diner", "city": "San Diego|CA"})
check("web lookup: not confirmed -> plain 400, nothing invented", nf.status_code == 400 and "couldn't confirm" in nf.json()["detail"], nf.json())
check("web lookup: city required", c.post("/api/web-lookup", json={"name": "X Y", "city": "Atlantis|ZZ"}).status_code == 400)
llm.claude_call = real_call
check("llm: state becomes the search region", llm.location_for({"city": "Austin", "state": "TX"})["region"] == "Texas")

# ---- competitor radius search: slow / failed free map never shows an error (fake map)
import requests as _rq
map_calls = []
def slow_map(*a, **k):
    map_calls.append(k.get("timeout")); raise _rq.exceptions.ReadTimeout("fake slow map")
def good_map(*a, **k):
    map_calls.append(k.get("timeout"))
    return Resp({"elements": [{"type": "node", "id": 9, "lat": 32.8001, "lon": -117.2389, "tags": {"name": "Diner Near", "cuisine": "diner"}}]})
nb = lambda radius=800, extra="": c.get(f"/api/places/nearby?lat=32.8&lon=-117.239&radius={radius}&cuisine=diner&exclude=Check%20Diner&slug=check_diner{extra}")
ncache = tmp / "live" / "check_diner" / "nearby_cache.json"
places.requests.post = slow_map
r0 = nb()
check("nearby: slow map + nothing saved -> calm 'map unavailable', not an error", r0.status_code == 200 and r0.json() == {"results": [], "map_unavailable": True}, r0.json())
check("nearby: slow map gives up quickly (short timeout per server)", map_calls and max(map_calls) <= 10, map_calls)
places.requests.post = good_map
r1 = nb().json()
check("nearby: map answer returned + saved for this restaurant", r1["results"][0]["name"] == "Diner Near" and r1["cached_at"] is None and ncache.exists(), r1)
map_calls.clear()
r2 = nb().json()
check("nearby: same search reuses saved results (no map call), labelled with time", not map_calls and r2["cached_at"] and r2["results"] == r1["results"], (map_calls, r2))
nb(extra="&fresh=true")
check("nearby: 'Refresh' asks the map again", len(map_calls) == 1, map_calls)
places.requests.post = slow_map
r3 = nb(radius=1600).json()
check("nearby: slow map -> closest saved radius shown instead", r3["results"] == r1["results"] and r3["cached_radius"] == 800 and r3["cached_at"], r3)
r4 = c.get("/api/places/nearby?lat=1&lon=1&radius=800").json()
check("nearby: no restaurant (no cache) + slow map -> still calm", r4 == {"results": [], "map_unavailable": True}, r4)
check("nearby: cache never written into the real data folder", not (real_data / "live" / "check_diner").exists())

# ---- question bank: highlights, cuisine alternates, area nicknames
import hashlib
from platerank.queries import generate_queries
base = {"name": "Test Bistro", "cuisine": "thai", "area": "Union Square", "neighbourhood": "Flatiron", "city": "New York",
        "landmarks": ["Madison Square Park"], "signature_terms": ["pad see ew"], "price_level": 2}
BASE_BANK_SHA = "6835b4f10ab3a506"  # the 30 questions before highlights existed - changing them breaks every saved answer
bq = generate_queries(base)
check("questions: no new fields -> the same 30 as before (saved answers still reused)",
      len(bq) == 30 and hashlib.sha256("\n".join(q.text for q in bq).encode()).hexdigest()[:16] == BASE_BANK_SHA, len(bq))
taverna = {"name": "Test Taverna", "cuisine": "Greek", "area": "Harbor Point", "neighbourhood": "Harbor Point", "city": "Springfield",
           "address": "12 Ocean Ave, Springfield, CA 90000", "cuisine_alternates": ["Mediterranean"], "area_nicknames": ["HP"],
           "highlights": ["happy hour", "craft cocktails", "private events", "rehearsal dinner", "catering", "gluten-free",
                          "vegan", "outdoor seating"]}
tq = generate_queries(taverna)
texts = [q.text for q in tq]
check("questions: total stays 30-36", 30 <= len(tq) <= 36, len(tq))
check("questions: no duplicates", len({t.lower() for t in texts}) == len(texts))
check("questions: new categories added", {"happy-hour", "drinks", "events"} <= {q.category for q in tq}, sorted({q.category for q in tq}))
check("questions: street from the address", "happy hour with good food near Ocean Ave" in texts, texts[30:])
check("questions: rehearsal dinner + catering", "where to host a rehearsal dinner in Harbor Point" in texts and "Greek catering in Springfield" in texts, texts[30:])
check("questions: cocktails + nickname", "date night spot in HP with good cocktails" in texts, texts[30:])
check("questions: alternate cuisine rotated in", sum("Mediterranean" in t for t in texts) >= 4, texts)
check("questions: area nickname rotated in", sum(" in HP" in t for t in texts) >= 4, texts)
check("questions: no restaurant name in any question", not any("Test Taverna" in t for t in texts))
check("questions: cap keeps one per highlight first (gluten-free kept)", "Mediterranean restaurant with gluten-free options in Springfield" in texts, texts[30:])
oq = [q.text for q in generate_queries({**base, "highlights": ["rooftop views", "barbecue platter"]})]
check("questions: unknown highlight -> one plain question", "thai restaurant with rooftop views in Flatiron" in oq, oq[30:])
check("questions: 'barbecue' is not a bar", not any("good drinks" in t for t in oq), oq[30:])
check("questions: no address -> area used instead of a street",
      "happy hour with good food near Union Square, New York" in [q.text for q in generate_queries({**base, "highlights": ["happy hour"]})])

# new categories flow through Discovery -> Analysis -> gaps -> creators without errors (fake AI answers)
discovery.ASK["fakehl"] = lambda q, **kw: (("Try Test Taverna or Other Taverna" if "happy hour" in q else "Try Other Taverna"), "fake", [], 0.0)
c.put("/api/restaurants", json={"profile": {**taverna, "competitors": [{"name": "Other Taverna"}]}})
pipeline.run("test_taverna", platforms=["fakehl"])
tr = c.get("/api/restaurants/test_taverna/results").json()
rates = {r["category"]: r["mention_rate"] for r in tr["rank"]["by_category"]}
check("pipeline: new categories scored", rates.get("happy-hour") == 1.0 and rates.get("events") == 0.0, rates)
check("pipeline: new categories reach lost categories + creator briefs", "events" in tr["change"]["lost_categories"]
      and all(k in tr for k in ("why", "change", "make")), tr["change"]["lost_categories"])
br = {c_: creators_mod.content_briefs({"handle": "@x", "niches": [c_]}, taverna, [c_])[0]["concept_title"] for c_ in ("happy-hour", "drinks", "events")}
check("creators: briefs for the new categories", "Happy Hour" in br["happy-hour"] and "Cocktail" in br["drinks"] and "Party" in br["events"], br)

# ---- website content pack (fake Claude - no paid calls)
from platerank import content_gen as cg
import zipfile, io
HOURS = "Sun–Thu 11am–9pm, Fri–Sat 11am–9:30pm; happy hour daily 3–6pm"
oh = cg.parse_hours(HOURS)
check("pack: hours parsed into schema, happy hour not counted as opening hours",
      oh == [{"@type": "OpeningHoursSpecification", "dayOfWeek": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"], "opens": "11:00", "closes": "21:00"},
             {"@type": "OpeningHoursSpecification", "dayOfWeek": ["Friday", "Saturday"], "opens": "11:00", "closes": "21:30"}], oh)
check("pack: unclear hours -> not guessed", cg.parse_hours("daily 11-10") is None and cg.parse_hours("call us") is None)
c.put("/api/restaurants", json={"profile": {"name": "Test Taverna", "cuisine": "Greek", "area": "Harbor Point", "hours": HOURS, "lat": 32.8, "lon": -117.24, "city_id": "Springfield|CA",
                                            "year_opened": 1990, "website": "https://taverna.example"}, "previous_slug": "test_taverna"})
tprof = pipeline.get_profile("test_taverna")
rj = cg.restaurant_jsonld(tprof)
check("pack: restaurant schema from facts only", rj["address"]["streetAddress"] == "12 Ocean Ave" and rj["address"]["postalCode"] == "90000"
      and rj["geo"]["latitude"] == 32.8 and rj["openingHoursSpecification"] == oh and rj["foundingDate"] == "1990"
      and rj["servesCuisine"] == ["Greek", "Mediterranean"], rj)
check("pack: unknown phone + price range -> [OWNER TO CONFIRM]", rj["telephone"].startswith(cg.CONFIRM) and rj["priceRange"].startswith(cg.CONFIRM), rj)
check("pack: no dishes saved -> no menu schema", cg.menu_jsonld(tprof) is None)

claude_calls = []
FAKE_PACK = {"about": "Test Taverna has served Greek food at 12 Ocean Ave since 1990. Award-winning chef! Call (619) 555-0101. "
                      "Also visit Harbor Kitchen at 900 Grand Ave. We open at 10am; happy hour runs 3pm to 6pm.",
             "menu_descriptions": [{"name": "Moussaka", "description": "Layers of eggplant, $18."}],
             "landing": {"intro": "A Greek spot in Harbor Point, HP locals call it home.", "meta_description": "Greek food near Ocean Ave",
                         "facts": ["Open Sun–Thu 11am–9pm", "Est. 1985"],
                         "qa": [{"q": "Is there a happy hour?", "a": "Yes - daily 3–6pm."}, {"q": "Phone?", "a": "Call 555-123-4567."}]}}
def fake_pack_call(prompt, **kw):
    claude_calls.append(kw)
    return llm.ClaudeResult(text=json.dumps(FAKE_PACK), model="fake-opus")
llm.claude_call = fake_pack_call
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
g = c.post("/api/restaurants/test_taverna/content-pack", json={})
pk = json.loads((tmp / "live" / "test_taverna" / "content_pack.json").read_text(encoding="utf-8"))
check("pack: generated through llm.py once, cached", g.status_code == 200 and len(claude_calls) == 1 and pk["about"], g.json())
check("pack: fact sheet passed in, honesty rules in the system prompt", "NEVER" in claude_calls[0]["system"].upper() and "OWNER TO CONFIRM" in claude_calls[0]["system"])
for tok in ("(619) 555-0101", "900 Grand Ave", "10am", "Harbor Kitchen", "Award-winning"):
    check(f"pack: invented '{tok}' wrapped for the owner", f"{cg.CONFIRM}: {tok}]" in pk["about"], pk["about"])
for tok in ("12 Ocean Ave", "1990", "3pm", "6pm"):
    check(f"pack: real fact '{tok}' kept as-is", tok in pk["about"] and f"{cg.CONFIRM}: {tok}" not in pk["about"], pk["about"])
check("pack: landing facts checked too", f"{cg.CONFIRM}: 1985]" in pk["landing"]["facts"][1] and f"{cg.CONFIRM}: 555-123-4567]" in pk["landing"]["qa"][1]["a"], pk["landing"])
check("pack: menu copy only for dishes we hold (none -> nothing)", pk["menu_descriptions"] == [], pk["menu_descriptions"])
# the key check: after the guard, no name / address / hours fact is left that the input facts don't contain
facts_in = pipeline._pack_facts("test_taverna", tprof)
all_out = " ".join([pk["about"], pk["landing"]["intro"], *pk["landing"]["facts"], *[x["a"] for x in pk["landing"]["qa"]]])
_, leftover = cg.guard_facts(all_out, facts_in)
check("pack: no name/address/hours fact in the output that isn't in the input facts", not leftover, leftover)
c.post("/api/restaurants/test_taverna/content-pack", json={})
check("pack: reload reuses the saved text (no new Claude call)", len(claude_calls) == 1, len(claude_calls))
c.post("/api/restaurants/test_taverna/content-pack", json={"regenerate": True})
check("pack: Regenerate asks Claude again", len(claude_calls) == 2, len(claude_calls))
tp = c.get("/api/restaurants/test_taverna/results").json()["make"]["pack"]
check("pack: six draft cards", [p_["key"] for p_ in tp["pieces"]] == list(cg.PACK_FILES), [p_["key"] for p_ in tp["pieces"]])
pieces = {p_["key"]: p_ for p_ in tp["pieces"]}
check("pack: landing page has facts, Q&A and JSON-LD", "<h1>Greek &amp; Mediterranean food in Harbor Point - Test Taverna</h1>" in pieces["pack_landing"]["text"]
      and "application/ld+json" in pieces["pack_landing"]["text"], pieces["pack_landing"]["text"][:300])
check("pack: flags shown on the card", "Harbor Kitchen" in pieces["pack_about"]["flags"], pieces["pack_about"]["flags"])
check("pack: menu cards say there are no dishes instead of making them up", "Nothing is made up" in pieces["pack_menu_schema"]["note"]
      and "Nothing is made up" in pieces["pack_menu_copy"]["note"] and not pieces["pack_menu_schema"]["text"])
check("pack: FAQ schema only has answers we know", cg.CONFIRM not in pieces["pack_faq_schema"]["text"] and "happy hour" in pieces["pack_faq_schema"]["text"].lower(),
      pieces["pack_faq_schema"]["note"])
check("pack: not regenerated on reload, no 'facts changed' yet", tp["generated"]["model"] == "fake-opus" and tp["facts_changed"] is False, tp["generated"])
z0 = c.get("/api/restaurants/test_taverna/website-pack.zip")
check("pack: download before any approval -> plain message", z0.status_code == 400 and "Approve" in z0.json()["detail"], z0.text[:200])
bad = c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_restaurant_schema", "text": pieces["pack_restaurant_schema"]["text"]})
check("pack: can't approve while [OWNER TO CONFIRM] remains", bad.status_code == 400 and "OWNER TO CONFIRM" in bad.json()["detail"], bad.json())
fixed = json.loads(pieces["pack_restaurant_schema"]["text"]); fixed.pop("telephone"); fixed.pop("priceRange")
c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_restaurant_schema", "text": json.dumps(fixed, indent=2)})
c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_faq_schema", "text": pieces["pack_faq_schema"]["text"]})
zr = c.get("/api/restaurants/test_taverna/website-pack.zip")
names = zipfile.ZipFile(io.BytesIO(zr.content)).namelist() if zr.status_code == 200 else []
check("pack: zip holds only the approved pieces + head snippet + README", zr.status_code == 200 and zr.headers["content-type"] == "application/zip"
      and sorted(names) == ["README.txt", "head-snippet.html", "schema-faq.json", "schema-restaurant.json"], names)
head = zipfile.ZipFile(io.BytesIO(zr.content)).read("head-snippet.html").decode() if names else ""
check("pack: head snippet wraps each schema in a JSON-LD script tag", head.count('<script type="application/ld+json">') == 2, head[:200])
c.put("/api/restaurants", json={"profile": {"name": "Test Taverna", "cuisine": "Greek", "area": "Harbor Point", "phone": "(555) 010-2030"}, "previous_slug": "test_taverna"})
check("pack: editing facts -> 'facts changed, regenerate'", c.get("/api/restaurants/test_taverna/results").json()["make"]["pack"]["facts_changed"] is True)
check("pack: sample can't generate (no real facts)", c.post("/api/restaurants/example/content-pack", json={}).status_code == 400)
check("pack: sample shows schemas only", c.get("/api/restaurants/example/results").json()["make"]["pack"]["is_sample"] is True)
del os.environ["ANTHROPIC_API_KEY"]
llm.claude_call = real_call
llm._client = NoRealCalls()

# ---- before the first check: "Make the changes" (content pack) already works
nr = c.get("/api/restaurants/check_diner/results")
nj = nr.json()
check("no run yet: results route gives the make-only view (not a 404)", nr.status_code == 200 and nj.get("no_run") is True
      and "rank" not in nj and [p_["key"] for p_ in nj["make"]["pack"]["pieces"]] == list(cg.PACK_FILES), list(nj))
check("no run yet: FAQ + email drafts ready", [d["key"] for d in nj["make"]["drafts"]] == ["faq_page", "outreach_email"])
check("no run yet: unknown restaurant still 404", c.get("/api/restaurants/nope/results").status_code == 404)

# ---- measurement: first vs latest (same question bank only) + tools/recheck.py (fake AI, temp DB)
from platerank import store as _store
ask_log = []
def fake_claude(q, **kw):
    ask_log.append(q)
    hit = "happy hour" in q or (len(ask_log) > 36 and "dietary" not in q and "gluten" in q)
    return (("Try Recheck Cafe or Other Place" if hit else "Try Other Place"), "fake-sonnet", [], 0.01)
real_claude_ask = discovery.ASK["claude"]
discovery.ASK["claude"] = fake_claude
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
c.put("/api/restaurants", json={"profile": {"name": "Recheck Cafe", "cuisine": "Greek", "area": "Harbor Point", "city": "Springfield",
                                            "highlights": ["happy hour"], "competitors": [{"name": "Other Place"}]}})
cmp0 = pipeline.improvement("recheck_cafe")
check("improve: no checks yet -> plain reason", cmp0["comparable"] is False and "No checks" in cmp0["reason"], cmp0)
pipeline.run("recheck_cafe", platforms=["claude"])
n_q = len(ask_log)
check("improve: one check -> asks for a re-check", "Only one check" in pipeline.improvement("recheck_cafe")["reason"])
sys.path.insert(0, str(Path("tools").resolve()))
import recheck
check("recheck: no --yes and nobody to confirm -> nothing spent", recheck.main(["recheck_cafe"], interactive=False) == 1 and len(ask_log) == n_q)
check("recheck: answer other than 'yes' -> cancelled", recheck.main(["recheck_cafe"], ask=lambda _: "no", interactive=True) == 1 and len(ask_log) == n_q)
check("recheck: unknown restaurant -> plain message", recheck.main(["nope", "--yes"]) == 2)
rc = recheck.main(["recheck_cafe", "--yes"])
check("recheck: --yes asks every question fresh (no saved answers reused)", rc == 0 and len(ask_log) == 2 * n_q, (rc, len(ask_log), n_q))
check("recheck: log line written", "fresh=" in (tmp / "live" / "recheck_cafe" / "recheck_log.txt").read_text(encoding="utf-8"))
cmp1 = pipeline.improvement("recheck_cafe")
cats1 = {x["category"]: x for x in cmp1.get("by_category", [])}
check("improve: same questions -> first vs latest compared, labelled directional", cmp1["comparable"] and cmp1["label"].startswith("Directional")
      and cmp1["first"]["mention_rate"] < cmp1["latest"]["mention_rate"] and cmp1["change"]["mention_rate"] > 0, cmp1)
check("improve: per question type before/after", cats1["happy-hour"]["first"] == 1.0 and cats1["dietary"]["latest"] > cats1["dietary"]["first"], cats1)
check("improve: results tab carries the comparison", c.get("/api/restaurants/recheck_cafe/results").json()["improve"]["compare"]["comparable"] is True)
c.put("/api/restaurants", json={"profile": {"name": "Recheck Cafe", "cuisine": "Greek", "area": "Harbor Point", "highlights": ["happy hour", "catering"]},
                                "previous_slug": "recheck_cafe"})
pipeline.run("recheck_cafe", platforms=["claude"], reuse=False)
cmp2 = pipeline.improvement("recheck_cafe")
check("improve: question bank changed -> not compared, says why", cmp2["comparable"] is False and "same questions" in cmp2["reason"], cmp2)
# an older run saved before fingerprints existed: rebuilt from its answer rows
old = _store.load_runs("Recheck Cafe")[0]
groups = _store.answer_runs("Recheck Cafe")
legacy = {k: v for k, v in old.items() if k not in ("bank_hash", "answers_run_ts", "by_category", "platforms", "web_search")}
check("improve: old run without fingerprint rebuilt from its saved answers",
      pipeline._enrich(legacy, groups)["bank_hash"] == old["bank_hash"] and pipeline._enrich(legacy, groups)["by_category"] == old["by_category"])
discovery.ASK["claude"] = real_claude_ask
del os.environ["ANTHROPIC_API_KEY"]

# ---- "Open in email": only for APPROVED outreach drafts, owner sends it themselves
check("email: no link before approval", "outreach_email" not in c.get("/api/restaurants/check_diner/results").json().get("mailto", {}))
c.post("/api/restaurants/check_diner/approve", json={"key": "outreach_email", "text": "Subject: A diner your readers may miss\n\nHi - I run Check Diner.\nThanks!"})
ml = c.get("/api/restaurants/check_diner/results").json()["mailto"].get("outreach_email", "")
check("email: approved -> mailto with subject + body, no recipient",
      ml == "mailto:?subject=A%20diner%20your%20readers%20may%20miss&body=Hi%20-%20I%20run%20Check%20Diner.%0D%0AThanks%21", ml)
check("email: no subject line -> default subject", cg.mailto_link("Hi there", "Collaboration with X").startswith("mailto:?subject=Collaboration%20with%20X&body=Hi%20there"))

# ---- evidence ledger: every web claim re-checked on its cited page (fake pages)
V = lambda kind, text, url="https://cafeathena.com": evidence.verify({"kind": kind, "text": text, "source_url": url, "found_by": "Claude web search"})
check("evidence: address found (Ave vs Avenue)", V("address", "1846 Garnet Ave, San Diego, CA 92109")["status"] == "verified")
check("evidence: rating + review count match loosely (4.5, 1,234)", V("rating", 4.5)["status"] == "verified" and V("review_count", 1234)["status"] == "verified")
check("evidence: hours match in another format (11am vs 11:00 AM)", V("hours", "Sun–Thu 11am–9pm, Fri–Sat 11am–9:30pm")["status"] == "verified")
check("evidence: curly quotes + accents + case normalised", V("quote", '"CAFÉ ATHENA\'S lamb gyro is the best thing on Garnet"')["status"] == "verified")
check("evidence: '...' gaps allowed, in order", V("quote", "Café Athena's lamb gyro ... on Garnet")["status"] == "verified"
      and V("quote", "on Garnet ... lamb gyro")["status"] == "rejected")
check("evidence: numbers inside scripts don't count (4.9 only in JS)", V("rating", 4.9)["status"] == "rejected")
r_missing = V("quote", "Voted best Greek restaurant in San Diego")
check("evidence: loaded but quote missing -> rejected", r_missing["status"] == "rejected" and "not found" in r_missing["check_note"], r_missing)
r_slow = V("rating", 4.5, "https://slow.example")
check("evidence: page timeout -> unverified, says why", r_slow["status"] == "unverified" and "ReadTimeout" in r_slow["check_note"], r_slow)
check("evidence: blocked (403) -> unverified", V("rating", 4.5, "https://blocked.example")["status"] == "unverified")
check("evidence: page needs a browser -> unverified, not rejected", V("rating", 4.5, "https://jsapp.example")["status"] == "unverified")
check("evidence: no link -> unverified", V("rating", 4.5, "")["status"] == "unverified")
check("evidence: competitor short name accepted ('Olive Tree Taverna: Greek Kitchen')", V("name", "Olive Tree Taverna: Greek Kitchen", "https://other.example/list")["status"] == "verified")

# check_facts: verified kept, unverified moved aside (never used), rejected dropped + counted; all in the ledger
ff = {"google_rating": 4.5, "google_review_count": 999, "price_level": 2, "hours": "daily 3am-4am",
      "sources": {"google_rating": "https://cafeathena.com", "google_review_count": "https://cafeathena.com",
                  "price_level": "https://slow.example", "hours": "https://cafeathena.com"}}
evidence.check_facts("ev_test", "Café Athena", ff, places.FACT_KEYS)
check("evidence: only verified values stay filled in", ff["google_rating"] == 4.5 and ff["google_review_count"] is None and ff["price_level"] is None, ff)
check("evidence: unverified kept aside for 'check the link', rejected counted",
      ff["_unverified"] == {"price_level": 2} and ff["_rejected"] == 2 and ff["_evidence"]["google_rating"]["status"] == "verified", ff)
led = evidence.summary("ev_test")
check("evidence: every claim recorded in the ledger (rejected too)", led["counts"] == {"verified": 1, "unverified": 1, "rejected": 2}
      and (tmp / "live" / "ev_test" / "evidence.json").exists() and not (real_data / "live" / "ev_test").exists(), led["counts"])
evidence.check_facts("ev_test", "Café Athena", dict(ff, google_rating=4.5, sources=ff["sources"]), {"google_rating": "rating"})
check("evidence: same claim re-checked, not duplicated", evidence.summary("ev_test")["counts"]["verified"] == 1)

# Suggest competitors: the cited page must mention the name
discovery_real_claude = discovery._suggest_competitors_claude
discovery._suggest_competitors_claude = lambda prof, n: {"suggestions": [
    {"name": "Olive Tree Taverna", "source_url": "https://other.example/list"},
    {"name": "Made Up Grill", "source_url": "https://other.example/list"},
    {"name": "Athens Market", "source_url": "https://slow.example"}], "sources": [], "grounded": True}
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
sg = c.post("/api/restaurants/check_diner/suggest-competitors").json()
by_name = {x["name"]: x["evidence"]["status"] for x in sg["suggestions"]}
check("evidence: competitor not on its cited page -> dropped + counted", by_name == {"Olive Tree Taverna": "verified", "Athens Market": "unverified"}
      and sg["rejected"] == 1, sg)
del os.environ["ANTHROPIC_API_KEY"]
discovery._suggest_competitors_claude = discovery_real_claude
ev_api = c.get("/api/restaurants/check_diner/evidence").json()
check("evidence: Sources panel route lists the ledger", ev_api["counts"]["rejected"] == 1 and any(e["text"] == "Made Up Grill" for e in ev_api["records"]), ev_api["counts"])

# ---- search-citation tier: llm.py keeps cited_text; a quote in the citation of the SAME url = verified (search citation)
cit_msg = NS(model="fake", stop_reason="end_turn", content=[NS(type="text", text="ok", citations=[
              NS(url="https://blocked.example/", title="Blocked", cited_text="Great gyros and super friendly staff, we go every week.")])],
             usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
llm._client = NS(messages=NS(create=lambda **kw: cit_msg))
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
cr = llm.claude_call("hi", model="claude-haiku-5-5", effort=None)
check("citations: cited_text + url kept from web search citations", cr.citations == [{"url": "https://blocked.example/", "title": "Blocked",
      "cited_text": "Great gyros and super friendly staff, we go every week."}], cr.citations)
llm._client = NoRealCalls()
blk = evidence.verify({"kind": "quote", "text": "great gyros and super friendly staff", "source_url": "https://blocked.example"}, citations=cr.citations)
check("citations: blocked page but quote in its search citation -> verified (search citation)",
      blk["status"] == "verified" and blk["tier"] == "search citation" and evidence.badge(blk)["tier"] == "search citation", blk)
check("citations: page fetch tier is labelled too", V("rating", 4.5)["tier"] == "page fetch")
check("citations: citation of a DIFFERENT page doesn't count", evidence.verify({"kind": "quote", "text": "great gyros", "source_url": "https://slow.example"},
      citations=cr.citations)["status"] == "unverified")

# ---- what AI says about you (saved answers only, no AI calls)
said = pipeline.ai_says({"name": "Café Athena", "aliases": []}, [
    {"status": "LIVE", "mentioned": True, "query": "best greek in pb", "platform": "claude", "sources": [{"url": "https://eater.com/x"}],
     "answer": "**Café Athena** is known for its great lamb gyros. However, Cafe Athena can be pricey on weekends. Other Place is fine too."},
    {"status": "FAILED", "mentioned": True, "query": "x", "answer": "Café Athena is wonderful."}])
check("ai says: sentences naming you, grouped praised / criticised", said["counts"] == {"praised": 1, "criticised": 1, "described": 0}
      and said["groups"]["praised"][0]["sources"] == ["https://eater.com/x"] and said["groups"]["praised"][0]["question"] == "best greek in pb", said)
check("ai says: labelled as AI quotes, FAILED rows + other restaurants left out", "AI answers" in said["label"] and len(said["headline"]) == 2
      and not any("Other Place" in q["quote"] for q in said["headline"]))
check("ai says: on the results 'why' tab", "ai_says" in c.get("/api/restaurants/recheck_cafe/results").json()["why"])

# ---- what people say right now -> evidence ledger -> business value (verified only)
FAKE_PAGES["https://slow.example/r"] = "timeout"
FAKE_REVIEWS = [
    {"quote": "Cafe Athena’s lamb gyro is the best thing on Garnet", "rating": "5", "date": "Sep 2026", "source_url": "https://cafeathena.com", "site": "Blog"},
    {"quote": "Great gyros and super friendly staff", "rating": 5, "source_url": "https://blocked.example", "site": "Yelp"},
    {"quote": "Rude staff and totally overpriced, never again", "rating": 1, "source_url": "https://cafeathena.com", "site": "Reddit"},
    {"quote": "Slow service and bland food tonight", "rating": 2, "source_url": "https://slow.example/r", "site": "TripAdvisor"},
    {"quote": "Loved the happy hour", "rating": 5, "source_url": "", "site": "Google"},
    {"quote": " ".join(["word"] * 45), "source_url": "https://cafeathena.com"}]
llm.claude_call = lambda *a, **k: llm.ClaudeResult(text=json.dumps(FAKE_REVIEWS), model="fake", citations=cr.citations)
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
ps = c.post("/api/restaurants/check_diner/people-say/search").json()
st = {x["quote"][:12]: x["evidence"]["status"] for x in ps["saved"]["items"]}
check("people say: page-verified + citation-verified kept, unverified greyed", st == {"Cafe Athena’": "verified", "Great gyros ": "verified",
      "Slow service": "unverified"}, st)
check("people say: rejected counted, no-URL + too-long dropped", ps["saved"]["rejected"] == 1 and ps["saved"]["dropped_no_url"] == 2, ps["saved"])
check("people say: saved to public_reviews.json", (tmp / "live" / "check_diner" / "public_reviews.json").exists())
bv = ps["business_value"]
check("business value: only the 2 verified quotes counted", bv["ready"] and bv["counts"]["verified_quotes"] == 2, bv.get("counts"))
check("business value: rejected + unverified complaints never feed the scores",
      bv["aspects"]["service"]["negative"] == 0 and bv["aspects"]["price_value"]["negative"] == 0 and bv["aspects"]["food"]["negative"] == 0, bv["aspects"])
check("business value: no complaints -> 'Doing well'", bv["aspects"]["service"]["status"] == "Doing well - no complaints found", bv["aspects"]["service"])
check("business value: one plain sentiment sentence", bv["sentiment"].startswith("Mostly positive") and "2 verified web quotes" in bv["sentiment"], bv["sentiment"])
check("people say: sample can't search the web", c.post("/api/restaurants/example/people-say/search").status_code == 400)
c.post("/api/restaurants/check_diner/reviews", json={"restaurant": "Check Diner", "avg_rating": 3, "source": "Google Maps",
                                                      "text": "2 | The price is too much for small portions."})
bv2 = c.get("/api/restaurants/check_diner/people-say").json()["business_value"]
check("business value: owner-pasted reviews added + complaint becomes an action with its quote",
      bv2["counts"]["owner_reviews"] == 1 and bv2["aspects"]["price_value"]["negative"] >= 1 and bv2["actions"][0]["quote"] and "low evidence" in bv2["actions"][0]["evidence"], bv2)
llm.claude_call = real_call
del os.environ["ANTHROPIC_API_KEY"]

# ---- food words: built-in dish words + the restaurant's own dishes / cuisine
from platerank import reviews_vfm as rv
fw = rv.food_words({"cuisine": "Greek", "cuisine_alternates": ["Mediterranean"], "signature_terms": ["Loukoumades with honey"]})
check("food words: from the profile (cuisine, alternates, signature dishes)", {"greek", "mediterranean", "loukoumades with honey", "loukoumades"} <= set(fw), fw)
check("food words: built-in dish words count as food (gyro, souvlaki)", rv.aspect_analysis([{"rating": 5, "text": "The souvlaki was amazing."}])["food"]["mentions"] == 1)
check("food words: the restaurant's own dish counts only when passed in",
      rv.aspect_analysis([{"rating": 5, "text": "Loukoumades were perfect."}])["food"]["mentions"] == 0
      and rv.aspect_analysis([{"rating": 5, "text": "Loukoumades were perfect."}], fw)["food"]["mentions"] == 1)

# ---- housekeeping: what the site says now vs proposed, reminders, PDF, social hygiene
FAKE_PAGES["https://taverna.example"] = FakePage('<html><head><title>Test Taverna | Greek in Harbor Point</title>'
    '<meta name="description" content="Greek food by the harbor."><script type="application/ld+json">{"@context":"https://schema.org",'
    '"@type":"Restaurant","name":"Test Taverna","telephone":"555-0100"}</script></head><body><h1>Test Taverna</h1>'
    '<a href="/menu.pdf">Our Menu</a><h2>About us</h2><p>Family recipes from Crete, served at 12 Ocean Ave.</p>' + FILLER + '</body></html>')
sn = c.post("/api/restaurants/test_taverna/site-now").json()
check("site now: one page read, real text per piece", sn["ok"] and '"telephone": "555-0100"' in sn["pieces"]["pack_restaurant_schema"]["text"]
      and "Family recipes from Crete" in sn["pieces"]["pack_about"]["text"] and "/menu.pdf" in sn["pieces"]["pack_menu_copy"]["text"], sn["pieces"].keys())
check("site now: missing pieces said plainly", sn["pieces"]["pack_faq_schema"] == {"text": "No FAQ schema on the homepage.", "found": False, "evidence": None})
check("site now: page text carries a verified (page fetch) badge + is in the ledger", sn["pieces"]["pack_about"]["evidence"]["tier"] == "page fetch"
      and any(e["subject"].startswith("your site now") for e in evidence.load("test_taverna")))
check("site now: shown in 'Make the changes'", c.get("/api/restaurants/test_taverna/results").json()["make"]["housekeeping"]["site_now"]["ok"])
c.put("/api/restaurants", json={"profile": {"name": "Check Diner", "cuisine": "diner", "area": "Union Square", "website": "https://blocked.example"},
                                "previous_slug": "check_diner"})
snb = c.post("/api/restaurants/check_diner/site-now").json()
check("site now: site can't be read -> said plainly", snb["ok"] is False and "403" in snb["note"] and "Open it yourself" in snb["note"], snb)
c.post("/api/restaurants/test_taverna/remind", json={"key": "pack_about"})
rem = c.get("/api/restaurants/test_taverna/results").json()["make"]["housekeeping"]["reminders"]
check("remind me later: hidden for 24h, saved", rem.get("pack_about", 0) > time.time() + 23.5 * 3600, rem)
c.post("/api/restaurants/test_taverna/remind", json={"key": "pack_about", "undo": True})
check("remind me later: bring back", "pack_about" not in c.get("/api/restaurants/test_taverna/results").json()["make"]["housekeeping"]["reminders"])
check("pdf: not approved -> plain 400", c.get("/api/restaurants/test_taverna/pdf/pack_about").status_code == 400)
c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_about", "text": "Café Athena – “family recipes” since 1990.\n\nSecond paragraph…"})
pdf = c.get("/api/restaurants/test_taverna/pdf/pack_about")
from pypdf import PdfReader
ptxt = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text() if pdf.status_code == 200 else ""
check("pdf: approved text only, accents kept, quotes/dashes made printable", pdf.content[:4] == b"%PDF" and "Café Athena - \"family recipes\" since 1990." in ptxt
      and "Second paragraph..." in ptxt, ptxt[:200])
c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_landing", "text": "<html><body><h1>Greek food</h1><p>Fish &amp; chips</p><script>x()</script></body></html>"})
lt = PdfReader(io.BytesIO(c.get("/api/restaurants/test_taverna/pdf/pack_landing").content)).pages[0].extract_text()
check("pdf: local page printed as text, not HTML", "Fish & chips" in lt and "<p>" not in lt and "x()" not in lt, lt[:200])
c.post("/api/restaurants/test_taverna/approve", json={"key": "pack_menu_copy", "text": "Moussaka - layers"})
check("pdf: menu only if we hold dishes", c.get("/api/restaurants/test_taverna/pdf/pack_menu_copy").status_code == 400)
soc = pipeline.social_hygiene(pipeline.get_profile("test_taverna"), ["late-night", "date-night", "happy-hour"])
check("social: hashtags from the profile + lost question types", {"#HarborPoint", "#GreekFoodSpringfield", "#HPHappyHour", "#GlutenFreeSpringfield",
      "#HPDateNight", "#SpringfieldCatering", "#SpringfieldPrivateEvents"} <= set(soc["hashtags"]), soc["hashtags"])
check("social: no hashtag for something the profile doesn't offer (late-night), no bare nickname", not any("Late" in t for t in soc["hashtags"]) and "#HP" not in soc["hashtags"], soc["hashtags"])
check("social: checklist uses the saved facts", any("12 Ocean Ave" in x for x in soc["checklist"]) and any(HOURS in x for x in soc["checklist"]), soc["checklist"])
check("social: keywords from the profile", "Greek restaurant Harbor Point" in soc["keywords"] and "happy hour HP" in soc["keywords"], soc["keywords"])

# ---- data farming: Reddit agent (fake Claude + fake pages); owner-voiced, verified-only, owner posts
FAKE_PAGES.update({
    "https://www.reddit.com/r/sandiego/": FakePage("<html><title>r/sandiego</title><body>r/sandiego - San Diego's community" + FILLER + "</body></html>"),
    "https://www.reddit.com/r/sandiego/about/rules/": FakePage("<html><body>Rules: 4. Self-promotion is allowed on weekends with the Business flair." + FILLER + "</body></html>"),
    "https://www.reddit.com/r/pacificbeach/": FakePage("<html><body>Welcome to r/pacificbeach" + FILLER + "</body></html>"),
    "https://www.reddit.com/r/pacificbeach/about/rules/": FakePage("blocked", status=403),
    "https://www.reddit.com/r/fakesub/": FakePage("<html><body>This community is about cats." + FILLER + "</body></html>"),
    "https://www.reddit.com/r/sandiego/comments/abc/best_greek/": FakePage("<html><body><h1>Best Greek food near Garnet Ave?</h1>" + FILLER + "</body></html>"),
    "https://www.reddit.com/r/sandiego/comments/zzz/made_up/": FakePage("<html><body><h1>Something else entirely</h1>" + FILLER + "</body></html>"),
})
SUBS = [{"name": "sandiego", "url": "https://www.reddit.com/r/sandiego/", "rules_url": "https://www.reddit.com/r/sandiego/about/rules/",
         "self_promotion": "allowed", "flair_required": True, "rule_quote": "Self-promotion is allowed on weekends with the Business flair."},
        {"name": "pacificbeach", "url": "https://www.reddit.com/r/pacificbeach/", "rules_url": "https://www.reddit.com/r/pacificbeach/about/rules/",
         "self_promotion": "allowed", "rule_quote": "Local businesses may post once a month."},
        {"name": "fakesub", "url": "https://www.reddit.com/r/fakesub/", "self_promotion": "allowed"}]
THREADS = [{"subreddit": "sandiego", "title": "Best Greek food near Garnet Ave?", "url": "https://www.reddit.com/r/sandiego/comments/abc/best_greek/", "date": "2026-10-01"},
           {"subreddit": "sandiego", "title": "Where to get gyros at 3am", "url": "https://www.reddit.com/r/sandiego/comments/zzz/made_up/"},
           {"subreddit": "x", "title": "Not reddit", "url": "https://example.com/forum/1"}]
DRAFTS = {"replies": [{"text": "We do great gyros - call (619) 555-0101."}],
          "posts": [{"title": "Owner of Recheck Cafe here - ask me anything about our happy hour", "text": "Owner of Recheck Cafe here - we're a Greek spot in Harbor Point."}]}
farm_calls = []
def fake_farm_call(prompt, **kw):
    farm_calls.append(prompt[:40])
    body = SUBS if "Reddit communities" in prompt else THREADS if "Reddit threads" in prompt else DRAFTS
    return llm.ClaudeResult(text=json.dumps(body), model="fake")
llm.claude_call = fake_farm_call
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
fv = c.post("/api/restaurants/recheck_cafe/reddit/find").json()
subs = {s["name"]: s for s in fv["subreddits"]}
check("reddit: only verified subreddits kept (fake one dropped)", set(subs) == {"sandiego", "pacificbeach"} and fv["counts"]["subreddits_found"] == 3, fv["counts"])
check("reddit: rule verified -> its permission counts; rule unverified -> 'unknown'", subs["sandiego"]["self_promotion"] == "allowed"
      and subs["pacificbeach"]["self_promotion"] == "unknown" and subs["pacificbeach"]["rule_quote"] is None, subs["pacificbeach"])
check("reddit: only verified threads (made-up title + non-reddit link dropped)", [t["title"] for t in fv["threads"]] == ["Best Greek food near Garnet Ave?"], fv["threads"])
kinds = {d["type"]: d for d in fv["drafts"]}
check("reddit: one reply per thread, a new post only where the verified rule allows", sorted(d["type"] for d in fv["drafts"]) == ["post", "reply"]
      and kinds["post"]["subreddit"] == "sandiego", [(d["type"], d["subreddit"]) for d in fv["drafts"]])
check("reddit: drafts always start as the owner", all(d["text"].startswith("Owner of Recheck Cafe here") for d in fv["drafts"]), [d["text"][:40] for d in fv["drafts"]])
check("reddit: invented facts wrapped for the owner", "[OWNER TO CONFIRM: (619) 555-0101]" in kinds["reply"]["text"], kinds["reply"]["text"])
check("reddit: the post carries the subreddit's rule", kinds["post"]["rule"].startswith("Self-promotion is allowed"))
check("reddit: no 'Open on Reddit' before approval", fv["links"] == {})
bad = c.post("/api/restaurants/recheck_cafe/approve", json={"key": kinds["reply"]["key"], "text": kinds["reply"]["text"]})
check("reddit: can't approve while [OWNER TO CONFIRM] remains", bad.status_code == 400)
c.post("/api/restaurants/recheck_cafe/approve", json={"key": kinds["reply"]["key"], "text": "Owner of Recheck Cafe here - we're a Greek spot in Harbor Point."})
c.post("/api/restaurants/recheck_cafe/approve", json={"key": kinds["post"]["key"], "text": kinds["post"]["text"]})
lk = c.get("/api/restaurants/recheck_cafe/reddit").json()["links"]
check("reddit: approved post -> pre-filled submit link + text to copy",
      lk[kinds["post"]["key"]]["href"].startswith("https://www.reddit.com/r/sandiego/submit?selftext=true&title=Owner%20of%20Recheck%20Cafe")
      and "&text=Owner%20of%20Recheck" in lk[kinds["post"]["key"]]["href"] and lk[kinds["post"]["key"]]["copy"] == kinds["post"]["text"], lk)
check("reddit: approved reply -> copy reply + open the thread", lk[kinds["reply"]["key"]] == {"href": "https://www.reddit.com/r/sandiego/comments/abc/best_greek/",
      "copy": "Owner of Recheck Cafe here - we're a Greek spot in Harbor Point.", "kind": "reply"}, lk)
check("reddit: posted link must be a reddit post", c.post("/api/restaurants/recheck_cafe/reddit/posted", json={"key": kinds["post"]["key"], "url": "https://example.com"}).status_code == 400)
pv = c.post("/api/restaurants/recheck_cafe/reddit/posted", json={"key": kinds["post"]["key"], "url": "https://www.reddit.com/r/sandiego/comments/new1/owner_here/"}).json()
check("reddit: posted saved; flag waits for the next re-check", pv["posted"][kinds["post"]["key"]]["url"].endswith("/owner_here/") and pv["cited"]["status"] == "waiting", pv["cited"])
discovery.ASK["claude"] = lambda q, **kw: ("Try Recheck Cafe", "fake", [{"url": "https://www.reddit.com/r/sandiego/comments/abc/", "title": "t"}], 0.0)
time.sleep(0.01)
pipeline.run("recheck_cafe", platforms=["claude"], reuse=False)
cv = c.get("/api/restaurants/recheck_cafe/reddit").json()["cited"]
check("reddit: next re-check flags reddit.com among the AI's sources", cv["status"] == "cited" and "directional" in cv["note"], cv)
discovery.ASK["claude"] = real_claude_ask
check("reddit: tab note says posts come from the owner", "never fake reviews" in c.get("/api/restaurants/recheck_cafe/reddit").json()["note"])
check("reddit: every subreddit/rule/thread is in the evidence ledger", sum(e["subject"].startswith("r/") or e["subject"] == "subreddit"
      for e in evidence.load("recheck_cafe")) >= 6)
check("reddit: sample can't search", c.post("/api/restaurants/example/reddit/find").status_code == 400)
llm.claude_call = real_call
del os.environ["ANTHROPIC_API_KEY"]

# ---- no money shown on screen (cost tracking stays in the backend + tools/check_live.py)
import re as _re
money = [f"{f.name}: {m.group(0)}" for f in Path("web/src").rglob("*.tsx")
         for m in _re.finditer(r"¢|\bcents?\b|cost \$|\$\{[^}]*(cost|usd)[^}]*\}|at most \(", f.read_text(encoding="utf-8"))]
check("frontend: no cost / price-of-a-call shown in the UI", not money, money)

# ---- frontend build present
dist = Path("web/dist/index.html")
check("frontend: built (web/dist/index.html)", dist.exists(), "run: cd web && npm run build")
if dist.exists():
    import hashlib
    h = hashlib.sha256()
    src = Path("web/src")
    files = sorted(src.rglob("*"), key=lambda p: [part for part in p.relative_to(src).parts])
    for f in [p for p in files if p.is_file()]:
        rel = "src/" + f.relative_to(src).as_posix()
        h.update((rel + "\n" + f.read_text(encoding="utf-8").replace("\r\n", "\n")).encode("utf-8"))
    stamp = Path("web/dist/src-fingerprint.txt")
    check("frontend: build matches the source", stamp.exists() and stamp.read_text().strip() == h.hexdigest(),
          "web/src changed since the last build - run: cd web && npm run build")

shutil.rmtree(tmp.parent, ignore_errors=True)
print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
