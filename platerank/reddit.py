"""DATA FARMING - Reddit agent (owner-voiced, human-in-the-loop).

Finds the local subreddits (with their posting rules) and live threads where people ask for this kind of
place, then drafts replies / posts in the OWNER's voice. Rules:
- Everything taken from the web goes through the evidence ledger; only VERIFIED subreddits, rules and
  threads are used.
- Drafts always say they come from the owner ("Owner of X here - ..."), use only profile facts + verified
  evidence, follow the subreddit's verified rule, are never a review and never pretend to be a customer.
- PlateRank never posts. The owner approves, then opens Reddit and presses Post themselves
  (posting through Reddit's API needs Reddit's approval - Responsible Builder Policy).
"""
import re, time
from urllib.parse import quote

from . import content_gen, evidence, llm
from .store import slugify

SUBS_PROMPT = (
    "Search the web for the Reddit communities where people in {where} ask where to eat: the city and neighbourhood "
    "subreddits and local food subreddits. Reply with ONLY a JSON array (max 6) of objects: name (without r/), url "
    "(https://www.reddit.com/r/<name>/), rules_url (the page that shows its rules, e.g. https://www.reddit.com/r/<name>/about/rules/), "
    "self_promotion ('allowed', 'not allowed', 'weekly thread only' or 'unknown'), weekly_thread (its name or null), "
    "flair_required (true/false/null), rule_quote (the rule about self-promotion or advertising, copied word for word, max 25 "
    "words, or null). Only include communities you actually found. Never guess a rule.")
THREADS_PROMPT = (
    "Search the web for recent Reddit threads (last 12 months) where people ask for recommendations that {name} could "
    "honestly answer: {cuisine} food, {asks} in or near {where}. Reply with ONLY a JSON array (max 8) of objects: "
    "subreddit (without r/), title (the thread title copied exactly), url (the thread's reddit.com link), date (as shown, or "
    "null), asks_for (a few words). Only real threads you found; never invent one.")
DRAFT_SYSTEM = (
    "You draft Reddit comments and posts for a restaurant OWNER to review and post themselves. Every draft starts with "
    "'Owner of {name} here' and is clearly from the restaurant. Use ONLY facts from the JSON. Never write a review, never "
    "pretend to be a customer, never invent dishes, prices, awards, quotes or claims; if a needed fact is missing write "
    "[OWNER TO CONFIRM: what]. Be helpful first: answer the question asked, mention the restaurant once, no hard sell, no "
    "hashtags. Follow each subreddit's rule exactly. Reply with JSON only.")

POST_NOTE = "Posting through Reddit's API needs Reddit's approval (Responsible Builder Policy), so you press Post."
TAB_NOTE = "Posts come from you, as the owner - never fake reviews."


def _sub_name(x: str) -> str:
    return re.sub(r"^(?:https?://(?:www\.|old\.)?reddit\.com)?/?r/", "", str(x or "").strip()).strip("/").split("/")[0]


def path(slug: str):
    return evidence.ledger_path(slug).parent / "reddit.json"


def load(slug: str) -> dict:
    import json
    p = path(slug)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(slug: str, data: dict):
    import json
    p = path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _where(profile: dict) -> str:
    return ", ".join(x for x in (profile.get("neighbourhood") or profile.get("area"), profile.get("city"), profile.get("state")) if x)


def _asks(profile: dict) -> str:
    hl = [h for h in profile.get("highlights") or [] if h][:4]
    return ", ".join(["a good " + profile["cuisine"] + " restaurant"] + hl) or "where to eat"


