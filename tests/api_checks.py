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

from platerank import llm, places, pipeline, store, discovery

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
check("api: drafts ready for approval", [d["key"] for d in res["make"]["drafts"]] == ["faq_page", "schema_markup", "outreach_email"])
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
    '"neighbourhood": "Pacific Beach", "cuisine": "Greek", "found": true, "sources": {"address": "https://cafeathena.com"}}', model="fake")
wl = c.post("/api/web-lookup", json={"name": "Cafe Athena", "city": "San Diego|CA"}).json()
check("web lookup: basics + sources + map point", wl["name"] == "Café Athena" and wl["sources"]["address"] and
      abs(wl["_point"]["lat"] - 32.8002) < 1e-3 and wl["_point"]["precision"].startswith("street"), wl)
llm.claude_call = lambda *a, **k: llm.ClaudeResult(text='{"found": false}', model="fake")
nf = c.post("/api/web-lookup", json={"name": "Nowhere Diner", "city": "San Diego|CA"})
check("web lookup: not confirmed -> plain 400, nothing invented", nf.status_code == 400 and "couldn't confirm" in nf.json()["detail"], nf.json())
check("web lookup: city required", c.post("/api/web-lookup", json={"name": "X Y", "city": "Atlantis|ZZ"}).status_code == 400)
llm.claude_call = real_call
check("llm: state becomes the search region", llm.location_for({"city": "Austin", "state": "TX"})["region"] == "Texas")

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
