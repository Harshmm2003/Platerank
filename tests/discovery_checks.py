"""Offline checks for Phase 3 Discovery: fake platform, no API calls."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from platerank import discovery as d
from platerank.queries import Query

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + (f": {detail}" if detail else "")); ok += cond; fail += not cond

# --- name matching
v = d.name_variants("KazuNori: The Original Hand Roll Bar")
check("short name before ':' is a variant", "KazuNori" in v, v)
check("trailing street number dropped", "Sushi of Gari" in d.name_variants("Sushi of Gari 46"), d.name_variants("Sushi of Gari 46"))
r = d._rank_of("YONO Sushi", "Try KazuNori first, then Yono Sushi, or Sushi of Gari.",
               ["KazuNori: The Original Hand Roll Bar", "Sushi of Gari 46"])
check("case-insensitive + short names, in answer order", r["ordered_mentions"] == ["KazuNori: The Original Hand Roll Bar", "YONO Sushi", "Sushi of Gari 46"] and r["rank"] == 2, r)
r = d._rank_of("YONO Sushi", "Yonomi Sushi is great.", [])
check("no false hit inside another word", not r["mentioned"], r)
r = d._rank_of("YONO Sushi", "Go to YONO near Penn Station.", [], {"YONO Sushi": ["YONO"]})
check("owner alias matched", r["mentioned"], r)

# --- run with a fake platform: busy, quota, cache
qs = [Query(f"q{i}", "generic") for i in range(4)]
calls = []
def fake(q):
    calls.append(q)
    if q == "q1":
        raise RuntimeError("busy")           # one failure -> FAILED row, run continues
    if q == "q2" and len(calls) > 3:
        raise d.QuotaError("429")           # quota -> stop calling for the rest
    return f"YONO Sushi is good ({q})", "fake-model"
d.ASK["fake"] = fake
cache = Path(tempfile.mkdtemp()) / "answers.json"
rows = d.run_discovery(qs, "YONO Sushi", [], "fake", runs=2, cache_path=cache, use_cache=True)
st = [(r["run_id"], r["query"], r["status"]) for r in rows]
check("run keeps going after one failure", [s for *_, s in st].count(d.FAILED) >= 1 and len(rows) == 8, st)
check("quota stops further calls", d.FAILED in [s for (run, q, s) in st if run == 2 and q == "q3"], st)
check("failed rows are never 'mentioned'", all(not r["mentioned"] for r in rows if r["status"] == d.FAILED))
check("live answers cached to disk", cache.exists() and "fake|run1|q0" in cache.read_text())
calls.clear()
rows2 = d.run_discovery(qs, "YONO Sushi", [], "fake", runs=1, cache_path=cache, use_cache=True)
check("re-run reuses cache (no call for saved questions)", "q0" not in calls and rows2[0]["status"] == d.CACHED, (calls, [r["status"] for r in rows2]))
calls.clear()
d.ASK["fake"] = lambda q: (_ for _ in ()).throw(RuntimeError("down"))
rows3 = d.run_discovery(qs[:1], "YONO Sushi", [], "fake", runs=1, cache_path=cache, use_cache=False)
check("fresh run that fails falls back to saved answer, labelled", rows3[0]["status"] == d.CACHED and "saved answer used" in rows3[0]["note"], rows3[0])
demo = d.run_discovery([Query("best healthy lunch near NYU", "healthy")], "Greenwich Kitchen", ["Sweetgreen"], "demo")
check("demo rows labelled DEMO", demo[0]["status"] == d.DEMO, demo[0]["status"])
print(f"\n{ok} passed, {fail} failed")
