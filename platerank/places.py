"""SETUP helpers - find a restaurant and its neighbours without typing everything in.

Data sources (all free, no Google account):
  - OpenStreetMap via Photon (komoot) : type-ahead restaurant search -> dropdown
  - OpenStreetMap via Overpass        : the picked place's public tags (cuisine, website, hours,
                                         address) and same-cuisine restaurants within a radius
  - Claude + web search (optional)    : public facts OSM doesn't hold (Google price level, rating,
                                         review count), each returned WITH its source for the owner to check

Honesty rules: everything here is a SUGGESTION shown with where it came from. Owner-only facts
(hero dish, prices, anchor item) are never filled in here. OSM can be incomplete - if a place is
missing, the owner types it in.
Usage policy: OSM's public servers ask for a real User-Agent and light use - we send one request per
user action and cache nothing on their side.
"""
import json, math, re
from pathlib import Path
import requests

UA = {"User-Agent": "PlateRank-Hackathon/1.0 (NYU SPS x Pulse Foundry prototype)"}
PHOTON = "https://photon.komoot.io/api/"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OVERPASS_TIMEOUT = 15  # seconds per server; the public servers are sometimes slow - fail fast and say so
NEARBY_TIMEOUT = 8     # competitor radius search: give up sooner - the screen falls back to saved results / Claude
FOOD_TAGS = ("restaurant", "fast_food", "cafe", "food_court", "bar", "pub")

# Customer words -> OSM cuisine tag values that count as the same kind of place.
RELATED_CUISINES = {
    "sushi": ["sushi", "japanese"], "japanese": ["japanese", "sushi", "ramen"], "ramen": ["ramen", "japanese", "noodle"],
    "pizza": ["pizza", "italian"], "italian": ["italian", "pizza"], "burger": ["burger", "american"],
    "mexican": ["mexican", "tex-mex", "tacos"], "tacos": ["tacos", "mexican"], "chinese": ["chinese", "dim_sum", "noodle"],
    "indian": ["indian", "nepalese", "pakistani"], "thai": ["thai"], "korean": ["korean"], "vietnamese": ["vietnamese"],
    "healthy": ["salad", "healthy", "vegan", "vegetarian"], "salad": ["salad", "healthy"],
    "coffee": ["coffee_shop", "coffee"], "bakery": ["bakery", "pastry"], "mediterranean": ["mediterranean", "greek", "lebanese", "falafel"],
}


class PlacesError(Exception):
    """Plain-English reason a lookup failed."""


# ---------------------------------------------------------------- cities (fixed list, no typing errors)
CITIES_FILE = Path(__file__).parent / "cities_us.json"
US_STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
             "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
             "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
             "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
             "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
             "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
             "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
             "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
             "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico"}
_cities = None


def cities() -> list[dict]:
    """Every US city/borough with 50,000+ people (GeoNames), biggest first:
    [{id, name, state, lat, lon, population, radius_km}]."""
    global _cities
    if _cities is None:
        raw = json.loads(CITIES_FILE.read_text(encoding="utf-8"))["cities"]
        _cities = [{**c, "id": f"{c['name']}|{c['state']}", "state_name": US_STATES.get(c["state"], c["state"]),
                    # search area grows with the city: ~13 km for 100k people, capped at 40 km (NYC)
                    "radius_km": round(min(40, max(8, 5 + c["population"] ** 0.5 / 40)), 1)} for c in raw]
    return _cities


def city_by_id(city_id: str | None) -> dict | None:
    if not city_id:
        return None
    return next((c for c in cities() if c["id"] == city_id), None)


def _bbox(city: dict) -> str:
    dlat = city["radius_km"] / 111.0
    dlon = city["radius_km"] / (111.0 * max(0.2, math.cos(math.radians(city["lat"]))))
    return f"{city['lon'] - dlon},{city['lat'] - dlat},{city['lon'] + dlon},{city['lat'] + dlat}"


def _distance_m(lat1, lon1, lat2, lon2) -> int:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * r * math.asin(math.sqrt(a)))


def _address(tags: dict) -> str:
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    return ", ".join(x for x in (street, tags.get("addr:city"), tags.get("addr:postcode")) if x)


def cuisine_words(cuisine: str) -> list[str]:
    words = [w for w in re.split(r"[^a-z_]+", (cuisine or "").lower()) if w]
    out = []
    for w in words:
        out += RELATED_CUISINES.get(w, [w])
    return list(dict.fromkeys(out))


