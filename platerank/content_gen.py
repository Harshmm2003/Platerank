"""3. ACTION - generate artifacts the owner can actually use.
Template-based so it works offline; swap in Claude/Gemini calls on the day
for richer copy. Every artifact is a DRAFT until the owner clicks Approve.

Honesty rule: drafts are built ONLY from facts we hold (site audit, menu
prices, review analysis). Anything we don't know becomes an
[OWNER TO CONFIRM: ...] placeholder - the agent never invents a claim
(e.g. "quiet and candle-lit") that the reviews may contradict.
"""
import json, re

SCHEMA_DIETS = {"vegan": "VeganDiet", "gluten-free": "GlutenFreeDiet", "gluten free": "GlutenFreeDiet",
                "vegetarian": "VegetarianDiet", "halal": "HalalDiet", "kosher": "KosherDiet"}

def _confirm(what: str) -> str:
    return f"[OWNER TO CONFIRM: {what}]"

def faq_page(restaurant: str, area: str, facts: dict) -> str:
    """facts: dietary_tags (from the site audit), hero_dish, hero_price, anchor_item +
    anchor_price (from the menu), weak_aspects (review aspects with mostly negative sentiment),
    highlights (owner-given: dietary options, happy hour, events...), address, hours."""
    diet = facts.get("dietary_tags") or []
    hl = [h.strip() for h in facts.get("highlights") or [] if h and h.strip()]
    hl_diet = [h for h in hl if re.search(r"gluten|vegan|vegetarian|dairy|halal|kosher", h, re.I)]
    hero, hero_price, anchor_price = facts.get("hero_dish"), facts.get("hero_price"), facts.get("anchor_price")
    anchor = facts.get("anchor_item") or "everyday item"
    weak = set(facts.get("weak_aspects") or [])
    noise_note = (" - reviews currently complain about noise/seating, so fix that before publishing this answer"
                  if "ambience" in weak else "")
    if hero and hero_price:
        price = f"Our {hero} is ${hero_price}" + (f" and {anchor} is ${anchor_price}." if anchor_price else ".")
    else:
        price = _confirm("current prices of the signature dish and everyday items")
    qs = [
        (f"Does {restaurant} have vegan or gluten-free options?",
         f"Yes - our menu marks {', '.join(diet)} dishes." if diet
         else (f"Yes - {restaurant} offers {_join(hl_diet)} options. Ask your server which dishes fit your needs; "
               "we can't guarantee any dish is free of an allergen.") if hl_diet
         else _confirm("which dishes are vegan / gluten-free / vegetarian (the website lists no dietary tags today)")),
        (f"How much does a meal at {restaurant} cost?", price),
        (f"Where is {restaurant} and when is it open?",
         f"{restaurant} is at {facts['address']}. Hours: {facts.get('hours') or _confirm('opening hours')}."
         if facts.get("address") else _confirm(f"street address near {area} and opening hours")),
        (f"Is {restaurant} good for groups?", _confirm("seating for groups and how long people can stay" + noise_note)),
        (f"Is {restaurant} a good date-night spot?", _confirm("evening hours and atmosphere" + noise_note)),
    ]
    if any("happy hour" in h.lower() for h in hl):
        m = re.search(r"happy hour[:\s]+([^;,\n]+)", facts.get("hours") or "", re.I)
        qs.append((f"Does {restaurant} have a happy hour?",
                   f"Yes - happy hour is {m.group(1).strip()}." if m else _confirm("happy hour days and times")))
    events = [h for h in hl if re.search(r"private|event|party|parties|cater|banquet|group dining|rehearsal", h, re.I)]
    if events:
        qs.append((f"Can {restaurant} host private events or cater?",
                   f"Yes - {restaurant} offers {_join(events)}. Contact the restaurant to plan the details."))
    return "\n\n".join(f"Q: {q}\nA: {a}" for q, a in qs)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

