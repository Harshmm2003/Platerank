"""The whole pipeline as plain functions, for the web app (api.py) and the checks.

Setup -> Discovery -> Analysis -> 3 Action tracks -> owner approval -> Measurement.
Nothing here is new logic: it calls the existing engines in the same order app.py
(Streamlit) does, and packs the results into one JSON-friendly bundle organised by
the five owner questions. Every number keeps its provenance label (LIVE / CACHED /
DEMO / FAILED, SAMPLE, web-found, owner-entered).
"""
import json, re, time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from . import llm
from .queries import generate_queries, example_queries
from .discovery import run_discovery, FAILED, LIVE, CACHED, DEMO
from .analysis import scorecard, by_category, by_dimension, competitor_frequency, ai_recommended
from .scrape import audit_website, diagnose
from .sources_audit import audit_sources, prioritized_gaps, load_demo_sources, load_sources, save_sources
from .reviews_vfm import (load_demo as load_reviews_demo, load_reviews, analyse_restaurant, area_benchmark,
                          benchmark_label, price_scenario, food_words)
from .creators import (load_demo_creators, load_live_creators, match_creators, content_briefs, outreach_draft, local_places,
                       score_with_unknowns)
from .content_gen import faq_page, outreach_email
from . import content_gen
from .store import answer_runs as store_answer_runs, slugify
from .discovery import _norm as discovery_normalise
from .store import (save_run, save_answers, load_runs, load_profile, load_example_profile, restaurant_dir,
                    DATA)

EXAMPLE_SLUG = "example"
EXAMPLE_DIR = DATA / "example_state"   # runtime state for the SAMPLE example (git-ignored)

QUESTIONS = {
    "rank": "Where do I rank?",
    "why": "Why are competitors beating me?",
    "change": "What should I change?",
    "make": "Can you make the changes?",
    "improve": "Did my visibility improve?",
}


# ------------------------------------------------------------------ profile helpers
def get_profile(slug: str) -> dict | None:
    if slug == EXAMPLE_SLUG:
        return load_example_profile()
    for p in (DATA / "live").glob("*/profile.json"):
        if p.parent.name == slug:
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def set_pinned(slug: str, pinned: bool) -> dict:
    """Pin/unpin a saved restaurant so the Home screen focuses on it. Stored as "pinned" in its profile.json."""
    if slug == EXAMPLE_SLUG:
        raise ValueError("The sample restaurant can't be pinned - pin one of your own restaurants instead.")
    p = get_profile(slug)
    if p is None:
        raise ValueError("That restaurant isn't saved yet.")
    p["pinned"] = bool(pinned)
    _write(DATA / "live" / slug / "profile.json", p)
    return p


def state_dir(slug: str) -> Path:
    return EXAMPLE_DIR if slug == EXAMPLE_SLUG else DATA / "live" / slug


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def names_of(profile: dict) -> list[str]:
    return [c["name"] for c in profile.get("competitors", [])]


def aliases_of(profile: dict) -> dict:
    return ({c["name"]: c.get("aliases", []) for c in profile.get("competitors", [])}
            | {profile["name"]: profile.get("aliases", [])})


def available_platforms() -> list[str]:
    import os
    return (["claude"] if llm.has_key() else []) + (["gemini"] if (os.getenv("GOOGLE_API_KEY") or "").strip() else [])


def cached_platforms(slug: str) -> dict:
    """Platforms with saved real answers for this restaurant -> how many (re-showing them is free)."""
    profile = get_profile(slug)
    if slug == EXAMPLE_SLUG or profile is None:
        return {}
    cache = _read(restaurant_dir(profile["name"]) / "answers.json", {})
    return dict(Counter(k.split("|", 1)[0] for k in cache))


def estimate_calls(slug: str, runs: int, platforms: list[str]) -> dict:
    """How many new calls a run could make, and a rough cost (from tools/check_live.py measurements)."""
    profile = get_profile(slug)
    n = len(example_queries()) if slug == EXAMPLE_SLUG else len(generate_queries(profile))
    per_call = {"claude-haiku-5-5": 0.03, "claude-sonnet-5-5": 0.08, "claude-opus-5-5": 0.15}.get(llm.discovery_model(), 0.15)
    live = [p for p in platforms if p == "claude"]
    return {"questions": n, "runs": runs, "platforms": platforms, "max_calls": n * runs * len(platforms),
            "cached": cached_platforms(slug), "model": llm.discovery_model(),
            "rough_max_cost_usd": round(n * runs * len(live) * per_call, 2)}


# ------------------------------------------------------------------ nearby competitors (map + saved results)
def nearby(slug: str | None, lat: float, lon: float, radius: int, cuisine: str = "", exclude: str = "",
           fresh: bool = False) -> dict:
    """Radius search for competitors. Each successful map answer is saved per restaurant
    (state_dir/nearby_cache.json) and reused, so a slow or busy free map never blocks setup.
    Returns {"results", "cached_at"} - or, when the map fails and nothing is saved,
    {"results": [], "map_unavailable": True} (a calm note on screen, not an error)."""
    from . import places
    path = state_dir(slug) / "nearby_cache.json" if slug and get_profile(slug) else None
    cache = _read(path, {}) if path else {}
    key = f"{round(lat, 5)},{round(lon, 5)}|{int(radius)}|{cuisine.strip().lower()}"
    if key in cache and not fresh:
        return {"results": cache[key]["results"], "cached_at": cache[key]["at"]}
    try:
        res = places.nearby_restaurants(lat, lon, radius, cuisine, exclude)
    except places.PlacesError:
        # fall back to the saved search with the closest radius for this spot + cuisine
        same_spot = [(abs(int(k.split("|")[1]) - radius), v) for k, v in cache.items()
                     if k.split("|")[0] == key.split("|")[0] and k.split("|")[2] == key.split("|")[2]]
        if same_spot:
            v = min(same_spot, key=lambda x: x[0])[1]
            return {"results": v["results"], "cached_at": v["at"], "cached_radius": v["radius"]}
        return {"results": [], "map_unavailable": True}
    if path:
        cache[key] = {"at": time.strftime("%Y-%m-%d %H:%M"), "radius": int(radius), "results": res}
        _write(path, cache)
    return {"results": res, "cached_at": None}


# ------------------------------------------------------------------ Discovery
def run(slug: str, runs: int = 1, reuse: bool = True, platforms: list[str] | None = None,
        web_search: bool = True, progress=None, should_stop=None) -> dict:
    """Runs Discovery for one restaurant and saves the rows. Returns run meta."""
    profile = get_profile(slug)
    if profile is None:
        raise ValueError("Unknown restaurant")
    is_example = slug == EXAMPLE_SLUG
    target, names = profile["name"], names_of(profile)
    if not names:
        raise ValueError("Add at least one competitor first.")
    queries = example_queries() if is_example else generate_queries(profile)
    chosen = ["demo"] if is_example else (platforms or available_platforms() or list(cached_platforms(slug)))
    if not chosen:
        raise ValueError("No AI key in .env - add ANTHROPIC_API_KEY to run a live check, or try the sample.")
    rows = []
    for platform in chosen:
        opts = ({"web_search": web_search, "location": llm.location_for(profile)} if platform == "claude" else None)
        rows += run_discovery(queries, target, names, platform, runs=1 if is_example else runs,
                              aliases=aliases_of(profile),
                              cache_path=None if is_example else restaurant_dir(target) / "answers.json",
                              use_cache=reuse, progress=progress, ask_opts=opts, should_stop=should_stop)
    ok = [r for r in rows if r["status"] != FAILED]
    counts = {s: sum(r["status"] == s for r in rows) for s in (LIVE, CACHED, DEMO, FAILED)}
    meta = {"ts": time.time(), "when": time.strftime("%Y-%m-%d %H:%M"), "platforms": chosen,
            "runs": 1 if is_example else runs, "web_search": web_search and not is_example,
            "counts": counts, "cost_usd": round(sum(r.get("cost_usd", 0) for r in rows), 3),
            "questions": len(queries)}
    _write(state_dir(slug) / "last_run.json", {"meta": meta, "rows": rows})
    if ok and not is_example:
        answers_ts = save_answers(target, rows)
        card = scorecard(ok, target, names)
        me = card[card.restaurant == target].iloc[0]
        # bank fingerprint + platforms + web search: only runs that match on all three are compared
        save_run(target, "+".join(chosen), {"mention_rate": float(me.mention_rate), "mentions": int(me.mentions),
                                           "avg_rank": None if pd.isna(me.avg_rank) else float(me.avg_rank),
                                           "share_of_voice": float(me.share_of_voice), "answers": len(ok),
                                           "runs": runs, **{k.lower(): v for k, v in counts.items()},
                                           "bank_hash": bank_hash(q.text for q in queries), "platforms": chosen,
                                           "web_search": web_search, "answers_run_ts": answers_ts,
                                           "by_category": _cat_rates(ok)})
    return meta


