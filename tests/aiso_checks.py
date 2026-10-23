"""Offline checks: AI-readability research + drafts (platerank/aiso.py), no-price-advice, agent review out-of-date.
No network: a fake page fetcher stands in for the website."""
import json, sys, tempfile, traceback
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

ok = fail = 0
def check(name, fn):
    global ok, fail
    try:
        print(f"PASS  {name}: {fn()}"); ok += 1
    except Exception as e:
        print(f"FAIL  {name}: {type(e).__name__}: {e}"); traceback.print_exc(limit=3); fail += 1
def need(cond, msg=""):
    if not cond:
        raise AssertionError(msg)
    return "ok"

from platerank import aiso, evidence, reviews_vfm

HOME = """<html><head><title>Authentic Greek and Mediterranean Food - Cafe Athena</title>
<meta name="description" content="Savor authentic Greek and Mediterranean flavors in Pacific Beach, San Diego!">
<meta property="og:title" content="Authentic Greek and Mediterranean Food - Cafe Athena">
<script type="application/ld+json" class="yoast-schema-graph">{"@context":"https://schema.org","@graph":[{"@type":"WebPage","name":"x"},{"@type":"WebSite","name":"Cafe Athena"},{"@type":"Organization","name":"Cafe Athena"}]}</script>
</head><body><a href="tel:(858) 274-1140">Call</a> <a href="/menu/">Lunch &amp; Dinner Menu</a> <a href="/bar-happy-hour-menu/">Bar &amp; Happy Hour Menu</a>
<a href="#top">menu</a> Happy hour daily 3-6pm.</body></html>"""
ROBOTS = "# START YOAST BLOCK\nUser-agent: *\nCrawl-delay: 10\nDisallow:\n\nSitemap: https://cafeathena.com/sitemap_index.xml\n# END YOAST BLOCK\n"

class Resp:
    def __init__(self, status, text, ctype="text/html"):
        self.status_code, self.text, self.headers = status, text, {"content-type": ctype}

def fake_get(url, **kw):
    if url.endswith("/robots.txt"):
        return Resp(200, ROBOTS, "text/plain")
    if url.endswith("/llms.txt"):
        return Resp(404, "nope")
    if "spitz" in url:
        raise ConnectionError("down")
    return Resp(200, HOME)

PROFILE = {"name": "Café Athena", "website": "https://cafeathena.com/", "cuisine": "Greek", "cuisine_alternates": ["Mediterranean"],
           "area": "Pacific Beach", "neighbourhood": "Pacific Beach", "city": "San Diego", "state": "CA", "city_id": "San Diego|CA",
           "address": "1846 Garnet Ave, San Diego, CA 92109", "hours": "Sun–Thu 11am–9pm, Fri–Sat 11am–9:30pm; happy hour daily 3–6pm",
           "highlights": ["gluten-free", "happy hour", "cocktails", "catering", "vegan", "full bar", "Greek-mythology cocktails"],
           "lat": 32.8, "lon": -117.2, "year_opened": 1990,
           "competitors": [{"name": "Spitz", "website": "https://spitz.example/"}, {"name": "Slowly", "website": ""}]}

tmp = Path(tempfile.mkdtemp())
evidence.ledger_path = lambda slug: tmp / slug / "evidence.json"   # never touches data/live
SLUG = "aiso_test"