def schema_markup(restaurant: str, url: str, menu_items: list[dict] | None = None,
                  cuisine: str | None = None) -> str:
    """menu_items: [{name, price}] taken from the real menu - never a made-up dish."""
    data = {"@context": "https://schema.org", "@type": "Restaurant", "name": restaurant, "url": url}
    if cuisine:
        data["servesCuisine"] = cuisine
    if menu_items:
        data["hasMenu"] = {"@type": "Menu", "hasMenuSection": {"@type": "MenuSection", "name": "Menu",
                           "hasMenuItem": [{"@type": "MenuItem", "name": m["name"],
                                            "offers": {"@type": "Offer", "price": m["price"], "priceCurrency": "USD"}}
                                           for m in menu_items]}}
    note = ("<!-- Add suitableForDiet (e.g. https://schema.org/VeganDiet) per dish only once the owner confirms "
            "it; add address + openingHours from the Google Business Profile. -->\n")
    return note + '<script type="application/ld+json">\n' + json.dumps(data, indent=2) + "\n</script>"

def outreach_email(profile: dict) -> str:
    """Pitch to a local food blog/listicle writer; the area and cuisine come from the profile."""
    restaurant, cuisine, area = profile["name"], profile["cuisine"], profile["area"]
    return (f"Subject: A {cuisine} spot near {area} your readers may be missing\n\n"
            f"Hi - I run {restaurant}. People asking AI assistants for {cuisine} near {area} "
            f"rarely hear about us yet. We'd love to be considered for your next roundup - "
            f"happy to host a tasting. Thanks!")


# ======================================================================== website content pack
# Schemas are built by code from the facts we hold. Claude only writes wording (about / menu copy /
# landing page) from a fact sheet, and guard_facts() wraps anything in its reply that the fact sheet
# can't back up (times, years, phone numbers, street addresses, prices, other names, award-style claims).
import hashlib, io, zipfile
from html import escape

CONFIRM = "[OWNER TO CONFIRM"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY = {d[:2].lower(): d for d in DAYS}   # "mo", "tu", ... - every spelling starts with these two letters
_DAY_RE = r"(mon|tues?|wed|thu(?:rs?)?|fri|sat|sun|mo|tu|we|th|fr|sa|su)[a-z]*\.?"
_T = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
_RANGE_RE = re.compile(_T + r"\s*(?:-|–|—|to)\s*" + _T, re.I)


