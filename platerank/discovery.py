"""1. DISCOVERY - run queries against AI platforms, log mentions/rank (v3).

Multi-run: AI answers vary run to run, so run_discovery(runs=N) repeats the
bank and every log row carries run_id. Analysis aggregates across runs -
a single run is never presented as truth.
Live mode: Gemini and/or Claude (whichever keys exist). Every live answer is
cached to data/live/<restaurant>/answers.json so re-runs and the demo don't
re-spend calls. Every row carries a status the UI shows as a badge:
  LIVE   - fetched from the platform during this run
  CACHED - a real answer saved from an earlier live run (with its timestamp)
  DEMO   - SAMPLE answer from the example dataset
  FAILED - the platform didn't answer and nothing was saved; Analysis skips these rows
A failed call is never replaced by a made-up answer.
"""
import json, os, re, time
from pathlib import Path
from .queries import Query

SAMPLE = Path(__file__).parent.parent / "data" / "sample_run.json"
SYSTEM = ("You are a helpful local guide. Recommend 3-4 specific restaurants "
          "by name, in ranked order, for the user's request. Be specific.")
LIVE, CACHED, DEMO, FAILED = "LIVE", "CACHED", "DEMO", "FAILED"

# ------------------------------------------------------------------ name matching
def _norm(text: str) -> str:
    return (text.lower().replace("’", "'").replace("‘", "'").replace("&", "and"))

def name_variants(name: str, aliases: list[str] | None = None) -> list[str]:
    """Ways an AI answer may write a restaurant: full name, the part before ':' / '(' / ' - ',
    that part without a trailing street number ('Sushi of Gari 46' -> 'Sushi of Gari'),
    plus owner-given aliases."""
    out = {name, *(aliases or [])}
    short = re.split(r":|\(| - | – | — ", name)[0].strip()
    out |= {short, re.sub(r"\s+\d+\w*$", "", short).strip()}
    return sorted({v for v in out if len(v) >= 3}, key=len, reverse=True)

def _first_pos(answer: str, variants: list[str]) -> int:
    low = _norm(answer)
    hits = [m.start() for v in variants
            for m in [re.search(r"(?<![\w])" + re.escape(_norm(v)) + r"(?![\w])", low)] if m]
    return min(hits) if hits else -1

def _rank_of(target: str, answer: str, competitors: list[str], aliases: dict | None = None) -> dict:
    aliases = aliases or {}
    found = []
    for n in [target] + competitors:
        pos = _first_pos(answer, name_variants(n, aliases.get(n)))
        if pos >= 0:
            found.append((pos, n))
    ordered = [n for _, n in sorted(found)]
    rank = ordered.index(target) + 1 if target in ordered else None
    return {"mentioned": target in ordered, "rank": rank, "ordered_mentions": ordered}

# ------------------------------------------------------------------ platforms
# Models that accept server-side refusal fallbacks (routed by refusal category).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
GEMINI_BACKUP = "gemini-3.5-flash"  # answered reliably when the default was overloaded (Oct 22)

# Read at call time (not import time) so CLAUDE_MODEL / GEMINI_MODEL in .env apply.
def claude_model() -> str:
    return os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

class QuotaError(Exception):
    """The platform refused because the key's quota is used up (HTTP 429)."""

def ask_claude(query: str) -> tuple[str, str]:
    import anthropic
    client = anthropic.Anthropic()
    model = claude_model()
    extra = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if model in FALLBACK_MODELS else {})
    try:
        msg = client.beta.messages.create(model=model, max_tokens=16000,
                                          output_config={"effort": "medium"},
                                          system=SYSTEM, messages=[{"role": "user", "content": query}], **extra)
    except anthropic.RateLimitError as e:
        raise QuotaError(str(e)) from e
    if msg.stop_reason == "refusal":
        return "", msg.model  # logged as "not mentioned"; the raw-answers view shows the empty answer
    return "".join(b.text for b in msg.content if b.type == "text"), msg.model

def _gemini_busy_safe(client, contents, config=None, tries: int = 2):
    """Call Gemini; when it says 'busy' (5xx), wait briefly and retry, then try the
    backup model. Returns (response, model used). A 429 (quota) becomes QuotaError."""
    from google.genai import errors
    models = [gemini_model()] + ([GEMINI_BACKUP] if GEMINI_BACKUP != gemini_model() else [])
    last = None
    for model in models:
        for attempt in range(tries):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config), model
            except errors.ServerError as e:
                last = e
                time.sleep(2 * (attempt + 1))
            except errors.ClientError as e:
                if e.code == 429:
                    raise QuotaError(str(e)) from e
                raise
    raise last

_gemini_client = None

def ask_gemini(query: str) -> tuple[str, str]:
    global _gemini_client
    from google import genai
    from google.genai import types
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    resp, model = _gemini_busy_safe(_gemini_client, query, types.GenerateContentConfig(system_instruction=SYSTEM))
    return resp.text or "", model

ASK = {"claude": ask_claude, "gemini": ask_gemini}

# ------------------------------------------------------------------ competitor suggestions
def _json_from(text: str):
    """Pull the first JSON array/object out of a model reply (tolerates ``` fences)."""
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    end = max(text.rfind("]"), text.rfind("}"))
    if start < 0 or end < start:
        raise ValueError("no JSON in the reply")
    return json.loads(text[start:end + 1])

