"""1. DISCOVERY - query bank generation (v3).
The bank builds itself from the restaurant profile (cuisine, area,
neighbourhood, city, landmarks, price level, signature terms - plus optional highlights,
cuisine alternates and area nicknames), so it works for any restaurant. Every query carries its dimensions - category x price tier x
occasion - so Analysis can slice visibility; that's where the diagnosis lives.
The Example dataset (SAMPLE) ships its own fixed bank in data/sample_run.json
so its cached answers still line up.
"""
import json, re
from dataclasses import dataclass
from pathlib import Path

SAMPLE = Path(__file__).parent.parent / "data" / "sample_run.json"

@dataclass
class Query:
    text: str
    category: str          # generic, signature, cheap, value, lunch, date-night, premium, group, dietary, tourist, late-night,
                          # happy-hour, drinks, events (the last three only when the owner lists those highlights)
    price_tier: str = "any"  # cheap, mid, premium, any
    occasion: str = "any"    # date, group, solo, family, celebration, any

def generate_queries(profile: dict) -> list[Query]:
    cuisine = profile["cuisine"].strip()
    area = profile["area"].strip()
    hood = (profile.get("neighbourhood") or area).strip()
    city = (profile.get("city") or "").strip()
    near = f"near {area}" + (f", {city}" if city and city.lower() not in area.lower() else "")
    in_hood = f"in {hood}"
    # an extra landmark (e.g. a station or venue) replaces the area in 3 questions
    marks = [m.strip() for m in profile.get("landmarks") or [] if m.strip()]
    near_lm = f"near {marks[0]}" if marks else near
    sig = [s.strip() for s in profile.get("signature_terms") or [] if s.strip()]
    sig += [f"authentic {cuisine}", f"really fresh {cuisine}", f"{cuisine} chef's specials"]
    upscale = int(profile.get("price_level") or 2) >= 3
    raw = [
        # generic / best-of
        (f"best {cuisine} {near}", "generic", "any", "any"),
        (f"top rated {cuisine} restaurant {in_hood}", "generic", "any", "any"),
        (f"where should I go for {cuisine} {near_lm}?", "generic", "any", "any"),
        (f"hidden gem {cuisine} spot {in_hood}", "generic", "any", "any"),
        (f"best {cuisine} restaurants in {city or hood} right now", "generic", "any", "any"),
        # signature dishes / what the place is known for
        (f"best {sig[0]} {near}", "signature", "any", "any"),
        (f"where to get great {sig[1]} {in_hood}", "signature", "any", "any"),
        (f"{sig[2]} worth the trip {near}", "signature", "any", "any"),
        # cheap / value / lunch - these feed the Value-for-Money engine directly
        (f"cheap {cuisine} {near}", "cheap", "cheap", "any"),
        (f"budget-friendly {cuisine} lunch special {near}", "cheap", "cheap", "solo"),
        (f"affordable {cuisine} dinner {in_hood}", "cheap", "cheap", "any"),
        (f"best value for money {cuisine} {near}", "value", "cheap", "any"),
        ((f"is {cuisine} {in_hood} worth splurging on, and where?" if upscale
          else f"good {cuisine} that won't break the bank {near}"), "value", "any", "any"),
        (f"quick {cuisine} lunch {near_lm}", "lunch", "any", "solo"),
        (f"{cuisine} takeout or delivery {near_lm}", "lunch", "any", "solo"),
        # date night / premium
        (f"romantic {cuisine} dinner {in_hood}", "date-night", "mid", "date"),
        (f"{cuisine} date night spot {near}", "date-night", "mid", "date"),
        (f"quiet {cuisine} restaurant for two {in_hood}", "date-night", "mid", "date"),
        (f"upscale {cuisine} for a special occasion {near}", "premium", "premium", "celebration"),
        (f"best high-end {cuisine} experience {in_hood}", "premium", "premium", "date"),
        # groups
        (f"{cuisine} restaurant good for a group dinner {near}", "group", "mid", "group"),
        (f"{cuisine} spot for a birthday dinner {in_hood}", "group", "mid", "celebration"),
        # dietary
        (f"vegetarian-friendly {cuisine} {near}", "dietary", "any", "any"),
        (f"{cuisine} restaurant with gluten-free options {in_hood}", "dietary", "any", "any"),
        (f"vegan options at {cuisine} restaurants {near}", "dietary", "any", "any"),
        # visitors / families / late night
        (f"best {cuisine} {near} to take out-of-town visitors", "tourist", "mid", "family"),
        (f"family-friendly {cuisine} restaurant {in_hood}", "tourist", "any", "family"),
        (f"{cuisine} open late {near}", "late-night", "any", "any"),
        (f"solo {cuisine} meal at the counter {in_hood}", "generic", "any", "solo"),
        (f"which {cuisine} places {near} do locals actually recommend?", "generic", "any", "any"),
    ]
    # owner-given alternates / nicknames rotate into a FIXED handful of questions (same ones every run,
    # so repeat checks stay comparable): "Mediterranean" for "Greek", "in PB" for "in Pacific Beach"
    alts = _clean(profile.get("cuisine_alternates"))
    nicks = _clean(profile.get("area_nicknames"))
    for n, i in enumerate((4, 11, 20, 25) if alts else ()):
        t, *rest = raw[i]
        raw[i] = (t.replace(cuisine, alts[n % len(alts)], 1), *rest)
    for n, i in enumerate((3, 10, 17, 26) if nicks else ()):
        t, *rest = raw[i]
        raw[i] = (t.replace(in_hood, f"in {nicks[n % len(nicks)]}", 1), *rest)

    street = _street(profile.get("address"))
    v = {"cuisine": cuisine, "alt": alts[0] if alts else cuisine, "nick": nicks[0] if nicks else hood,
         "hood": hood, "near": near, "in_hood": in_hood, "town": city or hood,
         "street_near": f"near {street}" if street else near}
    raw += highlight_queries(_clean(profile.get("highlights")), v)

    seen, out = set(), []
    for t, c, p, o in raw:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(Query(text=t, category=c, price_tier=p, occasion=o))
    return out