def find(slug: str, profile: dict) -> dict:
    """Two Claude + web search calls (subreddits, threads), every item checked in the evidence ledger,
    then one call to draft. Saved to reddit.json (posted markers are kept)."""
    old = load(slug)
    loc = llm.location_for(profile)
    r1 = llm.claude_call(SUBS_PROMPT.format(where=_where(profile)), tools=[llm.web_search_tool(max_uses=4, location=loc)], max_tokens=5000)
    subs_raw = _json_list(r1.text)
    subs = []
    for s in subs_raw:
        name = _sub_name(s.get("name") or s.get("url"))
        if not name:
            continue
        items = [{"kind": "quote", "text": f"r/{name}", "source_url": s.get("url") or f"https://www.reddit.com/r/{name}/", "subject": "subreddit"}]
        if s.get("rule_quote") and s.get("rules_url"):
            items.append({"kind": "quote", "text": s["rule_quote"], "source_url": s["rules_url"], "subject": f"r/{name} rule"})
        recs = evidence.record_and_verify(slug, items, citations=r1.citations)
        if recs[0]["status"] != evidence.VERIFIED:
            continue
        rule_ok = len(recs) > 1 and recs[1]["status"] == evidence.VERIFIED
        subs.append({"name": name, "url": items[0]["source_url"], "evidence": evidence.badge(recs[0]),
                     "rules_url": s.get("rules_url"), "rule_quote": s.get("rule_quote") if rule_ok else None,
                     "rule_evidence": evidence.badge(recs[1]) if len(recs) > 1 else None,
                     # a posting permission only counts when the rule itself was verified
                     "self_promotion": (s.get("self_promotion") or "unknown") if rule_ok else "unknown",
                     "weekly_thread": s.get("weekly_thread") if rule_ok else None,
                     "flair_required": s.get("flair_required") if rule_ok else None})
    r2 = llm.claude_call(THREADS_PROMPT.format(name=profile["name"], cuisine=profile["cuisine"], asks=_asks(profile), where=_where(profile)),
                         tools=[llm.web_search_tool(max_uses=5, location=loc)], max_tokens=5000)
    threads_raw = [t for t in _json_list(r2.text) if str(t.get("url", "")).startswith("http") and "reddit.com" in str(t.get("url")) and t.get("title")]
    recs = evidence.record_and_verify(slug, [{"kind": "quote", "text": t["title"], "source_url": t["url"], "subject": f"r/{_sub_name(t.get('subreddit'))} thread"}
                                             for t in threads_raw], citations=r2.citations)
    threads = [{"subreddit": _sub_name(t.get("subreddit")), "title": t["title"], "url": t["url"], "date": t.get("date"),
                "asks_for": t.get("asks_for"), "evidence": evidence.badge(rec)} for t, rec in zip(threads_raw, recs) if rec["status"] == evidence.VERIFIED]
    counts = {"subreddits_found": len(subs_raw), "subreddits_verified": len(subs), "threads_found": len(threads_raw), "threads_verified": len(threads)}
    data = {"at": time.strftime("%Y-%m-%d %H:%M"), "subreddits": subs, "threads": threads, "counts": counts,
            "drafts": draft(profile, subs, threads), "posted": old.get("posted", {}),
            "cost_usd": round(r1.cost_usd + r2.cost_usd, 4)}
    _save(slug, data)
    return data


def _json_list(text: str) -> list[dict]:
    try:
        d = llm.json_from(text or "[]")
    except ValueError:
        return []
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