def _site_responds(url: str) -> bool:
    import requests
    try:
        return requests.get(url, timeout=6, headers={"User-Agent": "PlateRank-Hackathon/1.0"}).status_code < 400
    except Exception:
        return False

def suggest_competitors(profile: dict, n: int = 6) -> dict:
    """SETUP helper: ask Gemini for real same-cuisine restaurants near the target.
    Tries Google Search grounding first; if the key's plan has no search quota
    (free tier), falls back to Gemini WITHOUT search and says so (grounded=False).
    Each suggested website is checked once. Returns {"suggestions", "sources",
    "grounded"}. These are PROPOSALS for the owner to approve/edit - never added silently."""
    from google import genai
    from google.genai import types, errors
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    where = ", ".join(x for x in (profile.get("neighbourhood"), profile.get("area"), profile.get("city")) if x)
    prompt = (f"List up to {n} real, currently open {profile['cuisine']} restaurants in or near "
              f"{where} that compete with {profile['name']} for the same customers. Do not include "
              f"{profile['name']} itself. Only include places you are confident exist. "
              "Reply with ONLY a JSON array of objects with keys: name, website (official site, or empty "
              "string if you are not sure), address, why (one short phrase).")
    try:
        resp = client.models.generate_content(
            model=gemini_model(), contents="Use Google Search. " + prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                # one try only: a no-search plan fails fast instead of being retried for ~30s
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))))
        grounded = True
    except errors.APIError:  # no search quota (429) or search busy (503): answer without search
        resp, _ = _gemini_busy_safe(client, prompt)
        grounded = False
    suggestions = [s for s in _json_from(resp.text or "") if isinstance(s, dict) and s.get("name")]
    from concurrent.futures import ThreadPoolExecutor  # check all sites at once, not one by one
    with ThreadPoolExecutor(8) as pool:
        ok = list(pool.map(lambda s: _site_responds(s["website"]) if s.get("website") else None, suggestions))
    for s, responds in zip(suggestions, ok):
        s["site_responds"] = responds
    sources = []
    meta = resp.candidates[0].grounding_metadata if resp.candidates else None
    for ch in (getattr(meta, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        if web and getattr(web, "uri", None):
            sources.append({"title": web.title, "url": web.uri})
    return {"suggestions": suggestions, "sources": sources, "grounded": grounded}

# ------------------------------------------------------------------ the run
def _load_cache(path: Path | None) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}

def _save_cache(path: Path | None, cache: dict):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")

def run_discovery(queries: list[Query], target: str, competitors: list[str],
                  platform: str = "demo", runs: int = 1, aliases: dict | None = None,
                  cache_path: Path | None = None, use_cache: bool = True, progress=None) -> list[dict]:
    """One row per (run, query). use_cache=True reuses saved live answers (no API call);
    use_cache=False asks the platform fresh and only falls back to a saved answer if the
    call fails. progress(done, total, note) is called after every row."""
    results = []
    sample = cache = {}
    if platform == "demo":
        sample = {s["query"]: s["answer"] for s in json.loads(SAMPLE.read_text(encoding="utf-8"))}
    else:
        cache = _load_cache(cache_path)
    ask = ASK.get(platform)
    total, quota_hit = runs * len(queries), None
    for run_id in range(1, runs + 1):
        for q in queries:
            key = f"{platform}|run{run_id}|{q.text}"
            saved = cache.get(key)
            row = {"query": q.text, "category": q.category, "price_tier": getattr(q, "price_tier", "any"),
                   "occasion": getattr(q, "occasion", "any"), "platform": platform, "run_id": run_id}
            if platform == "demo":
                row.update(status=DEMO, model="sample", answer=sample.get(q.text, ""), note="SAMPLE answer")
            elif saved and use_cache:
                row.update(status=CACHED, model=saved["model"], answer=saved["answer"],
                           note=f"saved live answer from {saved['ts']}")
            elif quota_hit:
                row.update(status=CACHED if saved else FAILED, model=saved["model"] if saved else "",
                           answer=saved["answer"] if saved else "",
                           note=("quota used up - " + ("saved answer used" if saved else "no answer")))
            else:
                try:
                    answer, model = ask(q.text)
                    row.update(status=LIVE, model=model, answer=answer, note="")
                    cache[key] = {"answer": answer, "model": model, "ts": time.strftime("%Y-%m-%d %H:%M")}
                    _save_cache(cache_path, cache)  # saved straight away, so a stopped run keeps its answers
                except Exception as e:
                    reason = "quota used up" if isinstance(e, QuotaError) else f"{type(e).__name__}"
                    if isinstance(e, QuotaError):
                        quota_hit = reason  # stop calling for the rest of this run
                    row.update(status=CACHED if saved else FAILED, model=saved["model"] if saved else "",
                               answer=saved["answer"] if saved else "",
                               note=f"{reason} - " + ("saved answer used" if saved else "no answer"))
            row.update(_rank_of(target, row["answer"], competitors, aliases) if row["status"] != FAILED
                       else {"mentioned": False, "rank": None, "ordered_mentions": []})
            results.append(row)
            if progress:
                progress(len(results), total, f"run {run_id}/{runs} · {row['status']} · {q.text}")
    return results