def _hhmm(h: str, m: str | None, ap: str | None) -> str:
    h, m = int(h), int(m or 0)
    ap = (ap or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def _times(start, end) -> tuple[str, str]:
    """('3', None, None), ('6', None, 'pm') -> 15:00-18:00: a start without am/pm takes the end's."""
    s_ap = start[2] or (end[2] if end[2] and int(start[0]) <= int(end[0]) else None)
    return _hhmm(start[0], start[1], s_ap), _hhmm(*end)


def _days(text: str) -> list[str] | None:
    t = text.lower().strip()
    if re.fullmatch(r"(daily|every ?day|7 days( a week)?)", t):
        return DAYS[:]
    m = re.fullmatch(_DAY_RE + r"\s*(?:-|–|—|to|through)\s*" + _DAY_RE, t)
    if m:
        a, b = DAYS.index(_DAY[m.group(1)[:2]]), DAYS.index(_DAY[m.group(2)[:2]])
        return [DAYS[(a + i) % 7] for i in range((b - a) % 7 + 1)]
    parts = [p.strip() for p in re.split(r"[/&]|and", t) if p.strip()]
    if not parts or not all(re.fullmatch(_DAY_RE, p) for p in parts):
        return None
    return [_DAY[p[:2]] for p in parts]


def _closes_before_open(g) -> bool:
    return int(g[3]) * 60 + int(g[4] or 0) <= int(g[0]) * 60 + int(g[1] or 0) and int(g[0]) <= 12 and int(g[3]) <= 12


def parse_hours(text: str | None) -> list[dict] | None:
    """'Sun–Thu 11am–9pm, Fri–Sat 11am–9:30pm; happy hour daily 3–6pm' -> schema.org
    openingHoursSpecification. Segments naming something else (e.g. happy hour) are not opening
    hours and are skipped. Anything that doesn't parse cleanly -> None (we never guess hours)."""
    specs = []
    for seg in re.split(r"[;,\n]", text or ""):
        seg = seg.strip()
        if not seg:
            continue
        m = _RANGE_RE.search(seg)
        if not m:
            return None
        label = seg[:m.start()].strip().rstrip(":")
        if re.search(r"happy|kitchen|brunch|bar\b|lunch|dinner|delivery|takeout", label, re.I):
            continue
        days = _days(label)
        if days is None:
            return None
        g = m.groups()
        if not (g[2] or g[5]) and _closes_before_open(g):
            return None  # '11-10' with no am/pm: ambiguous, ask the owner
        opens, closes = _times(g[:3], g[3:])
        specs.append({"@type": "OpeningHoursSpecification", "dayOfWeek": days, "opens": opens, "closes": closes})
    return specs or None


def _split_address(addr: str) -> dict:
    m = re.match(r"\s*(.+?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$", addr or "")
    if m:
        return {"streetAddress": m.group(1), "addressLocality": m.group(2), "addressRegion": m.group(3), "postalCode": m.group(4)}
    return {"streetAddress": addr}


def menu_items(profile: dict) -> list[dict]:
    """Dishes with a price that the owner (or the menu reader) saved - never invented."""
    menu = profile.get("menu") or {}
    out = []
    if menu.get("hero_dish_name") and menu.get("hero_dish_price"):
        out.append({"name": menu["hero_dish_name"], "price": menu["hero_dish_price"]})
    if profile.get("anchor_item") and menu.get("anchor_price"):
        out.append({"name": profile["anchor_item"], "price": menu["anchor_price"]})
    return out


def restaurant_jsonld(profile: dict) -> dict:
    data = {"@context": "https://schema.org", "@type": "Restaurant", "name": profile["name"]}
    if profile.get("website"):
        data["url"] = profile["website"]
    data["servesCuisine"] = [profile["cuisine"]] + [c for c in profile.get("cuisine_alternates") or [] if c]
    if profile.get("address"):
        data["address"] = {"@type": "PostalAddress", **_split_address(profile["address"])}
        if profile.get("city_id"):  # the city list is US-only
            data["address"]["addressCountry"] = "US"
    else:
        data["address"] = _confirm("street address")
    if profile.get("lat") is not None and profile.get("lon") is not None:
        data["geo"] = {"@type": "GeoCoordinates", "latitude": profile["lat"], "longitude": profile["lon"]}
    data["openingHoursSpecification"] = parse_hours(profile.get("hours")) or _confirm(
        "opening hours in a clear format, e.g. 'Mon–Fri 11am–9pm'")
    data["telephone"] = profile.get("phone") or _confirm("phone number")
    data["priceRange"] = "$" * int(profile["price_level"]) if profile.get("price_level") else _confirm("price range ($ to $$$$)")
    if profile.get("year_opened"):
        data["foundingDate"] = str(profile["year_opened"])
    return data


def faq_jsonld(faq_text: str) -> tuple[dict | None, list[str]]:
    """FAQPage from the FAQ draft. Only answers we actually know go in; the rest are listed."""
    pairs = re.findall(r"Q: (.+?)\nA: (.+?)(?=\n\nQ: |\Z)", faq_text, re.S)
    known = [(q, a.strip()) for q, a in pairs if CONFIRM not in a]
    left_out = [q for q, a in pairs if CONFIRM in a]
    if not known:
        return None, left_out
    return ({"@context": "https://schema.org", "@type": "FAQPage",
             "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                            for q, a in known]}, left_out)


def menu_jsonld(profile: dict) -> dict | None:
    items = menu_items(profile)
    if not items:
        return None
    return {"@context": "https://schema.org", "@type": "Menu", "name": f"{profile['name']} menu",
            "hasMenuSection": {"@type": "MenuSection", "name": "Menu", "hasMenuItem": [
                {"@type": "MenuItem", "name": m["name"], "offers": {"@type": "Offer", "price": m["price"], "priceCurrency": "USD"}}
                for m in items]}}


def pack_facts(profile: dict, site_audit: dict | None = None, reviews: dict | None = None) -> dict:
    """The ONLY facts the wording may use. Empty fields are left out, so they can't be 'used'."""
    a = site_audit or {}
    f = {"name": profile["name"], "other_names": profile.get("aliases") or [], "cuisine": profile["cuisine"],
         "cuisine_also_described_as": profile.get("cuisine_alternates") or [], "address": profile.get("address"),
         "neighbourhood": profile.get("neighbourhood"), "area": profile.get("area"),
         "area_nicknames": profile.get("area_nicknames") or [], "city": profile.get("city"), "state": profile.get("state"),
         "hours": profile.get("hours"), "website": profile.get("website"), "phone": profile.get("phone"),
         "year_opened": profile.get("year_opened"), "known_for": profile.get("highlights") or [],
         "signature_dishes": profile.get("signature_terms") or [], "menu_items": menu_items(profile),
         "dietary_tags_on_website": a.get("dietary_tags_found") or [],
         "owner_confirmed_note": profile.get("facts_note")}
    if reviews:
        f["reviews"] = {"source": reviews.get("source"), "avg_rating": reviews.get("avg_rating"),
                        "review_count": reviews.get("review_count"), "pasted_reviews": len(reviews.get("reviews") or [])}
    return {k: v for k, v in f.items() if v not in (None, "", [], {})}


def facts_hash(facts: dict) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


PACK_SYSTEM = (
    "You write website copy for one independent restaurant. Use ONLY the facts in the JSON the user gives you. "
    "Never invent awards, rankings, quotes, reviews, dishes, prices, phone numbers, dates, hours, chef names, "
    "ingredients or history. Never say 'best', '#1', 'award-winning' or 'famous'. If a sentence needs a fact "
    "that isn't there, write [OWNER TO CONFIRM: what is needed] instead. Never say a dish is safe for an "
    "allergy. Plain, warm, specific language; use the street, neighbourhood and area nicknames so AI "
    "assistants and search engines can cite the page. Reply with JSON only.")


def pack_prompt(facts: dict) -> str:
    want = {"about": "About-us copy, about 150 words, 1-2 paragraphs",
            "menu_descriptions": "for EACH item in menu_items only: {name (exactly as given), description (max 25 words)}; [] if there are none",
            "landing": {"intro": "2-3 sentences: what the place is and where",
                        "facts": "5-8 short bullet facts, each taken directly from the facts",
                        "qa": "4-6 {q, a} pairs a local searcher would ask (e.g. dietary options, happy hour, events, location, hours)",
                        "meta_description": "max 155 characters"}}
    return ("FACTS:\n" + json.dumps(facts, indent=1, ensure_ascii=False) +
            "\n\nWrite this JSON (same keys):\n" + json.dumps(want, indent=1))


# ---- fact guard: anything the facts can't back up gets wrapped for the owner to confirm
_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)", re.I)
_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
_PRICE_RE = re.compile(r"\$\s?\d+(?:\.\d{2})?")
_STREET_RE = re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Ave(?:nue)?|St(?:reet)?|Blvd|Boulevard|R(?:oa)?d|Dr(?:ive)?|Way|Pl(?:ace)?|L(?:a)?ne?)\b")
_NAME_RE = re.compile(r"\b(?:Caf[eé]|Restaurant|Taverna|Trattoria|Bistro|Kitchen|Grill|Diner)\s+[A-Z][\w'’]+|\b[A-Z][\w'’]+\s+(?:Caf[eé]|Restaurant|Taverna|Trattoria|Bistro|Kitchen|Grill|Diner)\b")
_CLAIM_RE = re.compile(r"\b(?:award[- ]winning|voted|world[- ]famous|famous|number one|best[- ]in[- ]\w+)\b|#1\b", re.I)


def _norm_time(t: str) -> str:
    m = re.match(_T, t.strip(), re.I)
    return _hhmm(*m.groups()) if m else t


def _fact_times(text: str) -> set[str]:
    out = {_norm_time(t) for t in _TIME_RE.findall(text)}
    for m in _RANGE_RE.finditer(text):
        out.update(_times(m.groups()[:3], m.groups()[3:]))
    return out


def guard_facts(text: str, facts: dict, known_names: list[str] | None = None) -> tuple[str, list[str]]:
    """Wraps every time / year / phone / street / price / restaurant-like name / award-style claim in
    `text` that isn't in `facts` as [OWNER TO CONFIRM: ...]. Returns (text, what was flagged)."""
    src = json.dumps(facts, ensure_ascii=False)
    digits = re.sub(r"\D", "", src)
    low = src.lower().replace("avenue", "ave").replace("street", "st")
    names = {n.lower() for n in [facts.get("name", "")] + facts.get("other_names", []) + (known_names or []) if n}
    times, prices = _fact_times(src), {float(p.replace("$", "").strip()) for p in _PRICE_RE.findall(src)}
    prices |= {float(m["price"]) for m in facts.get("menu_items", [])}
    flagged = []

    def check(pattern, ok):
        def sub(m):
            if ok(m.group(0)):
                return m.group(0)
            flagged.append(m.group(0))
            return f"{CONFIRM}: {m.group(0)}]"
        # text already inside [OWNER TO CONFIRM: ...] is left alone (no double wrapping, safe to re-run)
        parts = re.split(r"(\[OWNER TO CONFIRM:[^\]]*\])", text)
        return "".join(p if i % 2 else pattern.sub(sub, p) for i, p in enumerate(parts))

    text = check(_STREET_RE, lambda t: t.lower().replace("avenue", "ave").replace("street", "st") in low)
    text = check(_PHONE_RE, lambda t: re.sub(r"\D", "", t) in digits)
    text = check(_TIME_RE, lambda t: _norm_time(t) in times)
    text = check(_YEAR_RE, lambda t: t in src)
    text = check(_PRICE_RE, lambda t: float(t.replace("$", "").strip()) in prices)
    text = check(_NAME_RE, lambda t: any(n in t.lower() or t.lower() in n for n in names))
    text = check(_CLAIM_RE, lambda t: False)
    return text, flagged


def landing_html(profile: dict, landing: dict, faq_ld: dict | None) -> str:
    """A standalone, citable local page: clear facts, Q&A, Restaurant + FAQPage JSON-LD.
    The title is a search phrase, not a 'best' claim."""
    alts = " & ".join([profile["cuisine"]] + (profile.get("cuisine_alternates") or [])[:1])
    place = profile.get("neighbourhood") or profile["area"]
    title = f"{alts} food in {place} - {profile['name']}"
    qa_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": x["q"], "acceptedAnswer": {"@type": "Answer", "text": x["a"]}}
        for x in landing.get("qa", []) if CONFIRM not in x["a"]]}
    scripts = [restaurant_jsonld(profile)] + ([qa_ld] if qa_ld["mainEntity"] else ([faq_ld] if faq_ld else []))
    e = escape
    return "\n".join([
        "<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(title)}</title>", f'<meta name="description" content="{e(landing.get("meta_description", ""))}">',
        *[f'<script type="application/ld+json">\n{json.dumps(s, indent=2, ensure_ascii=False)}\n</script>' for s in scripts],
        "</head>", "<body>", "<main>", f"<h1>{e(title)}</h1>", f"<p>{e(landing.get('intro', ''))}</p>",
        "<h2>At a glance</h2>", "<ul>", *[f"  <li>{e(x)}</li>" for x in landing.get("facts", [])], "</ul>",
        "<h2>Questions people ask</h2>",
        *[f"<h3>{e(x['q'])}</h3>\n<p>{e(x['a'])}</p>" for x in landing.get("qa", [])],
        "</main>", "</body>", "</html>"])