def search_restaurants(query: str, lat: float | None = None, lon: float | None = None, limit: int = 8,
                       city: dict | None = None) -> list[dict]:
    """Type-ahead: restaurants whose name matches `query`. With a city (from cities()), only places
    inside that city's area are returned, nearest to its centre first."""
    if len((query or "").strip()) < 2:
        return []
    params = [("q", query.strip()), ("limit", str(limit * 3)), ("lang", "en")]
    params += [("osm_tag", f"amenity:{t}") for t in FOOD_TAGS]
    if city:
        lat, lon = city["lat"], city["lon"]
        params.append(("bbox", _bbox(city)))
    if lat is not None and lon is not None:
        params += [("lat", str(lat)), ("lon", str(lon))]
    try:
        r = requests.get(PHOTON, params=params, headers=UA, timeout=10)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as e:
        raise PlacesError(f"Restaurant search is unavailable right now ({type(e).__name__}). "
                          "You can still type the restaurant in by hand.") from e
    out = []
    for f in feats:
        p, (flon, flat) = f.get("properties", {}), f.get("geometry", {}).get("coordinates", [None, None])
        if not p.get("name") or flat is None:
            continue
        if city and _distance_m(city["lat"], city["lon"], flat, flon) > city["radius_km"] * 1500:
            continue  # outside the chosen city (bbox is a hint to the server; this makes it a rule)
        street = " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
        out.append({"name": p["name"], "osm_type": {"N": "node", "W": "way", "R": "relation"}.get(p.get("osm_type"), "node"),
                    "osm_id": p.get("osm_id"), "kind": p.get("osm_value"),
                    "address": ", ".join(x for x in (street, p.get("district") or p.get("locality"), p.get("city"),
                                                     p.get("postcode")) if x),
                    "city": p.get("city") or "", "neighbourhood": p.get("district") or p.get("locality") or "",
                    "lat": flat, "lon": flon})
    return out[:limit]


def _overpass(query: str, timeout: int = OVERPASS_TIMEOUT) -> list[dict]:
    last = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": query}, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as e:
            last = e
    raise PlacesError("The free map service is busy right now. Try again in a minute - or use "
                      "'Find it on the web' / 'Suggest competitors' (Claude), or type the details in.")


def place_details(osm_type: str, osm_id: int) -> dict:
    """Public OSM tags for one place: cuisine, website, hours, phone, address."""
    els = _overpass(f"[out:json][timeout:20];{osm_type}({int(osm_id)});out tags center;")
    if not els:
        raise PlacesError("That place has no details on OpenStreetMap - fill them in by hand.")
    e = els[0]
    t = e.get("tags", {})
    return {"name": t.get("name", ""), "cuisine": (t.get("cuisine") or "").replace("_", " ").replace(";", ", "),
            "website": t.get("website") or t.get("contact:website") or "", "hours": t.get("opening_hours", ""),
            "phone": t.get("phone") or t.get("contact:phone") or "", "address": _address(t),
            "lat": e.get("lat") or e.get("center", {}).get("lat"), "lon": e.get("lon") or e.get("center", {}).get("lon"),
            "source": f"OpenStreetMap {osm_type}/{osm_id}"}


def nearby_restaurants(lat: float, lon: float, radius_m: int = 800, cuisine: str = "",
                       exclude_name: str = "", limit: int = 25) -> list[dict]:
    """Restaurants within radius_m of (lat, lon), same-cuisine ones first, nearest first."""
    radius_m = max(100, min(int(radius_m), 5000))
    q = (f'[out:json][timeout:25];nwr(around:{radius_m},{lat},{lon})["amenity"~"^({"|".join(FOOD_TAGS[:3])})$"]["name"];'
         "out tags center 200;")
    words = cuisine_words(cuisine)
    out, seen = [], set()
    for e in _overpass(q, timeout=NEARBY_TIMEOUT):
        t = e.get("tags", {})
        name = t.get("name", "").strip()
        if not name or name.lower() in seen or (exclude_name and name.lower() == exclude_name.lower()):
            continue
        seen.add(name.lower())
        elat, elon = e.get("lat") or e.get("center", {}).get("lat"), e.get("lon") or e.get("center", {}).get("lon")
        tag_cuisines = [c.strip().lower() for c in re.split(r"[;,]", t.get("cuisine", "")) if c.strip()]
        same = bool(words) and any(c in words for c in tag_cuisines)
        out.append({"name": name, "cuisine": ", ".join(tag_cuisines).replace("_", " "), "same_cuisine": same,
                    "website": t.get("website") or t.get("contact:website") or "", "address": _address(t),
                    "distance_m": _distance_m(lat, lon, elat, elon) if elat else None,
                    "source": f"OpenStreetMap {e.get('type')}/{e.get('id')}"})
    out.sort(key=lambda x: (not x["same_cuisine"], x["distance_m"] or 10 ** 9))
    return out[:limit]