# ------------------------------------------------------------------ Measurement: first vs latest
DIRECTIONAL = "Directional - AI answers vary run to run."


def bank_hash(texts) -> str:
    import hashlib
    return hashlib.sha256("\n".join(sorted(t.strip().lower() for t in texts)).encode("utf-8")).hexdigest()[:16]


def _cat_rates(rows: list[dict]) -> dict:
    cats = {}
    for r in rows:
        if r["status"] != FAILED:
            cats.setdefault(r["category"], []).append(bool(r["mentioned"]))
    return {c: {"rate": round(sum(v) / len(v), 3), "questions": len(v)} for c, v in cats.items()}


def _enrich(run: dict, groups: dict) -> dict:
    """Older runs saved no bank fingerprint - rebuild it from the answer rows saved in the same second."""
    rows = groups.get(run.get("answers_run_ts"))
    if rows is None:
        near = [ts for ts in groups if abs(ts - run["ts"]) < 5]
        rows = groups[min(near, key=lambda ts: abs(ts - run["ts"]))] if near else []
    return {**run, "bank_hash": run.get("bank_hash") or (bank_hash({r["query"] for r in rows}) if rows else None),
            "platforms": sorted(run.get("platforms") or run["platform"].split("+")),
            "by_category": run.get("by_category") or _cat_rates(rows)}


def improvement(slug: str) -> dict:
    """First vs latest check - only runs with the same question bank, platforms and web-search setting."""
    if slug == EXAMPLE_SLUG:
        return {"comparable": False, "reason": "The sample has no history - run your own restaurant twice.", "label": DIRECTIONAL}
    target = get_profile(slug)["name"]
    groups = store_answer_runs(target)
    runs = [_enrich(r, groups) for r in load_runs(target)]
    if len(runs) < 2:
        return {"comparable": False, "checks": len(runs), "label": DIRECTIONAL,
                "reason": "Only one check so far - run a fresh re-check to see before and after." if runs else "No checks yet."}
    latest = runs[-1]
    same = lambda a: (a["bank_hash"] and a["bank_hash"] == latest["bank_hash"] and a["platforms"] == latest["platforms"]
                      and (a.get("web_search") is None or latest.get("web_search") is None or a["web_search"] == latest["web_search"]))
    earlier = [r for r in runs[:-1] if same(r)]
    if not earlier:
        return {"comparable": False, "checks": len(runs), "label": DIRECTIONAL,
                "reason": "No earlier check used the same questions, AI platform and web-search setting as the latest one, "
                          "so they aren't compared."}
    first = earlier[0]
    pick = lambda r: {"when": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), "mention_rate": r["mention_rate"],
                      "avg_rank": r.get("avg_rank"), "share_of_voice": r["share_of_voice"], "answers": r.get("answers")}
    delta = lambda k: None if first.get(k) is None or latest.get(k) is None else round(latest[k] - first[k], 3)
    cats = sorted(set(first["by_category"]) | set(latest["by_category"]))
    return {"comparable": True, "label": DIRECTIONAL, "checks": len(runs), "compared_checks": len(earlier) + 1,
            "skipped": len(runs) - 1 - len(earlier), "platforms": latest["platforms"],
            "first": pick(first), "latest": pick(latest),
            "change": {k: delta(k) for k in ("mention_rate", "avg_rank", "share_of_voice")},
            "by_category": [{"category": c, "first": first["by_category"].get(c, {}).get("rate"),
                             "latest": latest["by_category"].get(c, {}).get("rate"),
                             "questions": latest["by_category"].get(c, first["by_category"].get(c, {})).get("questions")}
                            for c in cats]}


def _mailtos(approvals: dict, restaurant: str) -> dict:
    """'Open in email' links for APPROVED outreach drafts only - the owner picks the recipient and presses send."""
    return {k: content_gen.mailto_link(v["text"], f"Collaboration with {restaurant}")
            for k, v in approvals.items() if k.startswith("outreach")}


# ------------------------------------------------------------------ owner data
def save_approval(slug: str, key: str, text: str) -> dict:
    if key.startswith(("pack_", "reddit_")) and (not text.strip() or content_gen.CONFIRM in text):
        raise ValueError("Fill in or delete every [OWNER TO CONFIRM] part first - this text is approved only when every fact is confirmed.")
    path = state_dir(slug) / "approved.json"
    data = _read(path, {})
    data[key] = {"at": time.strftime("%Y-%m-%d %H:%M"), "text": text}
    _write(path, data)
    return data


def remove_approval(slug: str, key: str) -> dict:
    path = state_dir(slug) / "approved.json"
    data = _read(path, {})
    data.pop(key, None)
    _write(path, data)
    return data


def run_site_audit(slug: str) -> dict:
    """Live audit of the restaurant's site vs the most-mentioned competitor (from the last run).
    The SAMPLE example uses its SAMPLE audit records."""
    profile = get_profile(slug)
    last = _read(state_dir(slug) / "last_run.json", None)
    names = names_of(profile)
    top = names[0] if names else None
    if last:
        ok = [r for r in last["rows"] if r["status"] != FAILED]
        card = scorecard(ok, profile["name"], names)
        rivals = card[card.restaurant != profile["name"]]
        if not rivals.empty:
            top = rivals.iloc[0].restaurant
    if not top:
        raise ValueError("Add competitors first.")
    if slug == EXAMPLE_SLUG:
        src = load_demo_sources()
        out = {profile["name"]: {"audit": src[profile["name"]]["website"], "source": "SAMPLE record"},
               top: {"audit": src.get(top, {}).get("website", {}), "source": "SAMPLE record"}}
    else:
        urls = {c["name"]: c.get("website", "") for c in profile.get("competitors", [])}
        out = {}
        for n, u in ((profile["name"], profile.get("website", "")), (top, urls.get(top, ""))):
            if not u:
                out[n] = {"audit": {}, "source": "no website on file"}
                continue
            a = audit_website(u)
            out[n] = ({"audit": {}, "source": f"couldn't fetch {u} ({a['error'][:80]})"} if "error" in a
                      else {"audit": a, "source": f"LIVE fetch of {u} at {time.strftime('%H:%M')}"})
    _write(state_dir(slug) / "site_audit.json", out)
    return out


def save_reviews_text(slug: str, restaurant: str, avg_rating: float, review_count: int | None,
                      source: str, text: str) -> dict:
    """Owner-pasted REAL reviews, one per line as 'rating | text'."""
    if slug == EXAMPLE_SLUG:
        raise ValueError("The sample restaurant's reviews are fixed SAMPLE data.")
    if not source.strip():
        raise ValueError("Say where the reviews were copied from (e.g. Google Maps).")
    parsed, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        left, sep, body = line.partition("|")
        try:
            rating = int(float(left.strip()))
            assert sep and 1 <= rating <= 5 and body.strip()
            parsed.append({"rating": rating, "text": body.strip()})
        except Exception:
            bad += 1
    if not parsed:
        raise ValueError("No reviews read. Use one review per line:  5 | Great fish, fair price.")
    profile = get_profile(slug)
    path = restaurant_dir(profile["name"]) / "reviews.json"
    data = load_reviews(path) or {"restaurants": {}}
    listing = load_sources(restaurant_dir(profile["name"]) / "sources.json").get(restaurant, {})
    data["restaurants"][restaurant] = {"avg_rating": float(avg_rating), "review_count": int(review_count or len(parsed)),
                                       "price_level": listing.get("listings", {}).get("google", {}).get("price_level"),
                                       "reviews": parsed, "source": source.strip()}
    _write(path, data)
    return {"saved": len(parsed), "skipped_lines": bad}


