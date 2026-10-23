"""AI-readability (Housekeeping): research the restaurant's real website, then draft the fixes.

Deterministic by design - no AI writes any markup:
  research()  fetches the site's homepage, /robots.txt and /llms.txt (plus competitor sites that have a
              website saved), parses title / meta description / Open Graph / JSON-LD / robots rules,
              and records what it read in the evidence ledger (free - plain page fetches, no Claude).
  view()      turns those findings + the profile facts + the question types AI is losing into 5 drafts:
              visible FAQ section, title + meta description, robots.txt, schema (JSON-LD), llms.txt.
              Each draft says what we found (with its URL), why, and how strong the evidence is
              (research notes in aiso_research.json, each with its source).
Nothing is changed on the live site; the owner approves and adds each piece.
"""
import json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import evidence
from .content_gen import restaurant_jsonld, CONFIRM

RESEARCH = json.loads((Path(__file__).parent / "aiso_research.json").read_text(encoding="utf-8"))["notes"]
SEARCH_BOTS = ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User"]
TRAINING_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended"]
TITLE_MAX, DESC_MAX = 60, 155
STRENGTH_ORDER = {"Strong": 0, "Mixed": 1, "Weak": 2}
TOPIC = {"happy-hour": "happy hour", "drinks": "drinks / cocktails", "dietary": "dietary options", "events": "events / catering",
         "group": "groups", "date-night": "date night", "lunch": "lunch", "late-night": "late night"}

_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _path(slug: str) -> Path:
    return evidence.ledger_path(slug).parent / "aiso.json"


def load(slug: str) -> dict | None:
    p = _path(slug)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ parsing (pure functions, tested offline)
def _meta(html: str, attr: str, name: str) -> str | None:
    for m in re.finditer(r"<meta\b[^>]*>", html or "", re.I):
        tag = m.group(0)
        if re.search(rf'{attr}\s*=\s*["\']{re.escape(name)}["\']', tag, re.I):
            c = re.search(r'content\s*=\s*"([^"]*)"', tag, re.I) or re.search(r"content\s*=\s*'([^']*)'", tag, re.I)
            if c:
                return c.group(1).strip()
    return None


def ld_types(html: str) -> tuple[list[str], bool]:
    """Every JSON-LD @type on the page (including inside an @graph, e.g. Yoast's), and whether an @graph was used."""
    types, graph = [], False
    for m in _LD_RE.finditer(html or ""):
        try:
            d = json.loads(m.group(1).strip())
        except ValueError:
            continue
        items = d if isinstance(d, list) else ([*d["@graph"]] if isinstance(d, dict) and "@graph" in d else [d])
        graph |= isinstance(d, dict) and "@graph" in d
        for x in items:
            if isinstance(x, dict):
                t = x.get("@type")
                types += t if isinstance(t, list) else [t] if t else []
    return types, graph


def parse_page(html: str, base: str) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    types, graph = ld_types(html)
    tel = re.search(r'href=["\']tel:([+\d().\s-]{7,})["\']', html or "", re.I)
    menus = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
        label = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        href = m.group(1)
        if "menu" in (href + " " + label).lower() and not href.startswith(("#", "mailto:", "tel:")):
            u = urljoin(base, href)
            if u not in [x["url"] for x in menus]:
                menus.append({"url": u, "label": label[:60] or u.rsplit("/", 1)[-1]})
    return {"title": re.sub(r"\s+", " ", title.group(1)).strip() if title else None,
            "description": _meta(html, "name", "description"),
            "og_title": _meta(html, "property", "og:title"), "og_description": _meta(html, "property", "og:description"),
            "jsonld_types": types, "yoast_graph": graph and any(t in ("WebSite", "Organization", "WebPage") for t in types),
            "phone": re.sub(r"[^\d+]", "", tel.group(1)) if tel else None, "menu_links": menus[:6]}


