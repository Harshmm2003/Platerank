"""1. DISCOVERY - query bank generation (v3).
The bank builds itself from the restaurant profile (cuisine, area,
neighbourhood, city, landmarks, price level, signature terms), so it works for any
restaurant. Every query carries its dimensions - category x price tier x
occasion - so Analysis can slice visibility; that's where the diagnosis lives.
The Example dataset (SAMPLE) ships its own fixed bank in data/sample_run.json
so its cached answers still line up.
"""
import json
from dataclasses import dataclass
from pathlib import Path

SAMPLE = Path(__file__).parent.parent / "data" / "sample_run.json"

@dataclass
class Query:
    text: str
    category: str          # generic, signature, cheap, value, lunch, date-night, premium, group, dietary, tourist, late-night
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
    seen, out = set(), []
    for t, c, p, o in raw:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(Query(text=t, category=c, price_tier=p, occasion=o))
    return out

def example_queries() -> list[Query]:
    """The fixed bank of the SAMPLE example dataset (matches its cached answers)."""
    return [Query(text=e["query"], category=e["category"], price_tier=e["price_tier"], occasion=e["occasion"])
            for e in json.loads(SAMPLE.read_text(encoding="utf-8"))]