def save_listing(slug: str, restaurant: str, google: dict, source: str):
    """Rating / review count / price level for one restaurant (owner-checked), into sources.json."""
    profile = get_profile(slug)
    path = restaurant_dir(profile["name"]) / "sources.json"
    data = load_sources(path)
    entry = data.setdefault(restaurant, {"listings": {}, "mentions": {}})
    entry.setdefault("listings", {})["google"] = {k: v for k, v in google.items() if v is not None}
    entry["source"] = source
    save_sources(path, data)
    return entry


# ------------------------------------------------------------------ the results bundle
def _domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


# ------------------------------------------------------------------ website content pack (Action A)
PACK_TITLES = {"pack_restaurant_schema": "Your business details, in the format AI reads", "pack_faq_schema": "Your FAQ, in the format AI reads",
               "pack_menu_schema": "Your menu, in the format AI reads", "pack_about": "About us",
               "pack_menu_copy": "Menu descriptions", "pack_landing": "Local page for your website"}


def _pack_facts(slug: str, profile: dict, site_audit: dict | None = None, reviews: dict | None = None) -> dict:
    if site_audit is None:
        site_audit = _read(state_dir(slug) / "site_audit.json", {}).get(profile["name"], {}).get("audit")
    if reviews is None and slug != EXAMPLE_SLUG:
        reviews = (load_reviews(restaurant_dir(profile["name"]) / "reviews.json") or {}).get("restaurants", {}).get(profile["name"])
    return content_gen.pack_facts(profile, site_audit, reviews)


def generate_content_pack(slug: str, regenerate: bool = False) -> dict:
    """Claude writes the wording (about / menu copy / landing page) from the fact sheet only, once.
    The result is cached in content_pack.json; reloading never regenerates. regenerate=True asks Claude again."""
    if slug == EXAMPLE_SLUG:
        raise ValueError("The content pack is for your own restaurant - the sample has no real facts to write from.")
    profile = get_profile(slug)
    path = state_dir(slug) / "content_pack.json"
    cached = _read(path, None)
    if cached and not regenerate:
        return cached
    facts = _pack_facts(slug, profile)
    r = llm.claude_call(content_gen.pack_prompt(facts), system=content_gen.PACK_SYSTEM, max_tokens=8000)
    if r.refused:
        raise ValueError("Claude declined to write this text. Try Regenerate later, or write it by hand.")
    try:
        data = llm.json_from(r.text)
        landing = data.get("landing") or {}
    except (ValueError, AttributeError):
        raise ValueError("Claude's reply wasn't in the expected format. Click Regenerate to try again.")
    flags = {}

    def guard(key, text):
        t, f = content_gen.guard_facts(str(text or ""), facts)
        flags.setdefault(key, []).extend(f)
        return t

    held = {m["name"].lower() for m in content_gen.menu_items(profile)}
    pack = {"facts_hash": content_gen.facts_hash(facts), "at": time.strftime("%Y-%m-%d %H:%M"), "model": r.model,
            "cost_usd": round(r.cost_usd, 4),  # tracked, never shown on screen
            "about": guard("pack_about", data.get("about")),
            "menu_descriptions": [{"name": m["name"], "description": guard("pack_menu_copy", m.get("description"))}
                                  for m in data.get("menu_descriptions") or [] if str(m.get("name", "")).lower() in held],
            "landing": {"intro": guard("pack_landing", landing.get("intro")),
                        "meta_description": guard("pack_landing", landing.get("meta_description"))[:160],
                        "facts": [guard("pack_landing", x) for x in landing.get("facts") or []],
                        "qa": [{"q": guard("pack_landing", x.get("q")), "a": guard("pack_landing", x.get("a"))}
                               for x in landing.get("qa") or [] if isinstance(x, dict)]},
            "flags": flags}
    _write(path, pack)
    return pack


def content_pack_view(slug: str, profile: dict, site_audit: dict | None, reviews: dict | None, faq_text: str) -> dict:
    """Six draft cards. The three schemas are built by code every time; the wording comes from the cache."""
    is_example = slug == EXAMPLE_SLUG
    cached = None if is_example else _read(state_dir(slug) / "content_pack.json", None)
    facts = _pack_facts(slug, profile, site_audit, reviews)
    faq_ld, left_out = content_gen.faq_jsonld(faq_text)
    menu_ld = content_gen.menu_jsonld(profile)
    dumps = lambda d: json.dumps(d, indent=2, ensure_ascii=False)
    need_text = "Click “Write the text” above - Claude writes this from your facts only."
    pieces = [
        {"key": "pack_restaurant_schema", "kind": "json", "text": dumps(content_gen.restaurant_jsonld(profile)),
         "note": "Built from your saved facts - no AI. Fill in or delete any [OWNER TO CONFIRM] line before approving."},
        {"key": "pack_faq_schema", "kind": "json", "text": dumps(faq_ld) if faq_ld else "",
         "note": ("Only FAQ answers we actually know are included." +
                  (f" Left out until you confirm them: {'; '.join(left_out)}" if left_out else "")) if faq_ld
                 else "No FAQ answers are known yet - fill in the FAQ draft above first."},
        {"key": "pack_menu_schema", "kind": "json", "text": dumps(menu_ld) if menu_ld else "",
         "note": "From the dishes and prices you saved." if menu_ld else
                 "No dishes with prices saved yet - add them in Setup (Owner details). Nothing is made up."},
        {"key": "pack_about", "kind": "text", "text": (cached or {}).get("about", ""),
         "note": "" if cached else need_text},
        {"key": "pack_menu_copy", "kind": "text",
         "text": "\n\n".join(f"{m['name']} - {m['description']}" for m in (cached or {}).get("menu_descriptions", [])),
         "note": ("No dishes saved yet, so there's nothing to describe - add them in Setup. Nothing is made up."
                  if not content_gen.menu_items(profile) else ("" if cached else need_text))},
        {"key": "pack_landing", "kind": "code",
         "text": content_gen.landing_html(profile, cached["landing"], faq_ld) if cached else "",
         "note": "" if cached else need_text},
    ]
    for pc in pieces:
        pc["title"] = PACK_TITLES[pc["key"]]
        pc["flags"] = (cached or {}).get("flags", {}).get(pc["key"], [])
    return {"pieces": pieces, "is_sample": is_example,
            "generated": {"at": cached["at"], "model": cached["model"]} if cached else None,
            "facts_changed": bool(cached) and cached.get("facts_hash") != content_gen.facts_hash(facts),
            "can_generate": not is_example and llm.has_key()}


def website_pack(slug: str) -> bytes:
    profile = get_profile(slug)
    return content_gen.website_pack_zip(profile["name"], _read(state_dir(slug) / "approved.json", {}))


def _faq_facts(profile: dict, site_audit: dict | None, weak_aspects: list[str]) -> dict:
    menu, a = profile.get("menu", {}), site_audit or {}
    return {"dietary_tags": a.get("dietary_tags_found"), "hero_dish": menu.get("hero_dish_name"),
            "hero_price": menu.get("hero_dish_price"), "anchor_item": profile.get("anchor_item"),
            "anchor_price": menu.get("anchor_price"), "weak_aspects": weak_aspects,
            "address": profile.get("address"), "hours": profile.get("hours"), "highlights": profile.get("highlights")}


# ------------------------------------------------------------------ overview: one headline per tab + the ranked to-do list
def _p(x) -> str:
    return "-" if x is None else f"{round(x * 100)}%"


