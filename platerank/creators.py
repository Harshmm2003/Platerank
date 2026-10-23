"""3. ACTION 1 - Creator / influencer relevance engine.

Core insight (Harsh, Oct 22): after the standard fixes (PDF, FAQ, menu,
schema), relevance comes from being talked about where AI looks. So the
Analysis data (which query categories are lost, which sources AI cites)
drives a creator strategy: find the local food creators whose content
fills exactly those gaps, score them, and generate the content brief +
outreach for each.

Practicality rules baked in:
- Platform citation value is NOT equal. YouTube content is indexed,
  transcribed and heavily cited by AI assistants; Reddit likewise.
  Instagram Reels drive footfall but sit behind a wall AI rarely cites -
  so the score weights YouTube first for AISO, Instagram for reach.
  (Source: Oct 2026 market research - YouTube/Reddit among top cited
  sources in AI answers; Perplexity's Reddit share ~46.7% of top-10.)
- Realistic tier for one independent: nano/micro LOCAL creators
  (5k-150k), students and neighbourhood food accounts - not celebrities.
  Cost is usually a hosted meal + small fee, not an agency campaign.
- Creators in data/creators_demo.json are SAMPLE profiles for the demo.
  Friday workflow: replace them with real finds from YouTube/Instagram
  search (same fields) and re-run scoring unchanged.
"""
import json
from pathlib import Path

DEMO = Path(__file__).parent.parent / "data" / "creators_demo.json"

# How much a platform's content can actually move AI search (0-1)
PLATFORM_CITATION_VALUE = {"YouTube": 1.0, "TikTok": 0.6, "Instagram": 0.35, "Blog": 0.8}

LIVE = Path(__file__).parent.parent / "data" / "live" / "creators_live.json"

def load_demo_creators() -> list[dict]:
    return json.loads(DEMO.read_text(encoding="utf-8"))

def load_live_creators() -> list[dict]:
    """Real creator finds (same record format as the demo file); [] until added."""
    return json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else []

def local_places(profile: dict) -> set[str]:
    """Place names that count as 'local' for this restaurant (area, neighbourhood, city + its short forms)."""
    city = (profile.get("city") or "").strip()
    short = {"new york": {"NYC", "New York City"}}.get(city.lower(), set())
    return {p.lower() for p in {profile.get("area"), profile.get("neighbourhood"), city, *short} if p}

def score_creator(c: dict, lost_categories: list[str], local: set[str] | None = None) -> dict:
    niche_fit = len(set(c.get("niches", [])) & set(lost_categories)) / max(len(lost_categories), 1)
    locality = 1.0 if (c.get("local_to") or "").lower() in (local or set()) else 0.5
    engagement = min((c.get("engagement_rate", 0) or 0) / 0.08, 1.0)  # 8%+ = excellent for food
    citation = PLATFORM_CITATION_VALUE.get(c.get("platform"), 0.3)
    tier_fit = 1.0 if 5_000 <= c.get("followers", 0) <= 150_000 else 0.5  # micro = affordable + credible
    score = round(100 * (0.30 * niche_fit + 0.20 * locality + 0.20 * citation
                         + 0.15 * engagement + 0.15 * tier_fit), 1)
    return {**c, "relevance_score": score,
            "why": f"niche fit {round(niche_fit,2)} (covers lost categories {list(set(c.get('niches',[])) & set(lost_categories))}), "
                   f"{c.get('platform')} citation value {citation}, local to {c.get('local_to')}, "
                   f"{c.get('followers')} followers (micro tier an independent can actually afford)"}

def match_creators(creators: list[dict], lost_categories: list[str], top_n: int = 5,
                   local: set[str] | None = None) -> list[dict]:
    scored = [score_creator(c, lost_categories, local) for c in creators]
    return sorted(scored, key=lambda x: -x["relevance_score"])[:top_n]