def draft(profile: dict, subs: list[dict], threads: list[dict]) -> list[dict]:
    """One reply per verified thread; one new post per subreddit whose VERIFIED rule allows self-promotion."""
    allowed = [s for s in subs if s["self_promotion"] == "allowed"]
    if not threads and not allowed:
        return []
    facts = content_gen.pack_facts(profile)
    want = {"replies": [{"thread_url": t["url"], "thread_title": t["title"], "subreddit": t["subreddit"],
                         "rule": next((s["rule_quote"] for s in subs if s["name"] == t["subreddit"] and s["rule_quote"]), None)} for t in threads],
            "posts": [{"subreddit": s["name"], "rule": s["rule_quote"], "flair_required": s["flair_required"]} for s in allowed]}
    import json
    r = llm.claude_call("FACTS:\n" + json.dumps(facts, ensure_ascii=False, indent=1) + "\n\nWRITE (same order):\n" + json.dumps(want, indent=1) +
                        "\n\nReply with JSON: {\"replies\": [{\"text\"}], \"posts\": [{\"title\", \"text\"}]}",
                        system=DRAFT_SYSTEM.format(name=profile["name"]), max_tokens=6000)
    try:
        out = llm.json_from(r.text or "{}")
    except ValueError:
        out = {}
    owner = f"Owner of {profile['name']} here"
    drafts = []

    def clean(text: str) -> tuple[str, list[str]]:
        text = str(text or "").strip()
        if not text.lower().startswith(f"owner of {profile['name'].lower()}"):
            text = f"{owner} - {text}"
        return content_gen.guard_facts(text, facts)

    for t, d in zip(threads, (out.get("replies") or []) if isinstance(out, dict) else []):
        text, flags = clean(d.get("text") if isinstance(d, dict) else d)
        drafts.append({"key": "reddit_" + slugify(t["url"])[-40:], "type": "reply", "subreddit": t["subreddit"], "thread_url": t["url"],
                       "thread_title": t["title"], "title": f"Reply in r/{t['subreddit']}: {t['title']}", "text": text, "flags": flags})
    for s, d in zip(allowed, (out.get("posts") or []) if isinstance(out, dict) else []):
        d = d if isinstance(d, dict) else {}
        body, flags = clean(d.get("text"))
        title, tflags = content_gen.guard_facts(str(d.get("title") or f"{owner} - happy to answer questions"), facts)
        drafts.append({"key": f"reddit_post_{s['name']}", "type": "post", "subreddit": s["name"], "post_title": title,
                       "title": f"New post in r/{s['name']}", "text": body, "flags": flags + tflags, "rule": s["rule_quote"],
                       "flair_required": s["flair_required"]})
    return drafts


def submit_link(subreddit: str, title: str, text: str) -> str:
    """reddit.com/r/<sub>/submit pre-filled. Reddit doesn't document these parameters (title / text / selftext come
    from the old submit form), so the screen ALSO copies the text - if the box is empty, paste."""
    return f"https://www.reddit.com/r/{quote(subreddit)}/submit?selftext=true&title={quote(title)}&text={quote(text)}"


def mark_posted(slug: str, key: str, url: str) -> dict:
    url = url.strip()
    if not re.match(r"^https://(www\.|old\.)?reddit\.com/r/[^/]+/comments/", url):
        raise ValueError("Paste the link of your Reddit post or comment (it starts with https://www.reddit.com/r/.../comments/...).")
    data = load(slug)
    data.setdefault("posted", {})[key] = {"url": url, "at": time.strftime("%Y-%m-%d %H:%M"), "ts": time.time()}
    _save(slug, data)
    return data


def cited_check(posted: dict, last_run: dict | None) -> dict | None:
    """After the owner posts: did reddit.com show up in the websites the AI relied on in the next check?"""
    if not posted:
        return None
    first = min(p["ts"] for p in posted.values())
    if not last_run or last_run["meta"].get("ts", 0) < first:
        return {"status": "waiting", "note": "Run a re-check after posting to see if reddit.com shows up in the AI's sources."}
    rows = [r for r in last_run["rows"] if r.get("status") != "FAILED"]
    n = sum(any("reddit.com" in (s.get("url") or "") for s in r.get("sources") or []) for r in rows)
    return {"status": "cited" if n else "not yet", "answers_citing_reddit": n, "answers": len(rows), "checked": last_run["meta"].get("when"),
            "note": (f"reddit.com was among the websites the AI relied on in {n} of {len(rows)} answers ({last_run['meta'].get('when')}) - directional."
                     if n else f"reddit.com wasn't among the AI's sources in the check of {last_run['meta'].get('when')} yet - directional, check again later.")}
