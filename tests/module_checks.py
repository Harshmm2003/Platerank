"""Offline per-module checks for platerank (Phase 2). Run from the project root. No API calls."""
import sys, tempfile, traceback
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

ok = fail = 0
def check(name, fn):
    global ok, fail
    try:
        print(f"PASS  {name}: {fn()}"); ok += 1
    except Exception as e:
        print(f"FAIL  {name}: {type(e).__name__}: {e}"); traceback.print_exc(limit=3); fail += 1

from platerank import queries, discovery, analysis, scrape, sources_audit, reviews_vfm, creators, content_gen, store

# ---- Example (SAMPLE) dataset, end to end
P = store.load_example_profile(); T = P["name"]; C = [c["name"] for c in P["competitors"]]
qs = queries.example_queries()
res = discovery.run_discovery(qs, T, C, "demo")
card = analysis.scorecard(res, T, C)
check("example: discovery", lambda: f"{len(res)} rows, {sum(not r['answer'] for r in res)} without a cached answer")
check("example: scorecard", lambda: card[card.restaurant == T][["mention_rate", "avg_rank"]].to_dict("records"))
cats = analysis.by_category(res, T).set_index("category").mention_rate.to_dict()
check("example: date-night is 0%", lambda: cats["date-night"] == 0.0 or (_ for _ in ()).throw(AssertionError(cats)))
src = sources_audit.load_demo_sources()
check("example: gaps", lambda: [(g["action"], g["gap"]) for g in sources_audit.prioritized_gaps(sources_audit.audit_sources(T, C, src), T, cats)])
bench = reviews_vfm.area_benchmark(P["competitor_menus"])
check("example: benchmark", lambda: (bench["entree_avg"], reviews_vfm.benchmark_label(bench)))
rv = reviews_vfm.load_demo()
a = reviews_vfm.analyse_restaurant(T, rv["restaurants"][T], P["menu"], bench, 0.43, 1.8, P["anchor_item"])
check("example: VfM", lambda: (a["vfm"]["vfm_index"], a["vfm"]["verdict"], [r["area"] for r in a["recommendations"]]))
cr = creators.match_creators(creators.load_demo_creators(), ["date-night", "brunch"], local=creators.local_places(P))
check("example: creators", lambda: (cr[0]["handle"], cr[0]["relevance_score"], creators.content_briefs(cr[0], P, ["date-night"])[0]["concept_title"]))
check("example: outreach", lambda: creators.outreach_draft(cr[0], P, creators.content_briefs(cr[0], P, ["date-night"])[0])[:70])

# ---- Any restaurant (made-up test profile, never saved)
X = {"name": "Test Sushi Bar", "website": "", "cuisine": "sushi", "area": "Union Square", "neighbourhood": "Gramercy",
     "city": "New York", "price_level": 2, "signature_terms": ["omakase"], "anchor_item": "miso soup",
     "menu": {}, "competitors": [], "competitor_menus": {}}
xq = queries.generate_queries(X)
check("any restaurant: query bank", lambda: f"{len(xq)} queries, categories {sorted({q.category for q in xq})}")
check("any restaurant: no NYU/healthy leftovers", lambda: [q.text for q in xq if any(w in q.text.lower() for w in ("nyu", "healthy", "greenwich"))] or "none")
check("any restaurant: empty benchmark", lambda: reviews_vfm.benchmark_label(reviews_vfm.area_benchmark({})))
check("any restaurant: VfM with unknowns", lambda: reviews_vfm.analyse_restaurant(
    "Test Sushi Bar", {"avg_rating": 4.5, "review_count": 10, "reviews": [{"rating": 5, "text": "Great fish, fair price."}]},
    {}, reviews_vfm.area_benchmark({}))["vfm"]["verdict"])
check("any restaurant: gaps with no data", lambda: sources_audit.prioritized_gaps(sources_audit.audit_sources("Test Sushi Bar", [], {}), "Test Sushi Bar", {}))
check("any restaurant: FAQ + email", lambda: (content_gen.faq_page("Test Sushi Bar", "Union Square", {}).count("OWNER TO CONFIRM"),
                                             content_gen.outreach_email(X).splitlines()[0]))
check("scrape.menu_prices (unreachable)", lambda: scrape.menu_prices("https://does-not-exist.invalid")["note"])
store.DB = Path(tempfile.mkdtemp()) / "runs.db"  # temp DB - never touches data/runs.db
store.save_run(T, "demo", {"mention_rate": 0.17, "mentions": 5})
check("store save/load (temp DB)", lambda: store.load_runs(T)[0]["mention_rate"])
check("store.slugify", lambda: store.slugify("YONO Sushi!"))
check("store.slugify drops accents", lambda: store.slugify("Café Athena") == "cafe_athena" or (_ for _ in ()).throw(AssertionError(store.slugify("Café Athena"))))
print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