def parse_robots(txt: str) -> dict:
    """Groups of user agents -> their rules. Enough to tell: are AI bots blocked? is there a crawl-delay?"""
    groups, cur, last_was_agent = [], None, False
    for raw in (txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = [s.strip() for s in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not last_was_agent or cur is None:
                cur = {"agents": [], "disallow": [], "allow": [], "crawl_delay": None}
                groups.append(cur)
            cur["agents"].append(v)
            last_was_agent = True
            continue
        last_was_agent = False
        if cur is None:
            continue
        if k == "disallow" and v:
            cur["disallow"].append(v)
        elif k == "allow" and v:
            cur["allow"].append(v)
        elif k == "crawl-delay":
            cur["crawl_delay"] = v
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt or "")

    def blocked(bot: str) -> bool:
        g = next((g for g in groups if any(a.lower() == bot.lower() for a in g["agents"])), None) or \
            next((g for g in groups if "*" in g["agents"]), None)
        return bool(g and "/" in g["disallow"])
    return {"groups": groups, "sitemaps": sitemaps,
            "blocked": {b: blocked(b) for b in SEARCH_BOTS + TRAINING_BOTS},
            "crawl_delay": next((g["crawl_delay"] for g in groups if "*" in g["agents"] and g["crawl_delay"]), None),
            "names_ai_bots": any(a in SEARCH_BOTS + TRAINING_BOTS for g in groups for a in g["agents"])}


# ------------------------------------------------------------------ research (page fetches only, no AI)
def _get_text(url: str, get=None) -> tuple[str | None, str]:
    import requests
    get = get or evidence.FETCH or requests.get
    try:
        r = get(url, timeout=evidence.TIMEOUT, headers=evidence.UA)
        if r.status_code == 404:
            return None, "not found (404)"
        if r.status_code >= 400:
            return None, f"answered {r.status_code}"
        if "html" in (r.headers.get("content-type") or "").lower() and url.endswith(".txt"):
            return None, "no file (the site returned a web page instead)"
        return r.text, ""
    except Exception as e:
        return None, f"didn't load ({type(e).__name__})"


def _site(url: str, get=None) -> dict:
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    page, why = evidence.fetch_page(url, get=get)
    out = {"url": url, "at": time.strftime("%Y-%m-%d %H:%M"), "ok": page is not None, "error": why or None}
    if page:
        out["page"] = parse_page(page["html"], url)
    robots, rwhy = _get_text(base + "/robots.txt", get)
    out["robots_url"], out["robots"] = base + "/robots.txt", (parse_robots(robots) if robots is not None else None)
    out["robots_raw"] = (robots or "")[:2000] if robots is not None else None
    out["robots_error"] = rwhy or None
    llms, lwhy = _get_text(base + "/llms.txt", get)
    out["llms_url"], out["llms_txt"] = base + "/llms.txt", llms is not None and bool(llms.strip())
    out["llms_note"] = "found" if out["llms_txt"] else (lwhy or "empty")
    return out


def research(slug: str, profile: dict, get=None) -> dict:
    if not profile.get("website"):
        raise ValueError("Add the restaurant's website in Setup first - there's nothing to read yet.")
    own = _site(profile["website"], get)
    comps = []
    for c in profile.get("competitors", []):
        if c.get("website"):
            s = _site(c["website"], get)
            comps.append({"name": c["name"], **s})
        else:
            comps.append({"name": c["name"], "url": None, "ok": False, "error": "no website saved - add it in Setup to compare"})
    data = {"at": time.strftime("%Y-%m-%d %H:%M"), "own": own, "competitors": comps}
    if own["ok"]:
        p = own["page"]
        evidence.record_direct(slug, [{"kind": "quote", "text": v[:300], "source_url": own["url"], "page_title": p.get("title") or "",
                                       "subject": f"your site now: {k}"} for k, v in
                                      (("page title", p.get("title")), ("meta description", p.get("description")),
                                       ("schema types", ", ".join(p["jsonld_types"]) or None)) if v])
    if own.get("robots_raw"):
        evidence.record_direct(slug, [{"kind": "quote", "text": own["robots_raw"][:300], "source_url": own["robots_url"],
                                       "subject": "your site now: robots.txt"}])
    _path(slug).parent.mkdir(parents=True, exist_ok=True)
    _path(slug).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


# ------------------------------------------------------------------ facts
def facts(profile: dict, own: dict | None) -> dict:
    hours = profile.get("hours") or ""
    hh = re.search(r"happy hour[^;,.]*?(daily|every day|mon[^;,]*?|[A-Z][a-z]{2}[^;,]*?)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[–-]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm))", hours, re.I)
    hl = {h.lower() for h in profile.get("highlights") or []}
    page = (own or {}).get("page") or {}
    return {"name": profile["name"], "cuisine": profile["cuisine"], "alt": [c for c in profile.get("cuisine_alternates") or [] if c],
            "area": profile.get("neighbourhood") or profile.get("area") or "", "city": profile.get("city") or "",
            "address": profile.get("address") or "", "hours": hours.split(";")[0].strip(),
            "happy_hour": (f"{(hh.group(1) or 'daily').strip()} {hh.group(2)}".strip() if hh else None) if "happy hour" in hl else None,
            "cocktails": "Greek-mythology cocktails" if "greek-mythology cocktails" in hl else ("cocktails" if "cocktails" in hl else None),
            "full_bar": "full bar" in hl, "vegan": "vegan" in hl, "gluten_free": "gluten-free" in hl,
            "catering": "catering" in hl, "private_events": "private events" in hl, "groups": "group dining" in hl,
            "year": profile.get("year_opened"), "phone": profile.get("phone") or page.get("phone"),
            "phone_source": "profile" if profile.get("phone") else ((own or {}).get("url") if page.get("phone") else None),
            "menus": page.get("menu_links") or [], "website": profile.get("website") or ""}


def _fmt_phone(p: str | None) -> str | None:
    d = re.sub(r"\D", "", p or "")[-10:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else p


# ------------------------------------------------------------------ the drafts
def faq_pairs(f: dict, lost: list[str]) -> list[tuple[str, str, str]]:
    """(topic, question, answer) - only questions we can answer from facts."""
    street = f["address"].split(",")[0].strip() if f["address"] else ""
    n, where = f["name"], f"{street} in {f['area']}" if street else f["area"]
    out = []
    if f["happy_hour"]:
        out.append(("happy-hour", f"Does {n} have a happy hour?", f"Yes - happy hour is {f['happy_hour']} at {where}."))
    if f["cocktails"] or f["full_bar"]:
        bar = "a full bar" if f["full_bar"] else "a bar"
        out.append(("drinks", f"Does {n} serve cocktails?", f"Yes - {bar}" + (f" with {f['cocktails']}." if f["cocktails"] else ".")))
    if f["vegan"] or f["gluten_free"]:
        opts = " and ".join(x for x in ("vegan" if f["vegan"] else "", "gluten-free" if f["gluten_free"] else "") if x)
        out.append(("dietary", f"Does {n} have {opts} options?", f"Yes - the menu has {opts} options. Tell your server about any allergy."))
    if f["catering"] or f["private_events"]:
        what = " and ".join(x for x in ("catering" if f["catering"] else "", "private events" if f["private_events"] else "") if x)
        out.append(("events", f"Does {n} do {what}?", f"Yes - {n} offers {what}. Contact the restaurant to plan yours."))
    if f["groups"]:
        out.append(("group", f"Is {n} good for groups?", f"Yes - {n} takes group dining."))
    if f["hours"]:
        out.append(("generic", f"What are {n}'s hours?", f"{f['hours']}."))
    if f["address"]:
        out.append(("generic", f"Where is {n}?", f"{f['address']}, in {f['area']}, {f['city']}."))
    rank = {c: i for i, c in enumerate(lost)}
    return sorted(out, key=lambda x: rank.get(x[0], 99))


def title_meta(f: dict) -> tuple[str, str]:
    n, c, a = f["name"], f["cuisine"], f["area"]
    extra = "Happy Hour" if f["happy_hour"] else ("Cocktails" if f["cocktails"] else "")
    cand = [f"{n} | {c} Food & {extra} in {a}, {f['city']}", f"{n} | {c} Food & {extra} in {a}"] if extra else []
    cand += [f"{n} | {c} Restaurant in {a}, {f['city']}", f"{n} | {c} Restaurant in {a}", f"{n} | {c} Restaurant"]
    title = next((t for t in cand if len(t) <= TITLE_MAX), cand[-1][:TITLE_MAX])
    kinds = " & ".join([c] + f["alt"][:1])
    parts = [f"{kinds} food in {a}, {f['city']}" + (f" since {f['year']}." if f["year"] else ".")]
    if f["happy_hour"]:
        parts.append(f"Happy hour {f['happy_hour']}.")
    if f["cocktails"]:
        parts.append(f"{f['cocktails'][0].upper() + f['cocktails'][1:]}.")
    diet = " & ".join(x for x in ("vegan" if f["vegan"] else "", "gluten-free" if f["gluten_free"] else "") if x)
    if diet:
        parts.append(f"{diet[0].upper() + diet[1:]} options.")
    if f["catering"]:
        parts.append("Catering.")
    desc = ""
    for p in parts:  # add clauses in priority order while they fit
        if len((desc + " " + p).strip()) <= DESC_MAX:
            desc = (desc + " " + p).strip()
    return title, desc


def jsonld(profile: dict, f: dict, pairs: list) -> tuple[dict, list[str]]:
    """Restaurant + FAQPage in one @graph, from facts only. Unknown fields are LEFT OUT (listed), never guessed."""
    rest = restaurant_jsonld({**profile, "hours": f["hours"], "phone": _fmt_phone(f["phone"]) if f["phone"] else None})
    left_out = []
    for k in list(rest):
        if isinstance(rest[k], str) and CONFIRM in rest[k]:
            left_out.append(k)
            del rest[k]
    rest.pop("@context", None)
    feats = [x for x, ok in (("Full bar", f["full_bar"]), (f"Happy hour {f['happy_hour']}" if f["happy_hour"] else "", bool(f["happy_hour"])),
                             ("Vegan options", f["vegan"]), ("Gluten-free options", f["gluten_free"]), ("Catering", f["catering"]),
                             ("Private events", f["private_events"]), ("Group dining", f["groups"])) if ok]
    if feats:
        rest["amenityFeature"] = [{"@type": "LocationFeatureSpecification", "name": x, "value": True} for x in feats]
    if f["menus"]:
        rest["hasMenu"] = [m["url"] for m in f["menus"]]
    else:
        left_out.append("hasMenu")
    graph = [rest]
    if pairs:
        graph.append({"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                                                         for _, q, a in pairs]})
    return {"@context": "https://schema.org", "@graph": graph}, left_out


def validate_jsonld(text: str, profile: dict, f: dict) -> list[str]:
    """Plain-English problems; [] = valid. Every value must come from the profile/site facts."""
    try:
        d = json.loads(text)
    except ValueError as e:
        return [f"Not valid JSON ({e.msg} at line {e.lineno})."]
    errs = []
    if CONFIRM in text:
        errs.append("A placeholder is still in it - fill or remove it.")
    if re.search(r'"(aggregateRating|review)"', text):
        errs.append("Remove ratings/reviews - self-written review markup is against Google's rules and can't be verified.")
    graph = d.get("@graph", [d]) if isinstance(d, dict) else []
    rest = next((x for x in graph if isinstance(x, dict) and x.get("@type") in ("Restaurant", "FoodEstablishment")), None)
    if not rest:
        return errs + ["No Restaurant block."]
    for k in ("name", "address", "url", "servesCuisine"):
        if not rest.get(k):
            errs.append(f"Missing '{k}'.")
    if rest.get("name") and rest["name"] != profile["name"]:
        errs.append(f"Name '{rest['name']}' doesn't match your saved name '{profile['name']}'.")
    if rest.get("telephone") and f["phone"] and re.sub(r"\D", "", rest["telephone"])[-10:] != re.sub(r"\D", "", f["phone"])[-10:]:
        errs.append("Phone number doesn't match the one on your website.")
    street = (rest.get("address") or {}).get("streetAddress", "") if isinstance(rest.get("address"), dict) else ""
    if street and street.lower() not in (profile.get("address") or "").lower():
        errs.append("Street address doesn't match your saved address.")
    for x in graph:
        if isinstance(x, dict) and x.get("@type") in ("Organization", "WebSite") and f.get("yoast"):
            errs.append(f"Your site already outputs {x['@type']} (Yoast) - don't add a second one.")
    return errs


def robots_snippet(own: dict) -> str:
    r = (own or {}).get("robots") or {}
    lines = ["# --- AI search assistants: allowed, so they can read and cite you ---"]
    for b in SEARCH_BOTS:
        lines += [f"User-agent: {b}", "Allow: /", ""]
    lines += ["# --- AI training crawlers: YOUR choice. Option A (allow) - keep as is. Option B (block) - uncomment: ---"]
    for b in TRAINING_BOTS:
        lines += [f"# User-agent: {b}", "# Disallow: /", ""]
    lines += ["# --- Everyone else (your current rule) ---", "User-agent: *", "Disallow:"]
    for s in r.get("sitemaps") or []:
        lines.append(f"Sitemap: {s}")
    return "\n".join(lines).strip() + "\n"


def llms_txt(f: dict) -> str:
    kinds = " & ".join([f["cuisine"]] + f["alt"][:1])
    out = [f"# {f['name']}", "", f"> {kinds} restaurant in {f['area']}, {f['city']}" + (f", since {f['year']}." if f["year"] else "."), "", "## Visit"]
    if f["address"]:
        out.append(f"- Address: {f['address']}")
    if f["hours"]:
        out.append(f"- Hours: {f['hours']}")
    if f["happy_hour"]:
        out.append(f"- Happy hour: {f['happy_hour']}")
    if f["phone"]:
        out.append(f"- Phone: {_fmt_phone(f['phone'])}")
    if f["website"]:
        out.append(f"- Website: {f['website']}")
    if f["menus"]:
        out += ["", "## Menus"] + [f"- [{m['label']}]({m['url']})" for m in f["menus"]]
    good = [x for x, ok in (("Full bar" + (f" with {f['cocktails']}" if f["cocktails"] else ""), f["full_bar"] or bool(f["cocktails"])),
                            ("Vegan options", f["vegan"]), ("Gluten-free options", f["gluten_free"]), ("Catering", f["catering"]),
                            ("Private events", f["private_events"]), ("Group dining", f["groups"])) if ok]
    if good:
        out += ["", "## Good to know"] + [f"- {g}" for g in good]
    return "\n".join(out) + "\n"


def _note(key: str) -> dict:
    return {"text": RESEARCH[key]["claim"], "url": RESEARCH[key]["source"]}


def view(slug: str, profile: dict, lost: list[str]) -> dict:
    data = load(slug)
    if not data:
        return {"researched": False, "items": [], "header": HEADER}
    own = data["own"]
    page = own.get("page") or {}
    f = facts(profile, own)
    f["yoast"] = bool(page.get("yoast_graph"))
    pairs = faq_pairs(f, lost)
    lost_t = [TOPIC[c] for c in lost if c in TOPIC]
    lost_s = ", ".join(lost_t) or "none"
    title, desc = title_meta(f)
    ld, left_out = jsonld(profile, f, pairs)
    ld_text = json.dumps(ld, indent=2, ensure_ascii=False)
    robots = own.get("robots") or {}
    blocked = [b for b, v in (robots.get("blocked") or {}).items() if v and b in SEARCH_BOTS]
    faq_html = "<section id=\"faq\">\n  <h2>Frequently asked questions</h2>\n" + "".join(
        f"  <h3>{q}</h3>\n  <p>{a}</p>\n" for _, q, a in pairs) + "</section>\n"
    now_text = ((page.get("title") or "") + " " + (page.get("description") or "")).lower()
    miss = [t for t in ("happy hour", "cocktails", f["area"]) if t and t.lower() not in now_text]
    covered = [TOPIC.get(t, t) for t in dict.fromkeys(t for t, _, _ in pairs) if t in lost]
    src = own["url"]
    items = [
        {"key": "aiso_faq_section", "title": "A visible FAQ section on your homepage", "strength": "Strong", "file": "faq-section.html", "kind": "code",
         "before": "No FAQ section found on your homepage." if own["ok"] else f"Couldn't read your site: {own['error']}.", "before_url": src,
         "why": f"AI rarely names you for: {lost_s}. These answers say it in plain words on your own page" +
                (f" (covers {', '.join(covered)})." if covered else "."), "research": [_note("visible_text")], "text": faq_html},
        {"key": "aiso_title_meta", "title": "Page title + meta description", "strength": "Mixed", "file": "title-meta.html", "kind": "code",
         "before": f"Title: {page.get('title') or '(none)'}\nDescription: {page.get('description') or '(none)'}" if own["ok"] else
                   f"Couldn't read your site: {own['error']}.", "before_url": src,
         "why": (f"Your current title and description don't mention: {', '.join(miss)}. " if own["ok"] and miss else
                 "Your current title and description already cover the basics. " if own["ok"] else
                 "We couldn't read your current title - compare it yourself. ") +
                f"AI search tools see the title and description first when they decide which pages to open. Lengths: title {len(title)}/{TITLE_MAX}, "
                f"description {len(desc)}/{DESC_MAX}.", "research": [],
         "text": f"<title>{title}</title>\n<meta name=\"description\" content=\"{desc}\">\n<meta property=\"og:title\" content=\"{title}\">\n"
                 f"<meta property=\"og:description\" content=\"{desc}\">\n"},
        {"key": "aiso_robots", "title": "robots.txt: let AI search assistants in", "strength": "Mixed", "file": "robots.txt", "kind": "code",
         "before": own.get("robots_raw") or f"No robots.txt read ({own.get('robots_error') or 'unknown'}).", "before_url": own.get("robots_url"),
         "why": ("We couldn't read your robots.txt - check it yourself. " if not own.get("robots") else
                 "Some AI search bots are BLOCKED today: " + ", ".join(blocked) + ". " if blocked else
                 "Today no AI search bot is blocked" + (", but none is named. " if not robots.get("names_ai_bots") else ". ")) +
                "Naming the search bots makes it explicit; whether AI companies may TRAIN on your site is your choice." +
                (f" Your file also asks every crawler to wait {robots['crawl_delay']} seconds between pages - consider removing that line." if robots.get("crawl_delay") else ""),
         "research": [_note("ai_bots"), _note("robots_is_control")], "text": robots_snippet(own)},
        {"key": "aiso_schema", "title": "Business details + FAQ in the format AI reads (JSON-LD)", "strength": "Weak", "file": "schema.json", "kind": "json",
         "before": ("Schema types on your homepage: " + ", ".join(dict.fromkeys(page["jsonld_types"])) +
                    (" (from your Yoast plugin)" if f["yoast"] else "") + ". No Restaurant or FAQ block.") if page.get("jsonld_types")
                   else ("No schema found on your homepage." if own["ok"] else f"Couldn't read your site: {own['error']}."), "before_url": src,
         "why": "Housekeeping: cheap, keeps your facts consistent. Built by code from your saved facts only - no ratings, nothing guessed." +
                (" Adds Restaurant + FAQPage only; your Yoast plugin already covers WebSite/Organization." if f["yoast"] else "") +
                (f" Left out until you confirm them: {', '.join(left_out)}." if left_out else "") +
                (f" Phone taken from {f['phone_source']}." if f["phone_source"] and f["phone_source"] != "profile" else ""),
         "research": [_note("schema_no_lift")], "text": ld_text, "problems": validate_jsonld(ld_text, profile, f)},
        {"key": "aiso_llms", "title": "llms.txt (optional)", "strength": "Weak", "file": "llms.txt", "kind": "text",
         "before": "You have an llms.txt file." if own.get("llms_txt") else
                   f"No llms.txt on your site ({own.get('llms_note')})." if own.get("llms_note", "").startswith(("not found", "no file", "empty"))
                   else f"Couldn't check for llms.txt ({own.get('llms_note')}).", "before_url": own.get("llms_url"),
         "why": "Optional - a 5-minute file. Almost no AI assistant reads it today, so don't expect it to move anything.",
         "research": [_note("llms_txt_unused")], "text": llms_txt(f)},
    ]
    items.sort(key=lambda x: STRENGTH_ORDER[x["strength"]])
    comps = [{"name": c["name"], "ok": c.get("ok"), "url": c.get("url"), "error": c.get("error"),
              "title": (c.get("page") or {}).get("title"), "schema": (c.get("page") or {}).get("jsonld_types") or [],
              "llms_txt": c.get("llms_txt")} for c in data.get("competitors", [])]
    return {"researched": True, "at": data["at"], "url": src, "ok": own["ok"], "error": own.get("error"), "lost": lost_t,
            "header": HEADER, "items": items, "competitors": comps}


HEADER = ("Markup is housekeeping. The research says what other sites say about you (reviews, Reddit, creators) moves AI "
          "answers most - see Data farming and Social media. These drafts are built by code from your real website and saved facts.")
