"""Evidence ledger - every fact or quote we take from the internet, traceable to the page it came from.

One file per restaurant: data/live/<slug>/evidence.json. Each record:
  id, kind, subject, text (the exact quote / value), source_url, page_title, retrieved_at,
  found_by ("Claude web search" / "OpenStreetMap" / "owner"), status, check_note
status:
  verified   - we fetched the cited page ourselves and the text is on it
  unverified - the page wouldn't load / blocked us / needs a browser: shown greyed, "check the link"
  rejected   - the page loaded and the text is NOT on it: kept here, counted, never shown as a fact
Rule: only VERIFIED records may feed scores and drafts. Every feature that takes something from the
web (lookups, competitors, reviews, creators, Reddit...) goes through record_and_verify().
"""
import hashlib, html, json, re, time, unicodedata
from pathlib import Path

import requests

from . import store

UA = {"User-Agent": "PlateRank-Hackathon/1.0 (fact check of a cited page; NYU SPS x Pulse Foundry prototype)"}
TIMEOUT = 8
VERIFIED, UNVERIFIED, REJECTED = "verified", "unverified", "rejected"
FETCH = None  # tests put a fake page fetcher here; None = the real requests.get
MIN_PAGE_CHARS = 400  # less readable text than this = a JS app / consent wall: we can't judge it, so 'unverified'


def ledger_path(slug: str) -> Path:
    return (store.DATA / "example_state" if slug == "example" else store.LIVE / slug) / "evidence.json"


def load(slug: str) -> list[dict]:
    p = ledger_path(slug)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(slug: str, records: list[dict]):
    p = ledger_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- matching
