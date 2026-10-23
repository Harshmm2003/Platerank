"""The whole pipeline as plain functions, for the web app (api.py) and the checks.

Setup -> Discovery -> Analysis -> 3 Action tracks -> owner approval -> Measurement.
Nothing here is new logic: it calls the existing engines in the same order app.py
(Streamlit) does, and packs the results into one JSON-friendly bundle organised by
the five owner questions. Every number keeps its provenance label (LIVE / CACHED /
DEMO / FAILED, SAMPLE, web-found, owner-entered).
"""
import json, time
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
                          benchmark_label, price_scenario)
from .creators import load_demo_creators, load_live_creators, match_creators, content_briefs, outreach_draft, local_places
from .content_gen import faq_page, outreach_email
from . import content_gen
from .store import answer_runs as store_answer_runs
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
    if key.startswith("pack_") and (not text.strip() or content_gen.CONFIRM in text):
        raise ValueError("Fill in or delete every [OWNER TO CONFIRM] part first - website text is approved only when every fact is confirmed.")
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
PACK_TITLES = {"pack_restaurant_schema": "Restaurant schema (JSON-LD)", "pack_faq_schema": "FAQ schema (JSON-LD)",
               "pack_menu_schema": "Menu schema (JSON-LD)", "pack_about": "About us",
               "pack_menu_copy": "Menu descriptions", "pack_landing": "Local landing page (HTML)"}


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


def make_before_run(slug: str) -> dict | None:
    """'Make the changes' works before the first check: FAQ, outreach email and the content pack only
    need the saved facts. The other four tabs need a check (the UI says so)."""
    profile = get_profile(slug)
    if profile is None:
        return None
    t_site = _read(state_dir(slug) / "site_audit.json", {}).get(profile["name"], {}).get("audit") or {}
    faq_text = faq_page(profile["name"], profile["area"], _faq_facts(profile, t_site, []))
    return {"restaurant": profile["name"], "slug": slug, "is_sample": slug == EXAMPLE_SLUG, "no_run": True,
            "questions": QUESTIONS, "approvals": _read(state_dir(slug) / "approved.json", {}),
            "mailto": _mailtos(_read(state_dir(slug) / "approved.json", {}), profile["name"]),
            "make": {"drafts": [{"key": "faq_page", "title": "FAQ page", "kind": "text", "text": faq_text},
                                {"key": "outreach_email", "title": "Pitch to local food writers", "kind": "text",
                                 "text": outreach_email(profile)}],
                     "creators": [], "creators_note": "Run a check first - creator matches use the question types you're losing.",
                     "pack": content_pack_view(slug, profile, t_site, None, faq_text)}}


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
    out["why"] = {
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
                                   profile.get("anchor_item") or "everyday item")
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
    }

    # ---- 5. Did my visibility improve?
    hist = [] if is_example else load_runs(target)
    out["mailto"] = _mailtos(approvals, target)
    out["improve"] = {"history": hist, "compare": improvement(slug), "note": "Same-day changes are directional - AI answers vary run to run. "
                                               "The claim is the repeated re-test, not an instant jump."}
    return out