# ---- parsing
p = aiso.parse_page(HOME, "https://cafeathena.com/")
check("parse: title + description", lambda: need(p["title"].startswith("Authentic") and "Pacific Beach" in p["description"], p))
check("parse: Yoast @graph types seen", lambda: need(p["yoast_graph"] and "Organization" in p["jsonld_types"], p["jsonld_types"]))
check("parse: phone from tel: link", lambda: need(p["phone"] == "8582741140", p["phone"]))
check("parse: menu links (no #anchors)", lambda: need([m["url"] for m in p["menu_links"]] == ["https://cafeathena.com/menu/", "https://cafeathena.com/bar-happy-hour-menu/"], p["menu_links"]))
r = aiso.parse_robots(ROBOTS)
check("robots: nothing blocked, crawl-delay read", lambda: need(not any(r["blocked"].values()) and r["crawl_delay"] == "10" and not r["names_ai_bots"], r))
r2 = aiso.parse_robots("User-agent: GPTBot\nUser-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
check("robots: grouped agents blocked", lambda: need(r2["blocked"]["OAI-SearchBot"] and r2["blocked"]["GPTBot"] and not r2["blocked"]["ClaudeBot"], r2["blocked"]))

# ---- research + view
data = aiso.research(SLUG, PROFILE, get=fake_get)
v = aiso.view(SLUG, PROFILE, ["happy-hour", "drinks", "cheap"])
items = {i["key"]: i for i in v["items"]}
check("view: 5 drafts, strongest first", lambda: need([i["strength"] for i in v["items"]] == ["Strong", "Mixed", "Mixed", "Weak", "Weak"]
                                                   and v["items"][0]["key"] == "aiso_faq_section", [i["key"] for i in v["items"]]))
check("view: competitor fetch failing -> FAILED, not invented", lambda: need(
    [(c["name"], c["ok"]) for c in v["competitors"]] == [("Spitz", False), ("Slowly", False)] and "Setup" in v["competitors"][1]["error"], v["competitors"]))
check("view: findings recorded in the evidence ledger", lambda: need(any("page title" in x["subject"] for x in evidence.load(SLUG)), "no ledger rows"))
tm = items["aiso_title_meta"]["text"]
title = tm.split("<title>")[1].split("</title>")[0]
desc = tm.split('name="description" content="')[1].split('"')[0]
check("title <= 60 and mentions happy hour", lambda: need(len(title) <= 60 and "Happy Hour" in title, title))
check("description <= 155, facts only", lambda: need(len(desc) <= 155 and "3–6pm" in desc and "1990" in desc, desc))
check("FAQ: losing questions first", lambda: need(items["aiso_faq_section"]["text"].index("happy hour") < items["aiso_faq_section"]["text"].index("hours?"), "order"))
check("FAQ: no allergy promise", lambda: need("safe" not in items["aiso_faq_section"]["text"].lower(), "says safe"))
ld = items["aiso_schema"]
g = json.loads(ld["text"])["@graph"]
check("schema: valid, no problems", lambda: need(ld["problems"] == [], ld["problems"]))
check("schema: phone + menus from the site, no Organization (Yoast has it)", lambda: need(
    g[0]["telephone"] == "(858) 274-1140" and len(g[0]["hasMenu"]) == 2 and all(x["@type"] in ("Restaurant", "FAQPage") for x in g), g[0]))
check("schema: never aggregateRating", lambda: need("aggregateRating" not in ld["text"] and "review" not in ld["text"].lower(), "rating found"))
check("schema: hours exclude happy hour", lambda: need(len(g[0]["openingHoursSpecification"]) >= 2 and
      all(h["opens"] != "15:00" for h in g[0]["openingHoursSpecification"]), g[0]["openingHoursSpecification"]))
f = aiso.facts(PROFILE, data["own"]); f["yoast"] = True
bad = json.loads(ld["text"])
check("validator: bad JSON", lambda: need(aiso.validate_jsonld("{nope", PROFILE, f)[0].startswith("Not valid JSON")))
check("validator: missing field", lambda: need(any("url" in e for e in aiso.validate_jsonld(json.dumps({"@graph": [{**bad["@graph"][0], "url": ""}]}), PROFILE, f))))
check("validator: wrong name", lambda: need(any("doesn't match" in e for e in aiso.validate_jsonld(json.dumps({"@graph": [{**bad["@graph"][0], "name": "Other"}]}), PROFILE, f))))
check("validator: placeholder left", lambda: need(any("placeholder" in e for e in aiso.validate_jsonld(ld["text"].replace('"Greek"', '"[OWNER TO CONFIRM: x]"'), PROFILE, f))))
check("validator: rating refused", lambda: need(any("ratings" in e for e in aiso.validate_jsonld(json.dumps({"@graph": [{**bad["@graph"][0], "aggregateRating": {"ratingValue": 5}}]}), PROFILE, f))))
check("validator: duplicate Organization with Yoast", lambda: need(any("Yoast" in e for e in aiso.validate_jsonld(json.dumps({"@graph": bad["@graph"] + [{"@type": "Organization"}]}), PROFILE, f))))
rb = items["aiso_robots"]["text"]
check("robots snippet: all 6 AI search bots allowed", lambda: need(all(f"User-agent: {b}\nAllow: /" in rb for b in aiso.SEARCH_BOTS), rb))
check("robots snippet: training bots are the owner's choice (commented)", lambda: need("# User-agent: GPTBot" in rb and "\nUser-agent: GPTBot" not in rb))
check("robots: crawl-delay flagged", lambda: need("10 seconds" in items["aiso_robots"]["why"], items["aiso_robots"]["why"]))
check("llms.txt: not found -> says so, file drafted", lambda: need("No llms.txt" in items["aiso_llms"]["before"] and items["aiso_llms"]["text"].startswith("# Café Athena")))
check("every draft cites research or findings", lambda: need(all(i["research"] or i["key"] == "aiso_title_meta" for i in v["items"])))

# ---- site down: no claims about what we couldn't see
def down(url, **kw):
    raise ConnectionError("x")
aiso.research("aiso_down", PROFILE, get=down)
vd = {i["key"]: i for i in aiso.view("aiso_down", PROFILE, ["happy-hour"])["items"]}
check("site down: no claim about robots", lambda: need("couldn't read your robots.txt" in vd["aiso_robots"]["why"], vd["aiso_robots"]["why"]))
check("site down: no claim about title", lambda: need("couldn't read your current title" in vd["aiso_title_meta"]["why"], vd["aiso_title_meta"]["why"]))
check("site down: llms says couldn't check", lambda: need(vd["aiso_llms"]["before"].startswith("Couldn't check"), vd["aiso_llms"]["before"]))
check("not researched yet -> empty view", lambda: need(aiso.view("never", PROFILE, [])["researched"] is False))

# ---- price advice removed
check("no price-change functions left", lambda: need(not hasattr(reviews_vfm, "price_scenario")))
a = reviews_vfm.analyse_restaurant("X", {"avg_rating": 4, "review_count": 6, "reviews": [
    {"rating": 2, "text": "Great food but overpriced and expensive."}] * 6}, {"hero_dish_price": 40, "anchor_price": 9},
    {"entree_avg": 25, "entree_n": 3, "anchor_avg": 5, "anchor_n": 3}, 0.0, None, "coffee")
check("VfM never recommends a price change", lambda: need(not any("price" in r["area"].lower() for r in a["recommendations"]), a["recommendations"]))

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