def _first_line(s: str, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def overview(slug: str, out: dict) -> dict:
    """Adds out["headlines"] (one plain sentence per tab) and out["todo"] (max 10 actions from every tab).
    Ranking is deterministic: gap priority first, then business value, then website drafts, creators, Reddit."""
    profile = get_profile(slug)
    name = profile["name"]
    approvals = out.get("approvals", {})
    pack = (out.get("make") or {}).get("pack") or {}
    hk = (out.get("make") or {}).get("housekeeping") or {}
    bv = business_value(slug) if slug != EXAMPLE_SLUG else {"ready": False, "reason": "The sample has no web reviews."}
    cv = creators_view(slug) if slug != EXAMPLE_SLUG else {"creators": []}
    fv = farm_view(slug) if slug != EXAMPLE_SLUG else {}
    tabs = {"rank": "", "housekeeping": "", "social": "", "business": "", "farm": "", "todo": "", "improve": ""}

    # 1 where you rank
    if out.get("rank"):
        rk = out["rank"]
        rivals = [s for s in rk.get("scorecard", []) if s.get("restaurant") != name]
        top = max(rivals, key=lambda s: s.get("mention_rate", 0)) if rivals else None
        tabs["rank"] = f"AI names {name} in {_p(rk['mention_rate'])} of answers" + \
                       (f"; {top['restaurant']} is named in {_p(top['mention_rate'])}." if top else ".")
    else:
        tabs["rank"] = f"{name} hasn't been checked yet - run the first check to see how often AI recommends it."
    # 2 housekeeping
    pieces = [p_ for p_ in pack.get("pieces", []) if p_.get("text")]
    n_ok = sum(1 for p_ in pieces if p_["key"] in approvals)
    now = hk.get("site_now") or {}
    if now.get("ok"):
        miss = [k for k in ("pack_restaurant_schema", "pack_faq_schema", "pack_menu_schema", "faq_page") if not now["pieces"].get(k, {}).get("found")]
        tabs["housekeeping"] = f"Your website is missing {len(miss)} of 4 things AI assistants read; {n_ok} of {len(pieces)} ready-made fixes approved."
    else:
        tabs["housekeeping"] = f"{n_ok} of {len(pieces)} ready-made website fixes approved - read your current website to compare."
    # 3 social media
    ver = [c for c in cv.get("creators", []) if c.get("verified")]
    tabs["social"] = (f"{len(ver)} verified local food creators found; {sum(c['saved'] for c in ver)} saved to contact." if cv.get("creators")
                      else "No creators searched yet - find local food creators who cover your cuisine.")
    # 4 business value
    tabs["business"] = bv.get("sentiment") if bv.get("ready") else bv.get("reason", "")
    # 5 data farming
    if fv.get("at"):
        tabs["farm"] = (f"{len(fv.get('threads', []))} live Reddit conversations and {len(fv.get('subreddits', []))} subreddits verified; "
                        f"{len(fv.get('drafts', []))} replies ready for you to post.")
    else:
        tabs["farm"] = "Not searched yet - find where locals ask where to eat on Reddit."
    # 7 did it improve
    cmp = (out.get("improve") or {}).get("compare") or {}
    tabs["improve"] = (f"AI named you in {_p(cmp['first']['mention_rate'])} of answers at the first check and {_p(cmp['latest']['mention_rate'])} "
                       f"now - directional, answers vary run to run." if cmp.get("comparable") else
                       cmp.get("reason") or "Run a second check later to see before and after.")

    # 6 the to-do list
    items = []
    for g in sorted((out.get("why") or {}).get("gaps", []), key=lambda g: -(g.get("priority") or 0)):
        items.append({"id": "gap:" + slugify(g["gap"])[:60], "title": g["gap"], "why": _first_line(g.get("evidence")), "link": None,
                      "tab": {"standard": "housekeeping", "creator": "social", "vfm": "business"}.get(g.get("action"), "housekeeping"),
                      "rank": (0, -(g.get("priority") or 0))})
    for s in (out.get("why") or {}).get("site_gaps", []):
        if not s.startswith("No structural gaps"):
            items.append({"id": "site:" + slugify(s)[:60], "title": s, "why": "Found when we compared your website with the top competitor's.",
                          "link": profile.get("website"), "tab": "housekeeping", "rank": (1, 0)})
    for i, a in enumerate(bv.get("actions") or []):
        items.append({"id": "bv:" + a["category"], "title": f"{a['category'].replace('_', ' / ').capitalize()}: {a['action']}",
                      "why": _first_line(a["evidence"] + (f' - “{a["quote"]}”' if a.get("quote") else "")), "link": a.get("source_url"),
                      "tab": "business", "rank": (2, i)})
    for i, p_ in enumerate([p_ for p_ in pieces if p_["key"] not in approvals][:3]):
        found = (now.get("pieces") or {}).get(p_["key"], {}).get("found") if now.get("ok") else None
        items.append({"id": "hk:" + p_["key"], "title": f"Approve: {p_['title']}",
                      "why": "Your website doesn't have this today." if found is False else "Ready-made from your facts - check and approve.",
                      "link": now.get("url") or profile.get("website"), "tab": "housekeeping", "rank": (3, i)})
    for i, c in enumerate([c for c in ver if c["outreach_key"] not in approvals][:2]):
        items.append({"id": "cr:" + c["handle"], "title": f"Contact {c['name']} ({c['platform']})", "why": _first_line(f"Video idea: {c['brief']['concept_title']}"),
                      "link": c["url"], "tab": "social", "rank": (4, i)})
    posted = fv.get("posted") or {}
    for i, d in enumerate(fv.get("drafts") or []):
        if d["key"] in posted:
            continue
        ready = d["key"] in approvals
        items.append({"id": "rd:" + d["key"], "title": (f"Post your {'reply' if d['type'] == 'reply' else 'post'} in r/{d['subreddit']}" if ready
                                                     else f"Review your {'reply' if d['type'] == 'reply' else 'post'} for r/{d['subreddit']}"),
                      "why": _first_line(d.get("thread_title") or d.get("rule") or "Owner-voiced draft from your facts."),
                      "link": d.get("thread_url") or f"https://www.reddit.com/r/{d['subreddit']}/", "tab": "farm", "rank": (5 if not ready else 4.5, i)})
    done = _read(state_dir(slug) / "todo_done.json", {})
    items = sorted(items, key=lambda x: x["rank"])[:10]
    for x in items:
        x["done"] = bool(done.get(x["id"]))
        x.pop("rank")
    open_n = sum(not x["done"] for x in items)
    tabs["todo"] = f"{open_n} thing{'s' if open_n != 1 else ''} to do, most important first." if items else "Nothing to do yet - run a check or open the other tabs."
    out["headlines"], out["todo"] = tabs, items
    return out


def set_todo_done(slug: str, item_id: str, done: bool) -> dict:
    path = state_dir(slug) / "todo_done.json"
    data = _read(path, {})
    data[item_id] = bool(done)
    _write(path, data)
    return data


def make_before_run(slug: str) -> dict | None:
    """'Make the changes' works before the first check: FAQ, outreach email and the content pack only
    need the saved facts. The other four tabs need a check (the UI says so)."""
    profile = get_profile(slug)
    if profile is None:
        return None
    t_site = _read(state_dir(slug) / "site_audit.json", {}).get(profile["name"], {}).get("audit") or {}
    faq_text = faq_page(profile["name"], profile["area"], _faq_facts(profile, t_site, []))
    return overview(slug, {"restaurant": profile["name"], "slug": slug, "is_sample": slug == EXAMPLE_SLUG, "no_run": True,
            "questions": QUESTIONS, "approvals": _read(state_dir(slug) / "approved.json", {}),
            "mailto": _mailtos(_read(state_dir(slug) / "approved.json", {}), profile["name"]),
            "make": {"drafts": [{"key": "faq_page", "title": "FAQ page", "kind": "text", "text": faq_text},
                                {"key": "outreach_email", "title": "Pitch to local food writers", "kind": "text",
                                 "text": outreach_email(profile)}],
                     "creators": [], "creators_note": "Run a check first - creator matches use the question types you're losing.",
                     "pack": content_pack_view(slug, profile, t_site, None, faq_text),
                     "housekeeping": _housekeeping(slug, profile, [])}})


# ------------------------------------------------------------------ qualitative: what AI says / what people say
PRAISE = ["known for", "great", "excellent", "delicious", "best", "favorite", "favourite", "popular", "loved", "love", "fresh",
          "authentic", "friendly", "cozy", "cosy", "generous", "worth", "highly rated", "standout", "recommend", "beloved", "solid"]
CRITIC = ["but ", "however", "pricey", "expensive", "overpriced", "slow", "crowded", "noisy", "loud", "small portion", "mixed",
          "inconsistent", "complain", "wait", "rude", "bland", "disappointing", "dated"]


def _sentences(text: str) -> list[str]:
    clean = re.sub(r"[*_#`>]+", "", text or "")
    return [s.strip(" -•\t") for s in re.split(r"(?<=[.!?])\s+|\n+", clean) if len(s.strip()) > 12]


def ai_says(profile: dict, rows: list[dict]) -> dict:
    """Sentences from the saved AI answers that name the restaurant - quotes of AI answers, not facts.
    No new AI calls."""
    names = [n.lower() for n in [profile["name"]] + (profile.get("aliases") or []) if n]
    norm = lambda s: discovery_normalise(s)
    names_n = [norm(n) for n in names]
    groups, seen = {"praised": [], "criticised": [], "described": []}, set()
    for r in rows:
        if r.get("status") == FAILED or not r.get("mentioned"):
            continue
        for s in _sentences(r.get("answer", "")):
            ns = norm(s)
            if not any(n in ns for n in names_n) or ns in seen:
                continue
            seen.add(ns)
            low = s.lower()
            kind = "criticised" if any(w in low for w in CRITIC) else "praised" if any(w in low for w in PRAISE) else "described"
            groups[kind].append({"quote": s[:400], "question": r["query"], "platform": r.get("platform"),
                                 "sources": [x["url"] for x in (r.get("sources") or [])][:3]})
    head = (groups["praised"][:3] + groups["criticised"][:2] + groups["described"])[:5]
    return {"label": "Quotes of AI answers (what the assistants said), not verified facts.",
            "counts": {k: len(v) for k, v in groups.items()}, "groups": groups, "headline": head}


REVIEWS_PROMPT = (
    "Search the web for what customers say right now about the restaurant '{name}' at {where}: review and forum pages "
    "(Yelp, TripAdvisor, Reddit, local blogs, Google review snippets). Reply with ONLY a JSON array (at most 20 items) of "
    "objects: quote (SHORT verbatim words copied exactly from the page, max 25 words - never paraphrase), rating (stars as "
    "shown, or null), date (as shown, or null), source_url (the exact page the quote is on), site. Skip anything you can't "
    "quote word for word. Never invent or summarise.")


def public_reviews(slug: str) -> dict | None:
    return _read(state_dir(slug) / "public_reviews.json", None)


def find_public_reviews(slug: str) -> dict:
    """One Claude + web search call. Every quote goes through the evidence ledger; quotes without a URL
    (or too long to be verbatim) are dropped. Saved to public_reviews.json."""
    from . import evidence
    if slug == EXAMPLE_SLUG:
        raise ValueError("This searches the web for your own restaurant - the sample is fictional.")
    profile = get_profile(slug)
    where = profile.get("address") or ", ".join(x for x in (profile.get("area"), profile.get("city")) if x)
    r = llm.claude_call(REVIEWS_PROMPT.format(name=profile["name"], where=where),
                        tools=[llm.web_search_tool(max_uses=5, location=llm.location_for(profile))], max_tokens=6000)
    try:
        raw = llm.json_from(r.text or "[]")
    except ValueError:
        raw = []
    raw = [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    usable = [x for x in raw if str(x.get("source_url", "")).startswith("http") and x.get("quote")
              and len(str(x["quote"]).split()) <= 40][:20]
    recs = evidence.record_and_verify(slug, [{"kind": "quote", "text": str(x["quote"]).strip().strip('"“”'),
                                              "source_url": x["source_url"], "subject": f"review ({x.get('site') or 'web'})"}
                                             for x in usable], citations=r.citations)
    items = [{"quote": rec["text"], "rating": x.get("rating"), "date": x.get("date"), "site": x.get("site"),
              "source_url": x["source_url"], "evidence": evidence.badge(rec)}
             for x, rec in zip(usable, recs) if rec["status"] != evidence.REJECTED]
    data = {"at": time.strftime("%Y-%m-%d %H:%M"), "model": r.model, "cost_usd": round(r.cost_usd, 4), "items": items,
            "rejected": sum(rec["status"] == evidence.REJECTED for rec in recs), "dropped_no_url": len(raw) - len(usable)}
    _write(state_dir(slug) / "public_reviews.json", data)
    return data


def _rating(x) -> int | None:
    try:
        v = float(str(x).split("/")[0].split()[0])
        return int(round(v)) if 0 < v <= 5 else None
    except (ValueError, IndexError, TypeError):
        return None


def business_value(slug: str) -> dict:
    """VERIFIED public quotes + owner-pasted reviews -> reviews_vfm (unchanged): aspects, top 3 actions with a
    linked quote each, and one plain sentence of overall sentiment. Unverified/rejected quotes never count."""
    profile = get_profile(slug)
    pub = public_reviews(slug) or {}
    verified = [x for x in pub.get("items", []) if (x.get("evidence") or {}).get("status") == "verified"]
    owner = (load_reviews(restaurant_dir(profile["name"]) / "reviews.json") or {}).get("restaurants", {}).get(profile["name"]) \
        if slug != EXAMPLE_SLUG else None
    texts = [{"rating": _rating(x.get("rating")) or 3, "text": x["quote"], "url": x["source_url"]} for x in verified]
    texts += [{"rating": int(r.get("rating") or 3), "text": r["text"], "url": None, "owner": True} for r in (owner or {}).get("reviews", [])]
    if not texts:
        return {"ready": False, "reason": "No verified reviews yet - click “Find what people say” or paste reviews in Setup."}
    seen_r = [_rating(x.get("rating")) for x in verified if _rating(x.get("rating"))]
    avg = (owner or {}).get("avg_rating") or (round(sum(seen_r) / len(seen_r), 2) if seen_r else 0)
    a = analyse_restaurant(profile["name"], {"avg_rating": avg, "review_count": len(texts), "price_level": profile.get("price_level"),
                                             "reviews": [{"rating": t["rating"], "text": t["text"]} for t in texts]},
                           profile.get("menu", {}), {"entree_avg": None, "entree_n": 0}, 0.0, None, profile.get("anchor_item") or "everyday item",
                           food_words(profile))
    link = lambda q: next((t["url"] for t in texts if q and (q[:60].lower() in t["text"].lower() or t["text"][:60].lower() in q.lower())), None)
    actions = [{"category": rec["area"], "action": rec["recommendation"], "evidence": rec["evidence"],
                "quote": rec.get("example_quote"), "source_url": link(rec.get("example_quote"))}
               for rec in a["recommendations"]][:3]
    # the engine only recommends with enough evidence; below that, list each complained-about aspect as low evidence
    for k, v in sorted(a["aspects"].items(), key=lambda kv: -kv[1]["negative"]):
        if len(actions) >= 3 or not v["negative"] or any(x["category"] == k for x in actions):
            continue
        q = (v.get("neg_quotes") or [None])[0]
        actions.append({"category": k, "action": f"Look into {k.replace('_', ' / ')}",
                        "evidence": f"{v['negative']} complaint(s) in {len(texts)} reviews" + (" - low evidence, watch for more" if v["negative"] < 3 else ""),
                        "quote": q, "source_url": link(q)})
    aspects = {k: {"positive": v["positive"], "negative": v["negative"], "mentions": v["mentions"],
                   "status": "Doing well - no complaints found" if v["mentions"] and not v["negative"] else
                             ("No mentions yet" if not v["mentions"] else f"{v['negative']} complaint(s)")}
               for k, v in a["aspects"].items()}
    pos = sum(v["positive"] for v in a["aspects"].values()); neg = sum(v["negative"] for v in a["aspects"].values())
    loved = [k.replace("_", " / ") for k, v in sorted(a["aspects"].items(), key=lambda kv: -kv[1]["positive"]) if v["positive"] > v["negative"]][:2]
    hit = [(k.replace("_", " / "), v["negative"]) for k, v in sorted(a["aspects"].items(), key=lambda kv: -kv[1]["negative"]) if v["negative"]][:2]
    tone = "No clear sentiment yet" if not pos + neg else ("Mostly positive" if pos / (pos + neg) >= 0.65 else
                                                            "Mixed" if pos / (pos + neg) >= 0.4 else "Mostly negative")
    sentence = tone + (": loved for " + " and ".join(loved) if loved else "") + \
               ("; " + "; ".join(f"{k} criticised {n} time{'s' if n > 1 else ''}" for k, n in hit) if hit else "") + \
               f" (from {len(verified)} verified web quote{'s' if len(verified) != 1 else ''}" + \
               (f" + {len(owner['reviews'])} pasted review{'s' if len(owner['reviews']) != 1 else ''})" if owner and owner.get("reviews") else ")") + "."
    return {"ready": True, "sentiment": sentence, "actions": actions, "aspects": aspects,
            "counts": {"verified_quotes": len(verified), "owner_reviews": len((owner or {}).get("reviews", []))}}


def people_say(slug: str) -> dict:
    pub = public_reviews(slug)
    return {"saved": pub, "business_value": business_value(slug), "can_search": slug != EXAMPLE_SLUG and llm.has_key()}


# ------------------------------------------------------------------ housekeeping: site now vs proposed, reminders, PDF, social
_LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)


def _ld_blocks(raw_html: str) -> list[dict]:
    out = []
    for m in _LD_RE.finditer(raw_html or ""):
        try:
            d = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            if isinstance(x, dict):
                out.append(x)
    return out


def _around(text: str, word: str, n: int = 500) -> str | None:
    i = text.lower().find(word)
    if i < 0:
        return None
    start = text.rfind(". ", 0, max(0, i - 1))  # start at a sentence (never mid-word)
    return text[start + 2 if start >= 0 and i - start < 200 else i: i + n].strip()


def read_site_now(slug: str) -> dict:
    """ONE fetch of the restaurant's own homepage: what each website piece looks like today (real text, with URL)."""
    from . import evidence
    profile = get_profile(slug)
    url = profile.get("website") or ""
    now = {"at": time.strftime("%Y-%m-%d %H:%M"), "url": url, "ok": False, "pieces": {}}
    if not url:
        now["note"] = "No website saved for this restaurant - add it in Setup to compare."
        _write(state_dir(slug) / "site_now.json", now)
        return now
    page, why = evidence.fetch_page(url)
    if page is None:
        now["note"] = f"Couldn't read {url}: {why}. Open it yourself to compare."
        _write(state_dir(slug) / "site_now.json", now)
        return now
    lds, text = _ld_blocks(page["html"]), page["text"]
    typed = lambda *ts: next((d for d in lds if str(d.get("@type")) in ts), None)
    dumps = lambda d: json.dumps(d, indent=2, ensure_ascii=False)[:1500]
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', page["html"], re.I)
    menu_a = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*menu[^<]*)</a>', page["html"], re.I)
    rest, faq, menu = typed("Restaurant", "FoodEstablishment"), typed("FAQPage"), typed("Menu")
    faq_text = dumps(faq) if faq else _around(text, "faq") or _around(text, "frequently asked")
    found = {
        "pack_restaurant_schema": dumps(rest) if rest else None,
        "pack_faq_schema": dumps(faq) if faq else None,
        "faq_page": faq_text,
        "pack_menu_schema": dumps(menu) if menu else None,
        "pack_menu_copy": f"Menu link on the homepage: “{menu_a.group(2).strip()}” → {menu_a.group(1)}" if menu_a else None,
        "pack_about": _around(text, "about us") or _around(text, "our story") or text[:600] or None,
        "pack_landing": f"Page title: {page['title'] or '(none)'}\nDescription: {desc.group(1) if desc else '(none)'}\n"
                        f"{len(text.split())} words of readable text on the homepage.",
    }
    missing = {"pack_restaurant_schema": "Your homepage doesn't give AI your business details in its format.", "pack_faq_schema": "Your homepage has no FAQ in the format AI reads.",
               "faq_page": "No FAQ on the homepage.", "pack_menu_schema": "Your homepage has no menu in the format AI reads.",
               "pack_menu_copy": "No menu link found on the homepage.", "pack_about": "No readable text on the homepage."}
    recs = evidence.record_direct(slug, [{"kind": "quote", "text": v[:300], "source_url": url, "page_title": page["title"],
                                          "subject": f"your site now: {PACK_TITLES.get(k, 'FAQ page')}"} for k, v in found.items() if v])
    by_key = dict(zip([k for k, v in found.items() if v], recs))
    now.update(ok=True, title=page["title"], pieces={
        k: {"text": v or missing[k], "found": bool(v), "evidence": evidence.badge(by_key[k]) if k in by_key else None}
        for k, v in found.items()})
    _write(state_dir(slug) / "site_now.json", now)
    return now


