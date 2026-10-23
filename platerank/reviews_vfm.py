"""3. ACTION 2 - Google Reviews Value-for-Money engine.

Core insight (Harsh, Oct 22): customers judge a restaurant on FOOD quality
for the price, AMBIENCE, and BUDGET-FIT. So don't just count stars -
run aspect-based sentiment analysis (ABSA) over Google review text for
food / price-value / ambience / service / portion / wait, benchmark the
target against competitors and area prices, and turn the gaps into
business decisions, each backed by quoted review evidence.

Data in: REAL review text the owner exports/pastes (rating + text), one JSON
file per restaurant folder data/live/<restaurant>/reviews.json, same format as
the SAMPLE file data/reviews_demo.json. Menu prices come from the profile;
the area benchmark is computed from competitor menus (area_benchmark) and
always shown with its sample size - never a hardcoded number.
Honesty rules baked into the code:
- A price scenario is a POSITION vs the area benchmark, never a sales
  prediction. Review data has no sales/elasticity signal, so the engine
  says 'friction' or 'justified premium' - it never says 'cut to $30 and
  you will sell X more'.
- Every recommendation must carry evidence counts + an example quote.
"""
import json, re
from pathlib import Path
from collections import defaultdict

DEMO = Path(__file__).parent.parent / "data" / "reviews_demo.json"

ASPECT_KEYWORDS = {
    "food": ["food", "dish", "bowl", "salad", "taste", "tasty", "flavor", "fresh", "delicious", "bland", "chicken", "pasta", "coffee", "latte", "menu",
             "fish", "roll", "sushi", "rice", "noodle", "meat", "dessert", "omakase", "sashimi"],
    "price_value": ["price", "pricey", "expensive", "cheap", "affordable", "worth", "value", "overpriced", "budget", "$"],
    "ambience": ["ambience", "ambiance", "vibe", "cozy", "loud", "noise", "music", "lighting", "seat", "seating", "cramped", "decor", "atmosphere", "cute"],
    "service": ["staff", "service", "rude", "friendly", "waiter", "server", "attentive", "slow service"],
    "portion_wait": ["portion", "small portion", "generous", "wait", "line", "queue", "slow", "quick", "fast"],
}
# common dish words across cuisines - reviews name dishes far more often than they say "food"
COMMON_DISH_WORDS = ["gyro", "souvlaki", "falafel", "hummus", "pita", "kebab", "shawarma", "moussaka", "spanakopita", "baklava",
                     "taco", "burrito", "quesadilla", "enchilada", "sushi", "ramen", "udon", "pho", "dumpling", "bao", "pizza",
                     "pasta", "lasagna", "risotto", "burger", "fries", "sandwich", "steak", "curry", "biryani", "naan", "tikka",
                     "pad thai", "noodles", "bbq", "wings", "brunch", "breakfast", "lunch", "dinner", "appetizer", "entree", "soup"]
ASPECT_KEYWORDS["food"] = ASPECT_KEYWORDS["food"] + [w for w in COMMON_DISH_WORDS if w not in ASPECT_KEYWORDS["food"]]


def food_words(profile: dict | None) -> list[str]:
    """The restaurant's own words for its food: signature dishes, cuisine, cuisine alternates (lowercase)."""
    if not profile:
        return []
    terms = [profile.get("cuisine") or ""] + list(profile.get("cuisine_alternates") or []) + list(profile.get("signature_terms") or [])
    out = []
    for t in terms:
        t = t.strip().lower()
        if t:
            out.append(t)
            out += [w for w in re.findall(r"[a-z\u00e0-\u00ff]{4,}", t) if w not in ("with", "from", "house", "special", "style")]
    return sorted(set(out))


POS = ["good", "great", "amazing", "delicious", "fresh", "tasty", "love", "best", "worth", "affordable", "cozy", "friendly", "perfect", "generous", "excellent"]
NEG = ["bad", "bland", "expensive", "overpriced", "pricey", "loud", "cramped", "rude", "slow", "dirty", "disappointing", "not worth", "too much", "small"]

def _has_kw(text: str, kw: str) -> bool:
    """Keyword at the START of a word ('seat' hits 'seating', 'rice' doesn't hit 'price')."""
    return (kw in text) if not kw[0].isalnum() else re.search(r"\b" + re.escape(kw), text) is not None

def _sentiment(sentence: str, rating: int) -> int:
    s = sentence.lower()
    score = sum(1 for w in POS if w in s) - sum(1 for w in NEG if w in s)
    if score == 0:
        score = 1 if rating >= 4 else (-1 if rating <= 2 else 0)
    return score

