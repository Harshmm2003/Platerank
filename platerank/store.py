"""4. MEASUREMENT - save every run so before/after is real, not a slide.
Also the SETUP persistence: one folder per live restaurant under data/live/<slug>/
(profile.json, sources.json, reviews.json, cached answers) - kept apart from
the SAMPLE example dataset in data/.
"""
import json, re, sqlite3, time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
DB = DATA / "runs.db"
LIVE = DATA / "live"
EXAMPLE_PROFILE = DATA / "example_profile.json"

def save_run(target: str, platform: str, summary: dict):
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS runs (ts REAL, target TEXT, platform TEXT, summary TEXT)")
    con.execute("INSERT INTO runs VALUES (?,?,?,?)", (time.time(), target, platform, json.dumps(summary)))
    con.commit(); con.close()

def load_runs(target: str) -> list[dict]:
    if not DB.exists():
        return []
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT ts, platform, summary FROM runs WHERE target=? ORDER BY ts", (target,)).fetchall()
    con.close()
    return [{"ts": ts, "platform": p, **json.loads(s)} for ts, p, s in rows]

def save_answers(target: str, rows: list[dict]) -> float:
    """Log every Discovery row (query, platform, model, run, status, mention, rank, answer)
    under one run timestamp, so any count on screen can be audited against its rows."""
    run_ts = time.time()
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS answers (run_ts REAL, target TEXT, platform TEXT, model TEXT,
                   run_id INTEGER, query TEXT, category TEXT, price_tier TEXT, occasion TEXT, status TEXT,
                   mentioned INTEGER, rank INTEGER, ordered_mentions TEXT, answer TEXT, note TEXT)""")
    con.executemany("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(run_ts, target, r["platform"], r.get("model", ""), r["run_id"], r["query"], r["category"],
                      r["price_tier"], r["occasion"], r["status"], int(r["mentioned"]), r["rank"],
                      json.dumps(r["ordered_mentions"]), r["answer"], r.get("note", "")) for r in rows])
    con.commit(); con.close()
    return run_ts

def answer_runs(target: str) -> dict[float, list[dict]]:
    """Saved answer rows per run timestamp - lets older runs be compared by the questions they asked."""
    if not DB.exists():
        return {}
    con = sqlite3.connect(DB)
    try:
        rows = con.execute("SELECT run_ts, query, category, status, mentioned FROM answers WHERE target=?", (target,)).fetchall()
    except sqlite3.OperationalError:  # no answers table yet
        rows = []
    con.close()
    out: dict[float, list[dict]] = {}
    for ts, q, cat, status, mentioned in rows:
        out.setdefault(ts, []).append({"query": q, "category": cat, "status": status, "mentioned": bool(mentioned)})
    return out

def slugify(name: str) -> str:
    import unicodedata  # 'Café Athena' -> 'cafe_athena'
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "restaurant"

def restaurant_dir(name: str) -> Path:
    return LIVE / slugify(name)

def load_example_profile() -> dict:
    return json.loads(EXAMPLE_PROFILE.read_text(encoding="utf-8"))

def list_profiles() -> list[str]:
    """Names of saved live restaurants."""
    return sorted(json.loads(p.read_text(encoding="utf-8"))["name"] for p in LIVE.glob("*/profile.json"))

def load_profile(name: str) -> dict | None:
    p = restaurant_dir(name) / "profile.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def save_profile(profile: dict) -> Path:
    d = restaurant_dir(profile["name"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.json").write_text(json.dumps(profile, indent=1, ensure_ascii=False), encoding="utf-8")
    return d