def content_briefs(creator: dict, profile: dict, lost_categories: list[str]) -> list[dict]:
    """Content that creates an INDEXABLE asset, not just a post that vanishes.
    Every brief requires a YouTube/blog companion with the restaurant's facts
    in text - that's the part AI can cite later. The brief targets the lost
    category this creator actually covers."""
    restaurant, cuisine = profile["name"], profile["cuisine"]
    near = f"Near {profile['area']}"
    hood = profile.get("neighbourhood") or profile["area"]
    sig = (profile.get("signature_terms") or [cuisine])[0]
    covered = [c for c in lost_categories if c in creator.get("niches", [])]
    cat = (covered or lost_categories or ["generic"])[0]
    cheap = {"title": f"Cheap {cuisine.title()} {near} — I Tried 5 Spots So You Don't Have To",
             "hook": "First 3 seconds: the hero dish + its price on screen.",
             "format": "YouTube video + Short cut + Instagram Reel version"}
    templates = {
        "cheap": cheap, "value": cheap, "lunch": cheap,
        "healthy": {"title": f"Best Healthy Lunch {near}, Ranked",
                    "hook": "Open on the freshest dish, name the dietary tags out loud (captions = searchable text).",
                    "format": "YouTube video + Short cut + Instagram Reel version"},
        "signature": {"title": f"Best {sig.title()} {near}, Ranked",
                      "hook": f"Close-up of the {sig} in frame one, price on screen.",
                      "format": "YouTube video + Short cut + Instagram Reel version"},
        "date-night": {"title": f"Quiet {cuisine.title()} Date-Night Spots in {hood} That Aren't a Scene",
                       "hook": "Evening ambience shot, no talking for 2 seconds, then the take.",
                       "format": "YouTube video + Instagram Reel version"},
        "premium": {"title": f"Is High-End {cuisine.title()} in {hood} Worth It? I Tried the Top Spots",
                    "hook": "Show the bill total on screen, then the verdict.",
                    "format": "YouTube video + Instagram Reel version"},
        "group": {"title": f"{cuisine.title()} Spots {near} Where a Group Can Actually Sit and Stay",
                  "hook": "Wide shot of the table with the whole group in frame one.",
                  "format": "YouTube Short + Instagram Reel version"},
        "study": {"title": f"Study Spots {near} Where You Can Actually Eat and Stay",
                  "hook": "Show laptop + food + seating in frame one.",
                  "format": "YouTube Short + Instagram Reel version"},
        "dietary": {"title": f"Vegetarian & Gluten-Free {cuisine.title()} {near}: What Actually Works",
                    "hook": "Say the dietary need out loud, then show the dish.",
                    "format": "YouTube video + Short cut"},
        "happy-hour": {"title": f"Best Happy Hours in {hood} for Food, Not Just Drinks",
                       "hook": "Small plates + the happy-hour price list on screen in frame one; say the hours out loud.",
                       "format": "YouTube Short + Instagram Reel version"},
        "drinks": {"title": f"Best Cocktail Spots in {hood} Where the Food Holds Up Too",
                   "hook": "Pour shot of the signature drink, name it on screen, then the dish it pairs with.",
                   "format": "YouTube Short + Instagram Reel version"},
        "events": {"title": f"Where to Host a Party or Rehearsal Dinner {near}: Private Rooms Compared",
                   "hook": "Wide shot of the set-up room, group size + booking basics on screen.",
                   "format": "YouTube video + blog post version"},
    }
    t = templates.get(cat, {"title": f"Hidden {cuisine.title()} Gems in {hood} — {restaurant}",
                            "hook": "Lead with the signature dish.", "format": "YouTube video + Reel version"})
    return [{"creator": creator.get("handle"), "platform": creator.get("platform"), "target_category": cat,
             "concept_title": t["title"], "hook": t["hook"], "format": t["format"],
             "must_include_for_ai_citation": [
                 f"Restaurant name '{restaurant}' spoken AND in on-screen text + caption",
                 "Exact facts in the YouTube description/blog text: address, price of the featured dish, dietary tags, hours",
                 "A ranking/list format — AI answers cite list-structured content far more than single shout-outs",
                 "One honest negative or caveat — review-style credibility is what AI and viewers both trust"],
             "cta": "Pin a comment with the menu link; owner reshares + adds the video link to the Google Business Profile"}]

def outreach_draft(creator: dict, profile: dict, brief: dict) -> str:
    restaurant = profile["name"]
    return (f"Hi {creator.get('name', creator.get('handle'))} — I run {restaurant} near {profile['area']}. "
            f"Your '{creator.get('best_performing_format', 'food videos')}' is exactly what our customers watch. "
            f"We'd love to host you +1 for a meal (no script, honest take only) to film: "
            f"\"{brief['concept_title']}\". We can be flexible this week or next, and we'll reshare "
            f"and link it from our Google profile. Interested? — {restaurant}")
