"""2. ANALYSIS - full source audit + prioritized gaps (v3).
Audits every input type the brief names, for target AND competitors:
website/schema (live, via scrape.py), Google Business Profile, Yelp/TripAdvisor,
press, blog/'best of', Reddit/forum. Listing numbers come from owner-verified
manual entry (copied from public Google/Yelp pages) saved per restaurant in
data/live/<restaurant>/sources.json - same format as the SAMPLE file
data/sources_demo.json. Attribution ("this page caused that answer") is inferred.
"""
import json
from pathlib import Path

DEMO = Path(__file__).parent.parent / "data" / "sources_demo.json"

def load_demo_sources() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))

def load_sources(path: Path) -> dict:
    """Listings/mentions for one live restaurant folder; {} until entered."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}

def audit_sources(target: str, competitors: list[str], data: dict) -> dict:
    """Returns {restaurant: {website: {...}, listings: {...}, mentions: {...}}} for every
    name we hold data for. Website rows are overwritten by the site audit in the app."""
    return {r: json.loads(json.dumps(data[r])) for r in [target] + competitors if r in data}

def prioritized_gaps(audit: dict, target: str, category_rates: dict) -> list[dict]:
    """Concrete, prioritized gaps - never a single score.
    Priority = queries lost in affected categories x severity weight.
    Each gap names its Action: 'standard' (FAQ/schema/menu), 'creator'
    (social/influencer engine), or 'vfm' (reviews value-for-money engine)."""
    t = audit.get(target, {})
    gaps = []
    comps = {k: v for k, v in audit.items() if k != target}
    if not comps:
        return gaps
    top_name = max(comps, key=lambda k: comps[k].get("listings", {}).get("google", {}).get("review_count", 0))
    top = comps[top_name]
    tw, cw = t.get("website", {}), top.get("website", {})
    tg, cg = t.get("listings", {}).get("google", {}), top.get("listings", {}).get("google", {})

    def add(gap, evidence, categories, action, severity=1.0):
        # only categories this query bank actually contains count as lost
        lost = sum(1 - category_rates[c] for c in categories if c in category_rates)
        gaps.append({"gap": gap, "evidence": evidence,
                     "affected_categories": [c for c in categories if c in category_rates] or categories,
                     "action": action, "priority": round(lost * severity, 2)})

    if cg.get("review_count", 0) > 3 * max(tg.get("review_count", 1), 1):
        add(f"Review volume gap vs {top_name}",
            f"{top_name}: {cg.get('review_count')} Google reviews, {cg.get('rating')} stars. "
            f"{target}: {tg.get('review_count')} reviews, {tg.get('rating')} stars. AI trusts volume.",
            ["generic", "healthy", "tourist", "premium"], "vfm", 1.2)
    if cw.get("has_menu_schema") and not tw.get("has_menu_schema"):
        add("No Menu schema", f"{top_name} exposes Menu JSON-LD AI can parse; {target} has none.",
            ["healthy", "dietary", "signature"], "standard", 1.0)
    if tw.get("menu_is_pdf"):
        add("Menu is a PDF", "AI models largely cannot parse a PDF menu; competitor menus are HTML.",
            ["healthy", "dietary", "cheap", "signature"], "standard", 1.1)
    tm, cm = t.get("mentions", {}), top.get("mentions", {})
    if cm.get("best_of_lists", 0) > tm.get("best_of_lists", 0):
        add("Missing from 'best of' listicles",
            f"{top_name} appears in {cm.get('best_of_lists')} best-of lists/blogs; {target} in {tm.get('best_of_lists')}. "
            "Listicles are a top citation source for AI answers - this is a creator/press gap, not a website gap.",
            ["generic", "healthy", "brunch", "date-night", "premium"], "creator", 1.3)
    if cm.get("youtube_mentions", 0) > tm.get("youtube_mentions", 0) or cm.get("reddit_mentions", 0) > tm.get("reddit_mentions", 0):
        add("Invisible on YouTube / Reddit",
            f"YouTube mentions: {target} {tm.get('youtube_mentions', 0)} vs {top_name} {cm.get('youtube_mentions', 0)}; "
            f"Reddit: {tm.get('reddit_mentions', 0)} vs {cm.get('reddit_mentions', 0)}. "
            "YouTube and Reddit are among the most-cited sources in AI answers (research, Oct 2026).",
            ["generic", "cheap", "healthy", "signature"], "creator", 1.3)
    if (tg.get("price_level") or 0) > (cg.get("price_level") or 0):
        add("Priced above the competitor AI recommends",
            f"Google price level: {target} {'$' * (tg.get('price_level') or 0)} vs {top_name} {'$' * (cg.get('price_level') or 0)}. "
            "See the Value-for-Money engine before assuming a price cut - reviews may say the food justifies it, or not.",
            ["cheap", "value", "lunch"], "vfm", 1.2)
    return sorted(gaps, key=lambda g: -g["priority"])

def save_sources(path: Path, data: dict):
    """Owner-entered listings/mentions for one live restaurant folder."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