def geocode(address: str, city: dict | None = None) -> dict | None:
    """Street address -> approximate map point (Photon). Used when a restaurant isn't on the map
    itself, so the radius competitor search still works. Returns {lat, lon, precision} or None."""
    if not (address or "").strip():
        return None
    params = [("q", address), ("limit", "1"), ("lang", "en")]
    if city:
        params += [("lat", str(city["lat"])), ("lon", str(city["lon"])), ("bbox", _bbox(city))]
    try:
        r = requests.get(PHOTON, params=params, headers=UA, timeout=10)
        r.raise_for_status()
        f = (r.json().get("features") or [None])[0]
    except Exception:
        return None
    if not f:
        return None
    lon, lat = f["geometry"]["coordinates"]
    p = f.get("properties", {})
    precise = bool(p.get("housenumber"))
    return {"lat": lat, "lon": lon, "precision": "address" if precise else f"street ({p.get('name', 'street')})"}


def web_lookup(name: str, city: dict) -> dict:
    """For restaurants that aren't on OpenStreetMap: Claude + web search finds the public basics
    (address, neighbourhood, cuisine, website, hours, phone, price level, rating, review count),
    each with the URL it came from, then the address is placed on the map for the radius search.
    Suggestions only - the owner checks them before saving."""
    from . import llm
    where = f"{city['name']}, {city['state_name']}"
    prompt = (f"Find the restaurant called '{name}' in {where}. Search the web (its official website, Google Maps, "
              "Yelp). If several places share the name, choose the one in this city. Reply with ONLY a JSON object "
              "with keys: name (exact business name), address (street, city, state, zip), neighbourhood (as locals "
              "call the area), cuisine (how customers describe it, e.g. 'Greek'), website (official), hours (short), "
              "phone, price_level (1-4 as on Google Maps), google_rating (number), google_review_count (integer), "
              "found (true if you are confident this restaurant exists at that address), sources (object mapping "
              "each non-null key to the URL where you saw it). Use null for anything you could not confirm. Never estimate.")
    r = llm.claude_call(prompt, tools=[llm.web_search_tool(max_uses=4, location=llm.location_for(
        {"city": city["name"], "state": city["state"]}))], max_tokens=4000)
    facts = llm.json_from(r.text or "{}")
    if not isinstance(facts, dict) or not facts.get("found"):
        raise PlacesError(f"Claude couldn't confirm a restaurant called '{name}' in {city['name']}. "
                          "Check the spelling, or type the details in by hand.")
    point = geocode(facts.get("address") or "", city)
    facts.update(_engine=f"Claude ({r.model}) + web search", _cost_usd=r.cost_usd, _point=point)
    return facts


def web_facts(profile: dict) -> dict:
    """Public facts OSM lacks, looked up by Claude with web search: Google price level, Google rating
    and review count, website and hours if missing. Every value comes back with a source URL or as
    null - the owner confirms before anything is saved."""
    from . import llm
    where = profile.get("address") or ", ".join(x for x in (profile.get("area"), profile.get("city")) if x)
    prompt = (f"Find public facts about the restaurant '{profile['name']}' at {where}. Search the web. "
              "Reply with ONLY a JSON object with keys: price_level (1-4 as on Google Maps, or null), "
              "google_rating (number or null), google_review_count (integer or null), website (official, or null), "
              "hours (short text or null), cuisine (how customers would describe it, or null), "
              "sources (object mapping each non-null key to the URL where you saw it). Use null for anything "
              "you could not confirm. Never estimate.")
    r = llm.claude_call(prompt, tools=[llm.web_search_tool(max_uses=3, location=llm.location_for(profile))],
                        max_tokens=4000)
    facts = llm.json_from(r.text or "{}")
    if not isinstance(facts, dict):
        facts = {}
    facts["_engine"] = f"Claude ({r.model}) + web search"
    facts["_cost_usd"] = r.cost_usd
    return facts
