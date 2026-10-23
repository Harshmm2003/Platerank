"""3. ACTION - generate artifacts the owner can actually use.
Template-based so it works offline; swap in Claude/Gemini calls on the day
for richer copy. Every artifact is a DRAFT until the owner clicks Approve.

Honesty rule: drafts are built ONLY from facts we hold (site audit, menu
prices, review analysis). Anything we don't know becomes an
[OWNER TO CONFIRM: ...] placeholder - the agent never invents a claim
(e.g. "quiet and candle-lit") that the reviews may contradict.
"""
import json

SCHEMA_DIETS = {"vegan": "VeganDiet", "gluten-free": "GlutenFreeDiet", "gluten free": "GlutenFreeDiet",
                "vegetarian": "VegetarianDiet", "halal": "HalalDiet", "kosher": "KosherDiet"}

def _confirm(what: str) -> str:
    return f"[OWNER TO CONFIRM: {what}]"

def faq_page(restaurant: str, area: str, facts: dict) -> str:
    """facts: dietary_tags (from the site audit), hero_dish, hero_price, anchor_item +
    anchor_price (from the menu), weak_aspects (review aspects with mostly negative sentiment)."""
    diet = facts.get("dietary_tags") or []
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
         else _confirm("which dishes are vegan / gluten-free / vegetarian (the website lists no dietary tags today)")),
        (f"How much does a meal at {restaurant} cost?", price),
        (f"Where is {restaurant} and when is it open?",
         f"{restaurant} is at {facts['address']}. Hours: {facts.get('hours') or _confirm('opening hours')}."
         if facts.get("address") else _confirm(f"street address near {area} and opening hours")),
        (f"Is {restaurant} good for groups?", _confirm("seating for groups and how long people can stay" + noise_note)),
        (f"Is {restaurant} a good date-night spot?", _confirm("evening hours and atmosphere" + noise_note)),
    ]
    return "\n\n".join(f"Q: {q}\nA: {a}" for q, a in qs)

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