def remind_later(slug: str, key: str, hours: float = 24, undo: bool = False) -> dict:
    path = state_dir(slug) / "reminders.json"
    data = _read(path, {})
    if undo:
        data.pop(key, None)
    else:
        data[key] = time.time() + hours * 3600
    _write(path, data)
    return data


PDF_PIECES = {"faq_page": "FAQ", "pack_about": "About us", "pack_landing": "Local page", "pack_menu_copy": "Menu"}


def _pdf_text(s: str) -> str:
    """Core PDF fonts are Latin-1: straighten quotes/dashes, keep accents (é), replace the rest."""
    for a, b in {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
                 "→": "->", "•": "-", " ": " "}.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _html_lines(html_text: str) -> str:
    import html as _h
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.S | re.I)
    t = re.sub(r"</(h1|h2|h3|p|li|title)>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "- ", t, flags=re.I)
    t = _h.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def piece_pdf(slug: str, key: str) -> bytes:
    """PDF of ONE approved piece (the approved text, never the unapproved draft)."""
    from fpdf import FPDF
    if key not in PDF_PIECES:
        raise ValueError("PDF download is for the FAQ, About us, local page and menu text.")
    profile = get_profile(slug)
    approved = _read(state_dir(slug) / "approved.json", {}).get(key)
    if not approved:
        raise ValueError("Approve this piece first - the PDF only contains approved text.")
    if key == "pack_menu_copy" and not content_gen.menu_items(profile):
        raise ValueError("No dishes saved yet, so there's no menu text to print.")
    body = _html_lines(approved["text"]) if key == "pack_landing" else approved["text"]
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, _pdf_text(f"{profile['name']} - {PDF_PIECES[key]}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)
    for para in body.split("\n"):
        pdf.multi_cell(0, 6, _pdf_text(para) if para.strip() else " ", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 8)
    pdf.ln(4)
    pdf.multi_cell(0, 5, _pdf_text(f"Approved {approved['at']} - prepared with PlateRank from the restaurant's own facts."), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _tag(*words) -> str:
    """('PB', 'HappyHour') -> #PBHappyHour; ('pacific beach',) -> #PacificBeach (existing capitals are kept)."""
    parts = [p_ for w in words if w for p_ in re.split(r"[\s-]+", w) if p_]
    return "#" + "".join(re.sub(r"[^A-Za-z0-9]", "", p_ if any(ch.isupper() for ch in p_) else p_.capitalize()) for p_ in parts)


def social_hygiene(profile: dict, lost_categories: list[str], site_now: dict | None = None,
                   review_sites: list[str] | None = None) -> dict:
    """Hashtags + search keywords from the profile and the question types it is losing, and a consistency
    checklist. Facts only: a hashtag is only suggested for something the profile says the place offers."""
    import unicodedata
    plain = lambda s: "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    name, cuisine, area = profile["name"], profile["cuisine"], profile["area"]
    city, hood = profile.get("city") or "", profile.get("neighbourhood") or area
    nick = (profile.get("area_nicknames") or [None])[0]
    place = nick or area
    hl = " ".join(profile.get("highlights") or []).lower()
    tags = [_tag(plain(area)), _tag(plain(cuisine), "Food", plain(city)), _tag(plain(city), "Eats")]  # a bare nickname (#PB) is too vague
    tags += [_tag(plain(a), plain(city)) for a in profile.get("cuisine_alternates") or []]
    if "happy hour" in hl: tags.append(_tag(place, "HappyHour"))
    if re.search(r"cocktail|bar\b|wine|beer", hl): tags.append(_tag(place, "Cocktails"))
    for d in ("gluten-free", "vegan", "vegetarian"):
        if d.split("-")[0] in hl: tags.append(_tag(d.replace("-", " "), plain(city)))
    if "cater" in hl: tags.append(_tag(plain(city), "Catering"))
    if re.search(r"private|event", hl): tags.append(_tag(plain(city), "PrivateEvents"))
    lost_tags = {"date-night": (place, "DateNight"), "lunch": (place, "Lunch"), "group": (plain(city), "GroupDining"),
                 "happy-hour": (place, "HappyHour"), "drinks": (place, "Cocktails"), "events": (plain(city), "PrivateEvents")}
    for c in lost_categories:
        if c in lost_tags and (c not in ("happy-hour", "drinks", "events") or c.replace("-", " ") in hl or c == "events" and re.search(r"private|event|cater", hl)
                               or c == "drinks" and re.search(r"cocktail|bar\b|wine|beer", hl)):
            tags.append(_tag(*lost_tags[c]))
    tags = list(dict.fromkeys(t for t in tags if t and len(t) > 2))
    street = content_gen._split_address(profile.get("address") or "").get("streetAddress", "")
    street = re.sub(r"^\d+\s+", "", street) if street else ""
    kw = [f"{cuisine} restaurant {hood}", f"{cuisine} food {city}".strip()]
    kw += [f"{a} food {hood}" for a in profile.get("cuisine_alternates") or []]
    kw += [f"{cuisine} near {street}"] if street else []
    kw += [f"happy hour {place}"] if "happy hour" in hl else []
    kw += [f"{d} {cuisine} {city}".strip() for d in ("gluten-free", "vegan", "vegetarian") if d.split("-")[0] in hl]
    kw += [f"{cuisine} catering {city}".strip()] if "cater" in hl else []
    confirm = content_gen._confirm
    menu_link = ((site_now or {}).get("pieces", {}).get("pack_menu_copy", {}) or {}).get("text", "")
    m = re.search(r"→\s*(\S+)", menu_link)
    checklist = [
        f"Use exactly this name on every profile: “{name}”" + (f" (people also write {', '.join(profile.get('aliases') or [])})" if profile.get("aliases") else ""),
        f"Same address everywhere: {profile.get('address') or confirm('street address')}",
        f"Same hours everywhere: {profile.get('hours') or confirm('opening hours')}",
        f"Menu link in every bio: {(m.group(1) if m else None) or profile.get('website') or confirm('menu link')}",
        "Reply to recent reviews" + (f" - we found verified ones on {', '.join(review_sites)}" if review_sites else "") + ".",
        ("Name your dishes in captions: " + ", ".join(profile["signature_terms"][:5])) if profile.get("signature_terms")
        else "Name your dishes in captions - " + confirm("the dishes you're known for"),
    ]
    return {"hashtags": tags[:12], "keywords": list(dict.fromkeys(kw))[:8], "checklist": checklist,
            "note": "Instagram and TikTok bring reach; AI assistants mostly cite reviews, YouTube, listicles and Reddit."}


def _housekeeping(slug: str, profile: dict, lost_categories: list[str]) -> dict:
    now = _read(state_dir(slug) / "site_now.json", None)
    pub = public_reviews(slug) or {}
    sites = sorted({x.get("site") for x in pub.get("items", []) if (x.get("evidence") or {}).get("status") == "verified" and x.get("site")})
    return {"site_now": now, "reminders": _read(state_dir(slug) / "reminders.json", {}),
            "social": social_hygiene(profile, lost_categories, now, sites), "pdf_keys": list(PDF_PIECES)}


# ------------------------------------------------------------------ data farming: Reddit (owner-voiced, owner posts)
def farm_view(slug: str) -> dict:
    from . import reddit
    data = reddit.load(slug)
    approvals = _read(state_dir(slug) / "approved.json", {})
    links = {}
    for d in data.get("drafts", []):
        ap = approvals.get(d["key"])
        if not ap:
            continue  # "Open on Reddit" only after approval
        links[d["key"]] = ({"href": reddit.submit_link(d["subreddit"], d["post_title"], ap["text"]), "copy": ap["text"], "kind": "post"}
                           if d["type"] == "post" else {"href": d["thread_url"], "copy": ap["text"], "kind": "reply"})
    return {**data, "links": links, "note": reddit.TAB_NOTE, "post_note": reddit.POST_NOTE,
            "cited": reddit.cited_check(data.get("posted", {}), _read(state_dir(slug) / "last_run.json", None)),
            "can_search": slug != EXAMPLE_SLUG and llm.has_key()}


def farm_find(slug: str) -> dict:
    from . import reddit
    if slug == EXAMPLE_SLUG:
        raise ValueError("Reddit search is for your own restaurant - the sample is fictional.")
    reddit.find(slug, get_profile(slug))
    return farm_view(slug)


# ------------------------------------------------------------------ social media: real creators (verified only)
def _lost_from_last_run(slug: str) -> list[str]:
    last = _read(state_dir(slug) / "last_run.json", None)
    if not last:
        return []
    rates = _cat_rates([r for r in last["rows"] if r["status"] != FAILED])
    return [c for c, v in rates.items() if v["rate"] < 0.34]


def _brief_text(c: dict, profile: dict, brief: dict, scored: dict) -> str:
    score = (f"{scored['score_low']}-{scored['score_high']} (range: {', '.join(scored['unknown'])} unknown)"
             if scored.get("unknown") else str(scored["relevance_score"]))
    lines = [f"Creator strategy & brief - {profile['name']} x {c['name']} ({c['platform']})", "",
             f"Profile: {c['url']}", f"Followers: {c['followers'] if c.get('followers') is not None else 'unknown'}",
             f"Local to: {c.get('local_to') or 'unknown'}   Niches: {', '.join(c.get('niches') or [])}",
             f"Match score: {score}", f"Why: {scored['why']}", "",
             f"Video idea: {brief['concept_title']}", f"Target question type: {brief['target_category']}",
             f"Hook: {brief['hook']}", f"Format: {brief['format']}", "", "Must include (so AI assistants can cite it):"]
    lines += [f"- {m}" for m in brief["must_include_for_ai_citation"]] + ["", f"Call to action: {brief['cta']}", "",
              "Facts about the restaurant come only from its saved profile. Nothing here is sent automatically."]
    return "\n".join(lines)


def creators_view(slug: str) -> dict:
    profile = get_profile(slug)
    found = _read(state_dir(slug) / "creators_found.json", None) or {}
    lost = _lost_from_last_run(slug)
    local = local_places(profile)
    saved = {c.get("handle") for c in load_live_creators() if c.get("found_for") == profile["name"]}
    rows = []
    for c in found.get("creators", []):
        scored = score_with_unknowns(c, lost, local)
        brief = content_briefs(c, profile, lost)[0]
        rows.append({**c, "relevance_score": scored["relevance_score"], "score_low": scored["score_low"], "score_high": scored["score_high"],
                     "unknown": scored["unknown"], "why": scored["why"], "brief": brief,
                     "brief_text": _brief_text(c, profile, brief, scored), "outreach": outreach_draft(c, profile, brief),
                     "outreach_key": "outreach_" + str(c["handle"]).lstrip("@"), "saved": c["handle"] in saved})
    rows.sort(key=lambda x: (not x["verified"], -x["relevance_score"]))
    return {"at": found.get("at"), "creators": rows, "found": found.get("found", 0), "dropped_no_url": found.get("dropped_no_url", 0),
            "rejected": found.get("rejected", 0), "lost_categories": lost,
            "can_search": slug != EXAMPLE_SLUG and llm.has_key()}


def creators_find(slug: str) -> dict:
    from .creators import find_creators
    if slug == EXAMPLE_SLUG:
        raise ValueError("Creator search is for your own restaurant - the sample uses SAMPLE creator profiles.")
    find_creators(slug, get_profile(slug), _lost_from_last_run(slug))
    return creators_view(slug)


def creators_save(slug: str, handles: list[str]) -> dict:
    from .creators import save_live
    profile = get_profile(slug)
    found = (_read(state_dir(slug) / "creators_found.json", None) or {}).get("creators", [])
    picked = [c for c in found if c["handle"] in handles]
    if any(not c["verified"] for c in picked):
        raise ValueError("Only verified creators can be saved - open the link of an unchecked one first.")
    save_live(slug, profile["name"], picked)
    return creators_view(slug)


def results(slug: str) -> dict | None:
    profile = get_profile(slug)
    last = _read(state_dir(slug) / "last_run.json", None)
    if profile is None or not last:
        return None
    is_example = slug == EXAMPLE_SLUG
    target, names = profile["name"], names_of(profile)
    rdir = restaurant_dir(target)
    all_rows, meta = last["rows"], last["meta"]
    rows = [r for r in all_rows if r["status"] != FAILED]
    approvals = _read(state_dir(slug) / "approved.json", {})
    out = {"restaurant": target, "slug": slug, "is_sample": is_example, "meta": meta, "questions": QUESTIONS,
           "approvals": approvals}
    if not rows:
        out["empty"] = True
        return out

    # ---- 1. Where do I rank?
    card = scorecard(rows, target, names)
    cats = by_category(rows, target)
    me = card[card.restaurant == target].iloc[0]
    rivals = card[card.restaurant != target]
    top = rivals.iloc[0] if not rivals.empty else None
    lost = cats[cats.mention_rate == 0].category.tolist()
    out["rank"] = {
        "mention_rate": float(me.mention_rate), "mentions": int(me.mentions), "answers": len(rows),
        "avg_rank": None if pd.isna(me.avg_rank) else float(me.avg_rank),
        "share_of_voice": float(me.share_of_voice),
        "top_competitor": None if top is None else {"name": top.restaurant, "mention_rate": float(top.mention_rate)},
        "scorecard": json.loads(card.to_json(orient="records")),
        "by_category": json.loads(cats.sort_values("mention_rate").to_json(orient="records")),
        "categories_at_zero": lost,
        "answers_list": [{"query": r["query"], "category": r["category"], "platform": r["platform"],
                          "model": r.get("model", ""), "run": r["run_id"], "status": r["status"],
                          "mentions": r["ordered_mentions"], "mentioned": r["mentioned"], "rank": r["rank"],
                          "answer": r["answer"], "note": r.get("note", ""), "sources": r.get("sources", [])}
                         for r in all_rows],
    }

    # ---- 2. Why are competitors beating me?
    src_data = load_demo_sources() if is_example else load_sources(rdir / "sources.json")
    site = _read(state_dir(slug) / "site_audit.json", {})
    audit = audit_sources(target, names, src_data)
    for n, a in site.items():
        if a.get("audit"):
            audit.setdefault(n, {"listings": {}, "mentions": {}})["website"] = a["audit"]
    cat_rates = {r["category"]: r["mention_rate"] for r in out["rank"]["by_category"]}
    gaps = prioritized_gaps(audit, target, cat_rates)
    site_gaps = []
    if len(site) == 2 and all(v.get("audit") for v in site.values()):
        comp = next(n for n in site if n != target)
        site_gaps = diagnose(site[target]["audit"], site[comp]["audit"], comp)
    domains = Counter(_domain(s["url"]) for r in rows for s in (r.get("sources") or []) if s.get("url"))
    out["why"] = {"ai_says": ai_says(profile, rows),
        "gaps": gaps, "site_gaps": site_gaps, "site_audit": site,
        "ai_recommends_instead": ai_recommended(rows, [target] + names)[:15],
        "competitor_frequency": json.loads(competitor_frequency(rows).head(12).to_json(orient="records")),
        "sources_ai_used": [{"domain": d, "answers": k} for d, k in domains.most_common(15)],
        "listings_note": ("SAMPLE listings and mention counts." if is_example else
                          ("Listings from sources.json." if src_data else
                           "No ratings / review counts saved yet - use 'Find public ratings' to fill them.")),
        "listings": {n: d.get("listings", {}).get("google", {}) | {"source": d.get("source", "")}
                     for n, d in src_data.items() if n in [target] + names},
    }
    lost_categories = [c for c, rate in cat_rates.items() if rate < 0.34] or list(cat_rates)[:2]

    # ---- Value-for-Money (feeds 'change')
    reviews = load_reviews_demo() if is_example else load_reviews(rdir / "reviews.json")
    bench = area_benchmark(profile.get("competitor_menus", {}))
    lv = [d.get("listings", {}).get("google", {}).get("price_level") for n, d in src_data.items() if n in names]
    lv = [x for x in lv if x]
    area_pl = round(sum(lv) / len(lv), 2) if lv else None
    tiers = by_dimension(rows, target, "price_tier")
    cheap_rate = float(tiers.query("price_tier=='cheap'")["mention_rate"].iloc[0]) if "cheap" in list(tiers["price_tier"]) else 0.0
    vfm, target_analysis = None, None
    if reviews:
        comp_menus = {n: {"hero_dish_price": m.get("entree_price"), "anchor_price": m.get("anchor_price")}
                      for n, m in profile.get("competitor_menus", {}).items()}
        analyses = []
        for name, data in reviews["restaurants"].items():
            menu = profile.get("menu", {}) if name == target else comp_menus.get(name, {})
            a = analyse_restaurant(name, data, menu, bench, cheap_rate if name == target else 0.0, area_pl,
                                   profile.get("anchor_item") or "everyday item", food_words(profile))
            a["source"] = data.get("source", "SAMPLE" if is_example else "")
            analyses.append(a)
            if name == target:
                target_analysis = a
        vfm = {"analyses": analyses, "benchmark": bench, "benchmark_label": benchmark_label(bench),
               "area_price_level": area_pl, "area_price_level_n": len(lv)}
    menu = profile.get("menu", {})
    scenario = (price_scenario(menu.get("hero_dish_name") or "Hero dish", menu["hero_dish_price"],
                               bench["entree_avg"], bench["entree_avg"])
                if menu.get("hero_dish_price") and bench.get("entree_avg") else None)

    # ---- 3. What should I change?  (every gap, routed to the engine that fixes it)
    moves = [{"title": g["gap"], "evidence": g["evidence"], "route": g["action"], "priority": g["priority"],
              "categories": g["affected_categories"]} for g in gaps]
    moves += [{"title": s, "evidence": "Website audit vs top competitor", "route": "standard", "priority": None,
               "categories": []} for s in site_gaps if not s.startswith("No structural gaps")]
    if target_analysis:
        moves += [{"title": f"{r['area']}: {r['recommendation']}", "evidence": r["evidence"], "quote": r["example_quote"],
                   "route": "vfm", "priority": None, "categories": []} for r in target_analysis["recommendations"]]
    out["change"] = {"moves": moves, "lost_categories": lost_categories, "vfm": vfm,
                     "vfm_needs_reviews": reviews is None, "price_scenario": scenario}

    # ---- 4. Can you make the changes?  (drafts; owner approves each)
    t_site = site.get(target, {}).get("audit") or (src_data.get(target, {}).get("website", {}) if is_example else {})
    weak = [k for k, v in (target_analysis or {}).get("aspects", {}).items()
            if v["pos_ratio"] is not None and v["pos_ratio"] < 0.5 and v["mentions"] >= 3]
    facts = _faq_facts(profile, t_site, weak)
    pool = load_demo_creators() if is_example else load_live_creators()
    creators = []
    for c in match_creators(pool, lost_categories, local=local_places(profile)):
        brief = content_briefs(c, profile, lost_categories)[0]
        creators.append({**c, "brief": brief, "outreach": outreach_draft(c, profile, brief)})
    faq_text = faq_page(target, profile["area"], facts)
    out["make"] = {
        "drafts": [
            {"key": "faq_page", "title": "FAQ page", "kind": "text", "text": faq_text},
            {"key": "outreach_email", "title": "Pitch to local food writers", "kind": "text",
             "text": outreach_email(profile)},
        ],
        "creators": creators,
        "creators_note": ("SAMPLE creator profiles." if is_example else
                          ("Verified creators from data/live/creators_live.json." if pool else
                           "No verified creators added yet (Phase 5).")),
        "pack": content_pack_view(slug, profile, t_site, (reviews or {}).get("restaurants", {}).get(target), faq_text),
        "housekeeping": _housekeeping(slug, profile, lost_categories),
    }

    # ---- 5. Did my visibility improve?
    hist = [] if is_example else load_runs(target)
    out["mailto"] = _mailtos(approvals, target)
    out["improve"] = {"history": hist, "compare": improvement(slug), "note": "Same-day changes are directional - AI answers vary run to run. "
                                               "The claim is the repeated re-test, not an instant jump."}
    return overview(slug, out)