MAX_HIGHLIGHT_QUESTIONS = 6   # 30 base questions + at most 6 = 36


def _clean(items) -> list[str]:
    return [x.strip() for x in items or [] if x and x.strip()]


def _street(address: str | None) -> str:
    """'1846 Garnet Ave, San Diego, CA' -> 'Garnet Ave' (house number dropped). '' if it doesn't look like a street."""
    m = re.match(r"\s*\d+[A-Za-z-]*\s+([^,]+)", address or "")
    return m.group(1).strip() if m else ""


def _drink(h: str) -> str:
    return next((w for k, w in (("cocktail", "cocktails"), ("wine", "wine"), ("beer", "craft beer")) if k in h), "drinks")


def _diet(h: str) -> str:
    return next((w for w in ("gluten-free", "vegan", "vegetarian", "dairy-free", "halal", "kosher", "dietary")
                if w.split("-")[0] in h.replace("gluten free", "gluten-free")), "dietary")


# highlight keywords (regex, matched at a word start) -> rule name -> the searches customers type.
# A rule's first question is kept before any rule's second one when the cap is hit.
HIGHLIGHT_RULES = [
    (("happy hour",), "happy-hour", lambda h, v: [
        (f"happy hour with good food {v['street_near']}", "happy-hour", "cheap", "group"),
        (f"best happy hour deals in {v['nick']}", "happy-hour", "cheap", "any")]),
    (("cocktail", r"bar\b", "wine", "beer", "drinks"), "drinks", lambda h, v: [
        (f"date night spot in {v['nick']} with good {_drink(h)}", "drinks", "mid", "date")]),
    (("rehearsal",), "rehearsal", lambda h, v: [
        (f"where to host a rehearsal dinner in {v['hood']}", "events", "mid", "celebration")]),
    (("private", "party", "parties", "banquet", "group dining", "event"), "private", lambda h, v: [
        (f"{v['cuisine']} restaurant with a private room for a party {v['near']}", "events", "mid", "group")]),
    (("cater",), "catering", lambda h, v: [
        (f"{v['cuisine']} catering in {v['town']}", "events", "any", "group")]),
    (("gluten", "vegan", "vegetarian", "dairy", "halal", "kosher", "dietary"), "dietary", lambda h, v: [
        (f"{v['alt']} restaurant with {_diet(h)} options in {v['town']}", "dietary", "any", "any")]),
]


def highlight_queries(highlights: list[str], v: dict) -> list[tuple]:
    """Extra questions for what the owner says the place is known for. Recognised highlights get the
    searches people really type; anything else gets one plain question. Each rule fires once (dietary:
    once per diet), round-robin so the cap keeps one question per highlight before any second ones."""
    groups, fired = [], set()
    for h in highlights:
        hl = h.lower()
        rule = next(((name, make) for keys, name, make in HIGHLIGHT_RULES if any(re.search(r"\b" + k, hl) for k in keys)), None)
        if rule is None:
            groups.append([(f"{v['cuisine']} restaurant with {h} {v['in_hood']}", "generic", "any", "any")])
            continue
        name, make = rule
        key = name + (_diet(hl) if name == "dietary" else "")
        if key not in fired:
            fired.add(key)
            groups.append(make(hl, v))
    out = []
    for rnd in range(max((len(g) for g in groups), default=0)):
        out += [g[rnd] for g in groups if rnd < len(g)]
    return out[:MAX_HIGHLIGHT_QUESTIONS]


def example_queries() -> list[Query]:
    """The fixed bank of the SAMPLE example dataset (matches its cached answers)."""
    return [Query(text=e["query"], category=e["category"], price_tier=e["price_tier"], occasion=e["occasion"])
            for e in json.loads(SAMPLE.read_text(encoding="utf-8"))]