def aspect_analysis(reviews: list[dict], extra_food_words: list[str] | None = None) -> dict:
    """reviews: [{rating:int, text:str}] -> per-aspect mentions, pos/neg, example quotes.
    extra_food_words: the restaurant's own dish / cuisine words (food_words(profile))."""
    keywords = {**ASPECT_KEYWORDS, "food": ASPECT_KEYWORDS["food"] + [w for w in extra_food_words or [] if w not in ASPECT_KEYWORDS["food"]]}
    out = {a: {"mentions": 0, "positive": 0, "negative": 0, "pos_quotes": [], "neg_quotes": []}
           for a in ASPECT_KEYWORDS}
    for r in reviews:
        for sent in re.split(r"[.!?]", r.get("text", "")):
            sent = sent.strip()
            if not sent:
                continue
            low = sent.lower()
            for aspect, kws in keywords.items():
                if any(_has_kw(low, k) for k in kws):
                    o = out[aspect]
                    o["mentions"] += 1
                    sc = _sentiment(sent, int(r.get("rating", 3)))
                    if sc > 0:
                        o["positive"] += 1
                        if len(o["pos_quotes"]) < 2: o["pos_quotes"].append(sent)
                    elif sc < 0:
                        o["negative"] += 1
                        if len(o["neg_quotes"]) < 2: o["neg_quotes"].append(sent)
    for o in out.values():
        tot = o["positive"] + o["negative"]
        o["pos_ratio"] = round(o["positive"] / tot, 2) if tot else None
    return out

def area_benchmark(competitor_menus: dict) -> dict:
    """Area price benchmark = plain average over the competitor menus we hold
    prices for. Always returns the sample size + names so the UI can state them."""
    def avg(key):
        vals = {n: float(m[key]) for n, m in competitor_menus.items() if m.get(key)}
        return (round(sum(vals.values()) / len(vals), 2) if vals else None), sorted(vals)
    entree, entree_from = avg("entree_price")
    anchor, anchor_from = avg("anchor_price")
    return {"entree_avg": entree, "entree_n": len(entree_from), "entree_from": entree_from,
            "anchor_avg": anchor, "anchor_n": len(anchor_from), "anchor_from": anchor_from,
            "sources": sorted({m.get("source", "") for m in competitor_menus.values()} - {""})}

def benchmark_label(bench: dict, key: str = "entree") -> str:
    n, names = bench.get(f"{key}_n", 0), bench.get(f"{key}_from", [])
    if not n:
        return "no competitor menu prices yet"
    return f"average of {n} competitor menu{'s' if n != 1 else ''} ({', '.join(names)})"

def value_for_money_index(aspects: dict, avg_rating: float, price_level: int | None,
                          area_price_level: float | None = None) -> dict:
    """Transparent, explainable index (0-100), NOT a black box:
    food sentiment 40%, price-value sentiment 35%, rating 25%,
    then a premium penalty if priced above the area (competitors' average
    Google price level) with weak price sentiment. Unknown area level = no penalty."""
    food = aspects.get("food", {}).get("pos_ratio") or 0.5
    price = aspects.get("price_value", {}).get("pos_ratio")
    price = 0.5 if price is None else price
    idx = 100 * (0.40 * food + 0.35 * price + 0.25 * (avg_rating / 5))
    penalty = 0
    above = price_level is not None and area_price_level is not None and price_level > area_price_level
    if above and price < 0.5:
        penalty = round(10 * (price_level - area_price_level), 1)
    if price_level is None or area_price_level is None:
        verdict = "Area price level unknown - add Google price levels for the restaurant and its competitors"
    elif above:
        verdict = ("Premium is JUSTIFIED - food sentiment carries the price" if price >= 0.5
                   else "PRICE IS THE FRICTION - food is liked, price is not")
    else:
        verdict = "Priced in line with the area"
    return {"vfm_index": round(idx - penalty, 1), "food_sentiment": food,
            "price_sentiment": price, "rating_component": round(avg_rating / 5, 2),
            "premium_penalty": penalty, "area_price_level": area_price_level, "verdict": verdict}

def cheap_eats_eligibility(aspects: dict, menu: dict, benchmark: dict,
                           cheap_mention_rate: float) -> dict:
    """Does this restaurant honestly belong in cheap-eats / value AI answers?
    Checks Discovery (cheap-query mention rate) + review price sentiment +
    hero-dish price vs the area benchmark."""
    hero, bench = menu.get("hero_dish_price"), benchmark.get("entree_avg")
    price_sent = aspects.get("price_value", {}).get("pos_ratio")
    base = {"cheap_query_mention_rate": cheap_mention_rate, "hero_dish_price": hero,
            "area_entree_benchmark": bench, "benchmark_basis": benchmark_label(benchmark),
            "review_price_sentiment": price_sent}
    if not hero or not bench:
        return {"qualifies": None, **base,
                "why": "Unknown - needs the hero dish price and at least one competitor menu price."}
    qualifies = bool(hero <= bench * 1.1 and cheap_mention_rate >= 0.2)
    return {"qualifies": qualifies, **base,
            "why": ("Price, reviews and AI mentions all line up for cheap-eats queries." if qualifies else
                    f"Hero dish ${hero:g} vs area average ${bench:g} ({benchmark_label(benchmark)}); review price "
                    f"sentiment {price_sent}; AI mentions it in {round(cheap_mention_rate*100)}% of cheap-eats "
                    "answers. It does not currently belong in cheap-eats answers - and forcing it would fail. "
                    "Fix the price position on ONE value hero dish first, then earn the mentions.")}