PACK_FILES = {"pack_restaurant_schema": "schema-restaurant.json", "pack_faq_schema": "schema-faq.json",
              "pack_menu_schema": "schema-menu.json", "pack_about": "about.html",
              "pack_menu_copy": "menu-descriptions.html", "pack_landing": "landing-page.html"}


def website_pack_zip(restaurant: str, approved: dict) -> bytes:
    """Only APPROVED pieces go in. head-snippet.html carries every approved JSON-LD as <script> tags."""
    pieces = {k: v["text"] for k, v in approved.items() if k in PACK_FILES}
    if not pieces:
        raise ValueError("Approve at least one piece of the content pack first - only approved text goes in the download.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        head = []
        for k, text in pieces.items():
            name = PACK_FILES[k]
            if name.endswith(".json"):
                z.writestr(name, text)
                head.append(f'<script type="application/ld+json">\n{text}\n</script>')
            elif k == "pack_landing":
                z.writestr(name, text)
            else:
                title = "About us" if k == "pack_about" else "Menu"
                body = "\n".join(f"<p>{escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip())
                z.writestr(name, f'<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8"><title>{escape(title)} - '
                                 f"{escape(restaurant)}</title></head>\n<body>\n<h1>{escape(title)}</h1>\n{body}\n</body>\n</html>")
        if head:
            z.writestr("head-snippet.html", "<!-- Paste inside <head> on the homepage -->\n" + "\n".join(head))
        missing = [f"- {PACK_FILES[k]}" for k in PACK_FILES if k not in pieces]
        z.writestr("README.txt", f"Website content pack for {restaurant} - owner-approved drafts only.\n\nIncluded:\n" +
                   "\n".join(f"- {PACK_FILES[k]}" for k in pieces) +
                   ("\n\nNot included (not approved yet):\n" + "\n".join(missing) if missing else "") +
                   "\n\nhead-snippet.html: paste into the <head> of the homepage. The landing page is a complete page.\n")
    return buf.getvalue()