def normalise(s: str) -> str:
    """Lowercase, accents off, curly quotes/dashes straight, '1,234' -> '1234', whitespace collapsed."""
    s = unicodedata.normalize("NFKD", html.unescape(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = (s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-").replace(" ", " "))
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def page_text(raw_html: str) -> tuple[str, str]:
    """(title, visible text) - scripts, styles and tags removed."""
    title = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    return (html.unescape(title.group(1)).strip() if title else ""), html.unescape(body)


def _num_in(n: str, page: str) -> bool:
    """4.5 matches '4.5'; 4 matches '4' or '4.0'; 1234 matches '1,234' (commas already removed)."""
    v = float(n)
    for m in re.finditer(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])", page):
        if abs(float(m.group(0)) - v) < 1e-9:
            return True
    return False


def _times(s: str) -> set[str]:
    out = set()
    for h, m, ap in re.findall(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", s):
        hh = int(h) % 12 + (12 if ap.startswith("p") else 0)
        out.add(f"{hh:02d}:{int(m or 0):02d}")
    for h, m in re.findall(r"\b(\d{1,2}):(\d{2})\b(?!\s*(?:am|pm|a\.m|p\.m))", s):
        out.add(f"{int(h):02d}:{m}")
    return out


def matches(kind: str, text: str, page: str) -> bool:
    """Is `text` on the page? `page` must already be normalise()d."""
    t = normalise(str(text))
    if not t:
        return False
    if kind in ("rating", "review_count") or re.fullmatch(r"\d+(?:\.\d+)?", t):
        return _num_in(t, page)
    if kind == "hours":   # formats vary ("11am" / "11:00 AM"): every time in the claim must be on the page
        need = _times(t)
        return bool(need) and need <= _times(page)
    if kind == "address":  # street line only - cities/zips are written many ways
        t = t.split(",")[0].strip()
        t = t.replace(" avenue", " ave").replace(" street", " st")
        page = page.replace(" avenue", " ave").replace(" street", " st")
    if kind == "phone":
        return re.sub(r"\D", "", t)[-10:] in re.sub(r"\D", "", page)
    if kind == "price_level":
        n = int(float(t)) if t.replace(".", "").isdigit() else len(t)
        return re.search(r"(?<!\$)" + r"\$" * n + r"(?!\$)", page) is not None
    if kind == "name":  # 'KazuNori: The Original Hand Roll Bar' -> also accept 'KazuNori'
        short = re.split(r"\s*[:(|]\s*|\s+-\s+", t)[0].strip()
        return t in page or (len(short) >= 4 and short in page)
    if kind == "website":
        dom = re.sub(r"^https?://(www\.)?", "", t).split("/")[0]
        return dom in page
    # quotes: "..." / "…" are gaps - every part must appear, in order
    pos = 0
    for part in [p.strip() for p in re.split(r"\.\.\.|…", t) if p.strip()]:
        i = page.find(part, pos)
        if i < 0:
            return False
        pos = i + len(part)
    return True


# ---------------------------------------------------------------- recording + verifying
def fetch_page(url: str, get=None) -> tuple[dict | None, str]:
    """One polite fetch. ({"title", "html", "text"}, "") or (None, plain reason)."""
    get = get or FETCH or requests.get
    try:
        r = get(url, timeout=TIMEOUT, headers=UA)
        if r.status_code >= 400:
            return None, f"the page answered {r.status_code} (blocked or gone)"
        if "html" not in (r.headers.get("content-type") or "text/html").lower():
            return None, "the link isn't a web page we can read"
        title, text = page_text(r.text)
        return {"title": title, "html": r.text, "text": re.sub(r"\s+", " ", text).strip()}, ""
    except Exception as e:
        return None, f"the page didn't load ({type(e).__name__})"


def record_direct(slug: str, items: list[dict]) -> list[dict]:
    """Text we just read on a page ourselves (e.g. the owner's site) - verified by that fetch, no second request."""
    now = time.strftime("%Y-%m-%d %H:%M")
    out = [{"id": _id(it["kind"], it["text"], it["source_url"]), "kind": it["kind"], "subject": it.get("subject", ""),
            "text": it["text"], "source_url": it["source_url"], "page_title": it.get("page_title", ""), "found_by": "PlateRank page read",
            "status": VERIFIED, "tier": "page fetch", "check_note": "read directly from the page", "retrieved_at": now} for it in items]
    if slug and out:
        keep = {r["id"]: r for r in load(slug)}
        keep.update({r["id"]: r for r in out})
        _save(slug, sorted(keep.values(), key=lambda r: r.get("retrieved_at", ""), reverse=True))
    return out


def _id(kind: str, text: str, url: str) -> str:
    return hashlib.sha256(f"{kind}|{normalise(str(text))}|{url}".encode()).hexdigest()[:12]


def _same_url(a: str, b: str) -> bool:
    norm = lambda u: re.sub(r"^https?://(www\.)?", "", (u or "").strip()).rstrip("/").lower()
    return norm(a) == norm(b)


def verify(record: dict, get=None, pages: dict | None = None, citations: list | None = None) -> dict:
    """Fetch the cited page (that one URL only, 8 s, polite UA) and check the text is on it.
    If the page can't confirm it (blocked, needs a browser, changed), a web-search citation of that SAME URL whose
    cited_text contains the quote counts as the second tier: verified (search citation)."""
    out = _verify_page(record, get, pages)
    if out["status"] != VERIFIED:
        for c in citations or []:
            if _same_url(c.get("url"), record.get("source_url")) and matches(record["kind"], record["text"], normalise(c.get("cited_text", ""))):
                return {**out, "status": VERIFIED, "tier": "search citation", "page_title": out.get("page_title") or c.get("title", ""),
                        "check_note": "matched the search engine's citation of this page (" + out["check_note"] + ")"}
    return out


def _verify_page(record: dict, get=None, pages: dict | None = None) -> dict:
    get = get or FETCH or requests.get
    url = record.get("source_url") or ""
    now = time.strftime("%Y-%m-%d %H:%M")
    if record.get("found_by") == "owner":
        return {**record, "status": VERIFIED, "tier": "owner", "check_note": "entered by the owner", "retrieved_at": now}
    if not url.startswith(("http://", "https://")):
        return {**record, "status": UNVERIFIED, "check_note": "no link to check", "retrieved_at": now}
    pages = pages if pages is not None else {}
    if url not in pages:
        try:
            r = get(url, timeout=TIMEOUT, headers=UA)
            if r.status_code >= 400:
                pages[url] = (None, f"the page answered {r.status_code} (blocked or gone) - open the link to check")
            elif "html" not in (r.headers.get("content-type") or "text/html").lower():
                pages[url] = (None, "the link isn't a web page we can read - open it to check")
            else:
                title, text = page_text(r.text)
                pages[url] = ((title, normalise(text)), "")
        except Exception as e:  # timeout, DNS, SSL...
            pages[url] = (None, f"the page didn't load ({type(e).__name__}) - open the link to check")
    page, note = pages[url]
    if page is None:
        return {**record, "status": UNVERIFIED, "check_note": note, "retrieved_at": now}
    title, text = page
    out = {**record, "page_title": record.get("page_title") or title, "retrieved_at": now}
    if matches(record["kind"], record["text"], text):
        return {**out, "status": VERIFIED, "tier": "page fetch", "check_note": "found on the cited page"}
    if len(text) < MIN_PAGE_CHARS:
        return {**out, "status": UNVERIFIED, "check_note": "the page needs a browser to read - open the link to check"}
    return {**out, "status": REJECTED, "check_note": "not found on the cited page"}


def record_and_verify(slug: str, items: list[dict], found_by: str = "Claude web search", get=None,
                      citations: list | None = None) -> list[dict]:
    """items: [{kind, text, source_url, subject?, page_title?}] -> checked records, saved to the ledger.
    The same claim from the same page replaces its older record (re-checked, not duplicated)."""
    pages: dict = {}
    out = []
    for it in items:
        rec = {"id": _id(it["kind"], it["text"], it.get("source_url", "")), "kind": it["kind"],
               "subject": it.get("subject", ""), "text": str(it["text"]), "source_url": it.get("source_url", ""),
               "page_title": it.get("page_title", ""), "found_by": it.get("found_by", found_by)}
        out.append(verify(rec, get=get, pages=pages, citations=citations))
    if slug and out:
        keep = {r["id"]: r for r in load(slug)}
        keep.update({r["id"]: r for r in out})
        _save(slug, sorted(keep.values(), key=lambda r: r.get("retrieved_at", ""), reverse=True))
    return out


def badge(rec: dict) -> dict:
    """What the UI shows next to a web-sourced item."""
    return {k: rec.get(k) for k in ("id", "status", "tier", "retrieved_at", "source_url", "page_title", "check_note", "found_by")}


def summary(slug: str) -> dict:
    recs = load(slug)
    counts = {s: sum(r["status"] == s for r in recs) for s in (VERIFIED, UNVERIFIED, REJECTED)}
    return {"records": recs, "counts": counts}


def check_facts(slug: str, subject: str, facts: dict, keys: dict, get=None) -> dict:
    """Web lookup / web facts: verify each value against the URL Claude cited for it.
    keys: {fact key: evidence kind}. Verified values stay; unverified ones move to _unverified (shown greyed,
    never used); rejected ones are dropped and counted. Adds _evidence {key: badge} and _rejected."""
    src = facts.get("sources") or {}
    todo = [(k, kind) for k, kind in keys.items() if facts.get(k) not in (None, "")]
    recs = record_and_verify(slug, [{"kind": kind, "text": facts[k], "source_url": src.get(k, ""), "subject": f"{subject}: {k}"}
                                    for k, kind in todo], get=get)
    ev, unverified, rejected = {}, {}, 0
    for (k, _), rec in zip(todo, recs):
        if rec["status"] == VERIFIED:
            ev[k] = badge(rec)
        elif rec["status"] == UNVERIFIED:
            ev[k] = badge(rec)
            unverified[k] = facts[k]
            facts[k] = None
        else:
            rejected += 1
            facts[k] = None
    facts.update(_evidence=ev, _unverified=unverified, _rejected=rejected)
    return facts
