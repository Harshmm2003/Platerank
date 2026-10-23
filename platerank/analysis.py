"""2. ANALYSIS - deterministic scorecard + sliced visibility (v2). No LLM vibes."""
import pandas as pd
from collections import Counter

def scorecard(results: list[dict], target: str, competitors: list[str]) -> pd.DataFrame:
    names = [target] + competitors
    denom = len(results) or 1  # = queries x runs, so multi-run rates stay honest
    total_mentions = sum(len(r["ordered_mentions"]) for r in results) or 1
    rows = []
    for n in names:
        hits = [r for r in results if n in r["ordered_mentions"]]
        ranks = [r["ordered_mentions"].index(n) + 1 for r in hits]
        rows.append({"restaurant": n,
                     "mention_rate": round(len(hits) / denom, 2),
                     "mentions": len(hits),
                     "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
                     "share_of_voice": round(len(hits) / total_mentions, 2)})
    return pd.DataFrame(rows).sort_values("mentions", ascending=False)

def by_category(results: list[dict], target: str) -> pd.DataFrame:
    cats = Counter(r["category"] for r in results)
    hits = Counter(r["category"] for r in results if r["mentioned"])
    return pd.DataFrame([{"category": c, "queries": n, "target_mentions": hits.get(c, 0),
                          "mention_rate": round(hits.get(c, 0) / n, 2)} for c, n in cats.items()])

def by_dimension(results: list[dict], target: str, dim: str = "price_tier") -> pd.DataFrame:
    """Slice target visibility by price_tier or occasion - e.g. cheap-tier
    mention rate is the restaurant's 'cheap eats eligibility' in AI answers."""
    groups = Counter(r.get(dim, "any") for r in results)
    hits = Counter(r.get(dim, "any") for r in results if r["mentioned"])
    return pd.DataFrame([{dim: g, "queries": n, "target_mentions": hits.get(g, 0),
                          "mention_rate": round(hits.get(g, 0) / n, 2)} for g, n in groups.items()])

def competitor_frequency(results: list[dict]) -> pd.DataFrame:
    c = Counter()
    for r in results:
        c.update(r["ordered_mentions"])
    total = sum(c.values()) or 1
    return pd.DataFrame([{"restaurant": n, "appearances": k, "share": round(k / total, 2)}
                         for n, k in c.most_common()])

# Labels AI answers put in bold that are not restaurant names.
_NOT_NAMES = {"why go", "the vibe", "the deal", "quick pick", "walk from penn station", "what to order", "best for",
              "price", "price range", "location", "address", "vibe", "must try", "must-try", "tip", "pro tip",
              "note", "why", "highlights", "the order", "what to get", "budget", "honorable mention",
              "local tip", "insider tip", "bonus", "good to know", "the catch", "bottom line", "summary"}

def ai_recommended(results: list[dict], known: list[str]) -> list[dict]:
    """Restaurant names the AI answers actually recommend (bold or numbered list items),
    counted by how many answers name them, minus the target + competitors already known.
    Extracted from answer formatting - a list for the owner to check, not ground truth."""
    import re
    from collections import Counter
    from .discovery import name_variants
    known_low = {v.lower() for n in known for v in name_variants(n)}
    seen = Counter()
    for r in results:
        names = set()
        for m in re.finditer(r"\*\*\s*(?:\d+[.)]\s*)?([^*\n]{2,60}?)\s*\*\*|^\s*\d+[.)]\s+([A-Z][^\n:*]{1,50})", r["answer"], re.M):
            n = re.sub(r"\s*\(.*?\)\s*$", "", (m.group(1) or m.group(2)).strip()).strip(" :-–—.")
            if (not n or n.endswith(":") or ":" in n or n.lower() in _NOT_NAMES or len(n.split()) > 6
                    or not n[0].isupper()):
                continue
            names.add(n)
        for n in names:
            if not any(k == n.lower() or k in n.lower() or n.lower() in k for k in known_low):
                seen[n] += 1
    return [{"restaurant": n, "answers_naming_it": k} for n, k in seen.most_common()]