def price_scenario(item: str, current: float, proposed: float, area_avg: float) -> dict:
    """Position math only - explicitly not a sales forecast."""
    return {"item": item, "current": current, "proposed": proposed, "area_average": area_avg,
            "current_premium_pct": round((current / area_avg - 1) * 100),
            "proposed_premium_pct": round((proposed / area_avg - 1) * 100),
            "note": ("Scenario, not a prediction: reviews tell us whether price is friction, "
                     "they cannot tell us unit sales at a new price. Test with a time-boxed "
                     "special and measure review + mention movement.")}

def recommendations(aspects: dict, vfm: dict, menu: dict, benchmark: dict,
                    anchor_item: str = "everyday item") -> list[dict]:
    recs = []
    amb = aspects.get("ambience", {})
    if amb.get("pos_ratio") is not None and amb["pos_ratio"] < 0.5 and amb["mentions"] >= 3:
        cues = " ".join(amb["neg_quotes"]).lower()
        fixes = []
        if "loud" in cues or "noise" in cues: fixes.append("lower music volume at peak times + add soft surfaces/acoustic panels")
        if "cramped" in cues or "seat" in cues: fixes.append("re-space tables, add comfortable seating for guests who stay longer")
        if "lighting" in cues or "dark" in cues: fixes.append("warmer mood lighting")
        recs.append({"area": "Ambience", "evidence": f"{amb['negative']} negative vs {amb['positive']} positive ambience mentions",
                     "example_quote": amb["neg_quotes"][0] if amb["neg_quotes"] else "",
                     "recommendation": "; ".join(fixes) or "audit music, lighting and seating against the quoted complaints"})
    pv = aspects.get("price_value", {})
    anchor, anchor_avg = menu.get("anchor_price"), benchmark.get("anchor_avg")
    if anchor and anchor_avg and anchor > anchor_avg * 1.2:
        recs.append({"area": "Price anchor item",
                     "evidence": f"{anchor_item.capitalize()} at ${anchor:g} vs area average ${anchor_avg:g} "
                                 f"({benchmark_label(benchmark, 'anchor')}); price sentiment {pv.get('pos_ratio')}",
                     "example_quote": pv["neg_quotes"][0] if pv.get("neg_quotes") else "",
                     "recommendation": f"Baseline the {anchor_item} to ~${anchor_avg:g}. A cheap everyday item is the price "
                                       "customers remember, and value/'cheap eats' answers lean on it. Keep premium "
                                       "pricing on signature dishes if food sentiment supports it."})
    svc = aspects.get("service", {})
    if svc.get("pos_ratio") is not None and svc["pos_ratio"] < 0.5 and svc["mentions"] >= 3:
        recs.append({"area": "Service / staff",
                     "evidence": f"{svc['negative']} negative vs {svc['positive']} positive service mentions",
                     "example_quote": svc["neg_quotes"][0] if svc["neg_quotes"] else "",
                     "recommendation": "Staff/service is a named gap: peak-time staffing + a service-recovery script; then a review-generation push once fixed, so new reviews dilute the old signal AI reads."})
    if vfm["verdict"].startswith("PRICE IS THE FRICTION"):
        hero, bench = menu.get("hero_dish_price"), benchmark.get("entree_avg")
        if hero and bench:
            recs.append({"area": "Hero dish price position",
                         "evidence": f"Food sentiment {vfm['food_sentiment']} (liked) but price sentiment {vfm['price_sentiment']} "
                                     f"(not liked); hero dish ${hero:g} vs area ${bench:g} ({benchmark_label(benchmark)})",
                         "example_quote": pv["neg_quotes"][0] if pv.get("neg_quotes") else "",
                         "recommendation": f"Don't cut everything. Create ONE value hero dish at ~${bench:g} (e.g. a weekday "
                                           "lunch set) to earn cheap-eats/value eligibility, and hold price on the dishes reviews praise."})
    return recs

def load_demo() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))

def load_reviews(path: Path) -> dict | None:
    """Real reviews for one restaurant folder; None until the owner adds them."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None

def analyse_restaurant(name: str, data: dict, menu: dict, benchmark: dict, cheap_mention_rate: float = 0.0,
                       area_price_level: float | None = None, anchor_item: str = "everyday item",
                       food_words: list[str] | None = None) -> dict:
    aspects = aspect_analysis(data["reviews"], food_words)
    vfm = value_for_money_index(aspects, data["avg_rating"], data.get("price_level"), area_price_level)
    return {"restaurant": name, "avg_rating": data["avg_rating"], "review_count": data["review_count"],
            "reviews_analysed": len(data["reviews"]), "price_level": data.get("price_level"),
            "aspects": aspects, "vfm": vfm,
            "cheap_eats": cheap_eats_eligibility(aspects, menu, benchmark, cheap_mention_rate),
            "recommendations": recommendations(aspects, vfm, menu, benchmark, anchor_item)}

def save_reviews(path: Path, data: dict):
    """Owner-pasted REAL reviews for one live restaurant folder (same format as the SAMPLE file)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
