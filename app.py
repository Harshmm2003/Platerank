"""PlateRank AI - AISO agent for restaurants. Run: python -m streamlit run app.py
Works for ANY restaurant: the sidebar profile (name, website, area, cuisine,
price level, menu prices) and the Setup panel (competitors + their menu prices)
drive every stage. Live data lives in data/live/<restaurant>/. The fictional
Greenwich Kitchen example is a separate dataset, labelled SAMPLE everywhere.
Layout: sidebar setup -> 5 screens (Discovery | Analysis | Creators |
Value-for-Money | Fix Pack + Measurement), as in the team briefing.
"""
import os, time
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from platerank.queries import generate_queries, example_queries
from platerank.discovery import (run_discovery, suggest_competitors, claude_model, gemini_model,
                                 LIVE, CACHED, DEMO, FAILED)
from platerank.analysis import scorecard, by_category, by_dimension, competitor_frequency, ai_recommended
from platerank.scrape import audit_website, diagnose, read_menu_file, fetch_pdf
from platerank.content_gen import faq_page, schema_markup, outreach_email
from platerank.store import (save_run, save_answers, load_runs, list_profiles, load_profile, save_profile,
                             load_example_profile, restaurant_dir)
from platerank.sources_audit import audit_sources, prioritized_gaps, load_demo_sources, load_sources, save_sources
from platerank.reviews_vfm import (load_demo as load_reviews_demo, load_reviews, save_reviews, analyse_restaurant,
                                   area_benchmark, benchmark_label)
from platerank.creators import (load_demo_creators, load_live_creators, match_creators, content_briefs,
                                outreach_draft, local_places)

load_dotenv()
st.set_page_config(page_title="PlateRank AI", layout="wide")
st.title("🍽️ PlateRank AI — get recommended by AI, not just ranked on Google")

LIVE_MODE, EXAMPLE = "Live: my restaurant", "Example: Greenwich Kitchen (SAMPLE data)"
PRICE_LEVELS = ["unknown", "$", "$$", "$$$", "$$$$"]

def approval_gate(key: str, label: str, artifact: str):
    """Owner sign-off for one draft. Approving only records the decision and
    hands the owner the file - PlateRank never publishes or sends anything."""
    approved = st.session_state.setdefault("approved", {})
    if key in approved:
        st.success(f"✅ {label} approved by owner at {approved[key]}. Ready for the owner to publish/send — "
                   "PlateRank does not publish or send anything itself.")
        c1, c2 = st.columns(2)
        c1.download_button("Download approved draft", artifact, file_name=f"{key}.txt", key=f"dl_{key}")
        if c2.button("Undo approval", key=f"undo_{key}"):
            del approved[key]
            st.rerun()
    elif st.button(f"✅ Approve {label}", key=f"approve_{key}"):
        approved[key] = time.strftime("%H:%M")
        st.rerun()

def site_audit(url: str, live: bool, sample: dict | None) -> tuple[dict, str]:
    """Returns (audit, provenance label). Live fetch when asked; the SAMPLE record
    is only a fallback in Example mode, and is labelled as such."""
    if live and url:
        a = audit_website(url)
        if "error" not in a:
            return a, f"LIVE fetch of {url}"
        if sample:
            return sample, f"SAMPLE record (live fetch failed: {a['error'][:80]})"
        return {}, f"Couldn't fetch {url} ({a['error'][:80]})"
    if sample:
        return sample, "SAMPLE record (cached demo data)"
    return {}, "No website on file" if not url else "Not fetched — tick 'Fetch both sites live'"

def avg_price_level(sources: dict, names: list[str]) -> tuple[float | None, int]:
    """Area price level = average Google price level of the competitors we have listings for."""
    lv = [sources[n]["listings"]["google"]["price_level"] for n in names
          if (sources.get(n, {}).get("listings", {}).get("google", {}) or {}).get("price_level")]
    return (round(sum(lv) / len(lv), 2), len(lv)) if lv else (None, 0)

def usd(v) -> str:
    return f"${v:g}" if v else "unknown"

def num(v):
    return None if v is None or pd.isna(v) else float(v)

# ---------------------------------------------------------------- SETUP (sidebar)
with st.sidebar:
    st.header("Setup")
    mode = st.radio("Which data?", [LIVE_MODE, EXAMPLE], key="mode")
    if mode == EXAMPLE:
        profile = load_example_profile()
        st.info("Fictional restaurant from the hackathon brief. Every number in this mode is SAMPLE data.")
        st.caption(f"{profile['name']} · {profile['cuisine']} · near {profile['area']}")
        chosen, runs, reuse = ["demo"], 1, True
    else:
        if "pending_choice" in st.session_state:
            st.session_state["choice"] = st.session_state.pop("pending_choice")
        saved = list_profiles()
        choice = st.selectbox("Restaurant", ["+ New restaurant"] + saved, key="choice")
        base = (load_profile(choice) if choice in saved else None) or {}
        menu0 = base.get("menu", {})
        k = f"p_{choice}_"  # per-restaurant widget keys, so switching restaurants reloads the form
        with st.form(k + "form"):
            f_name = st.text_input("Restaurant name *", base.get("name", ""), key=k + "name")
            f_web = st.text_input("Website", base.get("website", ""), key=k + "web")
            f_cuisine = st.text_input("Cuisine, as customers say it *", base.get("cuisine", ""),
                                      placeholder="e.g. sushi", key=k + "cuisine")
            f_area = st.text_input("Area / landmark customers search by *", base.get("area", ""),
                                   placeholder="e.g. a square, campus or street", key=k + "area")
            f_hood = st.text_input("Neighbourhood", base.get("neighbourhood", ""), key=k + "hood")
            f_city = st.text_input("City", base.get("city", ""), key=k + "city")
            f_marks = st.text_input("Other landmarks people search by (comma-separated)",
                                    ", ".join(base.get("landmarks", [])), placeholder="e.g. a station or venue",
                                    key=k + "marks")
            f_alias = st.text_input("Other names AI might use for you (comma-separated)",
                                    ", ".join(base.get("aliases", [])), placeholder="e.g. a short name",
                                    key=k + "alias")
            f_pl = st.selectbox("Google price level", PRICE_LEVELS, index=base.get("price_level") or 0, key=k + "pl")
            f_sig = st.text_input("Signature dishes / terms (comma-separated)",
                                  ", ".join(base.get("signature_terms", [])), key=k + "sig")
            st.caption("From your own menu (leave blank if unsure):")
            f_hero = st.text_input("Hero dish", menu0.get("hero_dish_name", ""), key=k + "hero")
            f_hero_p = st.number_input("Hero dish price ($)", value=num(menu0.get("hero_dish_price")),
                                       min_value=0.0, step=1.0, key=k + "herop")
            f_anchor = st.text_input("Everyday 'anchor' item", base.get("anchor_item", ""),
                                     placeholder="e.g. miso soup, coffee, a roll", key=k + "anchor")
            f_anchor_p = st.number_input("Anchor item price ($)", value=num(menu0.get("anchor_price")),
                                         min_value=0.0, step=0.5, key=k + "anchorp")
            submitted = st.form_submit_button("💾 Save restaurant")
        if submitted:
            if not (f_name.strip() and f_cuisine.strip() and f_area.strip()):
                st.error("Name, cuisine and area are required.")
            else:
                new = {**base, "name": f_name.strip(), "website": f_web.strip(), "cuisine": f_cuisine.strip(),
                       "area": f_area.strip(), "neighbourhood": f_hood.strip(), "city": f_city.strip(),
                       "landmarks": [m.strip() for m in f_marks.split(",") if m.strip()],
                       "aliases": [a.strip() for a in f_alias.split(",") if a.strip()],
                       "price_level": PRICE_LEVELS.index(f_pl) or None,
                       "signature_terms": [s.strip() for s in f_sig.split(",") if s.strip()],
                       "anchor_item": f_anchor.strip(),
                       "menu": {"hero_dish_name": f_hero.strip(), "hero_dish_price": f_hero_p, "anchor_price": f_anchor_p}}
                new.setdefault("competitors", [])
                new.setdefault("competitor_menus", {})
                save_profile(new)
                st.session_state["pending_choice"] = new["name"]
                st.rerun()
        profile = load_profile(choice) if choice in saved else None
        platforms = (["gemini"] if os.getenv("GOOGLE_API_KEY") else []) + (["claude"] if os.getenv("ANTHROPIC_API_KEY") else [])
        if platforms:
            chosen = st.multiselect("AI platforms", platforms, default=platforms,
                                    help="Only platforms with a key in .env are listed.")
            st.caption(" · ".join(f"{p}: {claude_model() if p == 'claude' else gemini_model()}" for p in chosen))
            runs = st.slider("Runs (AI answers vary, so each question is asked this many times)", 1, 3, 3)
            reuse = st.checkbox("Reuse saved answers (no new API calls for questions already answered)", value=True,
                                help="Untick for a fresh measurement run.")
            st.caption(f"Up to {runs * 30 * len(chosen)} live calls if nothing is saved yet.")
        else:
            chosen = []
            st.warning("No API key in .env — live Discovery is off. Add GOOGLE_API_KEY (free) to run it.")
    ready = bool(profile and profile.get("competitors") and (mode == EXAMPLE or chosen))
    run = st.button("▶ Run Discovery", disabled=not ready)
    if profile and not profile.get("competitors"):
        st.caption("Add at least one competitor in Setup first.")

if profile is None:
    st.info("Fill in your restaurant in the sidebar and press 💾 Save restaurant. "
            "Or pick the Example dataset to see a SAMPLE walkthrough.")
    st.stop()

is_example = mode == EXAMPLE
target, website = profile["name"], profile.get("website", "")
names = [c["name"] for c in profile.get("competitors", [])]
urls = {c["name"]: c.get("website", "") for c in profile.get("competitors", [])}
aliases = {c["name"]: c.get("aliases", []) for c in profile.get("competitors", [])} | {profile["name"]: profile.get("aliases", [])}
rdir = restaurant_dir(target)
anchor_item = profile.get("anchor_item") or "everyday item"
src_data = load_demo_sources() if is_example else load_sources(rdir / "sources.json")
gate = lambda key, label, art: approval_gate(f"{rdir.name}_{key}", label, art)

# ---------------------------------------------------------------- SETUP (competitors, menus, listings, reviews)
if not is_example:
    with st.expander("0 · Setup — competitors, menu prices, listings and reviews", expanded=not names):
        t_comp, t_menu, t_list, t_rev = st.tabs(["Competitors", "Menu prices", "Listings & mentions", "Reviews"])

        with t_comp:
            st.caption("You decide who your competitors are. Suggestions are only added when you pick and confirm them.")
            comp_df = pd.DataFrame([{**c, "aliases": ", ".join(c.get("aliases", []))} for c in profile.get("competitors") or []],
                                   columns=["name", "website", "aliases"])
            st.caption("'aliases' = other ways AI may write the name (e.g. a short name). Short forms like the part "
                       "before ':' are matched automatically.")
            edited = st.data_editor(comp_df, num_rows="dynamic", width="stretch", key=f"comps_{rdir.name}")
            c1, c2 = st.columns(2)
            if c1.button("💾 Save competitors"):
                profile["competitors"] = [{"name": str(r["name"]).strip(), "website": str(r["website"] or "").strip(),
                                           "aliases": [a.strip() for a in str(r.get("aliases") or "").split(",") if a.strip()]}
                                          for r in edited.to_dict("records")
                                          if isinstance(r.get("name"), str) and r["name"].strip()]
                save_profile(profile)
                st.rerun()
            if c2.button("🔎 Auto-suggest competitors", disabled=not os.getenv("GOOGLE_API_KEY")):
                with st.spinner("Asking Gemini for nearby competitors…"):
                    try:
                        st.session_state["suggest"] = {"for": target, **suggest_competitors(profile)}
                    except Exception as e:
                        st.error(f"Couldn't get suggestions right now ({type(e).__name__}). Gemini may be busy or the "
                                 "free daily quota used up — try again later, or type competitors into the table.")
            sug = st.session_state.get("suggest")
            if sug and sug["for"] == target and sug["suggestions"]:
                if sug["grounded"]:
                    st.success("Found with Google Search — check each one before adding.")
                else:
                    st.warning("Google Search isn't included in this API key's plan, so these come from Gemini's own "
                               "knowledge and are NOT web-verified. 'site_responds' shows whether the website loads. "
                               "Check each place before adding it.")
                st.dataframe(pd.DataFrame(sug["suggestions"]), width="stretch")
                picked = st.multiselect("Pick the ones you confirm are real competitors",
                                        [s["name"] for s in sug["suggestions"]], key=f"sug_{rdir.name}")
                if st.button("➕ Add picked competitors", disabled=not picked):
                    have = {n.lower() for n in names}
                    for s in sug["suggestions"]:
                        if s["name"] in picked and s["name"].lower() not in have:
                            profile["competitors"].append({"name": s["name"], "website": s.get("website") or ""})
                    save_profile(profile)
                    st.session_state.pop("suggest")
                    st.rerun()
                if sug["sources"]:
                    st.caption("Search sources Gemini used: " + " · ".join(f"[{s['title']}]({s['url']})" for s in sug["sources"]))

        with t_menu:
            st.caption("Prices for the area benchmark. Compare like with like: pick each competitor's dish that matches "
                       "yours. The benchmark is the plain average of what's filled in and always shows how many menus it used.")
            menus = profile.get("competitor_menus", {})
            mrows = [{"competitor": n, "main_dish_price": menus.get(n, {}).get("entree_price"),
                      "anchor_price": menus.get(n, {}).get("anchor_price"), "source": menus.get(n, {}).get("source", "")}
                     for n in names]
            mdf = st.data_editor(pd.DataFrame(mrows, columns=["competitor", "main_dish_price", "anchor_price", "source"]),
                                 disabled=["competitor"], width="stretch", key=f"menus_{rdir.name}",
                                 column_config={"main_dish_price": st.column_config.NumberColumn("Comparable main dish ($)"),
                                                "anchor_price": st.column_config.NumberColumn(f"Comparable {anchor_item} ($)")})
            if st.button("💾 Save menu prices"):
                profile["competitor_menus"] = {
                    r["competitor"]: {"entree_price": num(r["main_dish_price"]), "anchor_price": num(r["anchor_price"]),
                                      "source": r["source"] if isinstance(r["source"], str) and r["source"] else "entered by owner"}
                    for r in mdf.to_dict("records") if num(r["main_dish_price"]) or num(r["anchor_price"])}
                save_profile(profile)
                st.rerun()
            b = area_benchmark(profile.get("competitor_menus", {}))
            st.caption(f"Area benchmark — main dish: {usd(b['entree_avg'])} ({benchmark_label(b)}) · "
                       f"{anchor_item}: {usd(b['anchor_avg'])} ({benchmark_label(b, 'anchor')})")

            st.markdown("**📷 Read a menu with Gemini** — photo, screenshot (e.g. from Google Maps or an ordering app), "
                        "PDF, or a menu link. You pick the matching dishes; nothing is saved automatically.")
            whose = st.selectbox("Whose menu?", [target] + names, key=f"mwho_{rdir.name}")
            up = st.file_uploader("Upload a menu photo, screenshot or PDF", type=["png", "jpg", "jpeg", "webp", "pdf"],
                                  key=f"mup_{rdir.name}")
            murl = st.text_input("…or paste a menu link (a PDF or a menu web page)", key=f"murl_{rdir.name}")
            if st.button("📖 Read this menu", disabled=not (up or murl.strip()) or not os.getenv("GOOGLE_API_KEY")):
                with st.spinner("Gemini is reading the menu…"):
                    try:
                        if up:
                            data, mime, src = up.getvalue(), up.type or "application/pdf", f"uploaded file '{up.name}'"
                        elif murl.strip().lower().split("?")[0].endswith(".pdf"):
                            data, mime, src = fetch_pdf(murl.strip()), "application/pdf", murl.strip()
                        else:
                            from bs4 import BeautifulSoup
                            import requests
                            html = requests.get(murl.strip(), timeout=15, headers={"User-Agent": "PlateRank-Hackathon/1.0"}).text
                            data = BeautifulSoup(html, "html.parser").get_text("\n", strip=True).encode("utf-8")
                            mime, src = "text/plain", murl.strip()
                        st.session_state["menu_read"] = {"for": target, "whose": whose, "src": src,
                                                         "items": read_menu_file(data, mime)}
                    except Exception as e:
                        st.error(f"Couldn't read that menu ({type(e).__name__}). Try a clearer photo or a screenshot, "
                                 "or type the prices into the table.")
            mr = st.session_state.get("menu_read")
            if mr and mr["for"] == target:
                if not mr["items"]:
                    st.warning("Gemini found no priced items in that menu.")
                else:
                    st.caption(f"{len(mr['items'])} priced items read from {mr['src']} for {mr['whose']} — check them against the menu.")
                    st.dataframe(pd.DataFrame(mr["items"]), width="stretch", height=220)
                    labels = ["(none)"] + [f"{i['name']} — ${i['price']:g}" + (f" ({i['section']})" if i["section"] else "")
                                           for i in mr["items"]]
                    is_me = mr["whose"] == target
                    main_pick = st.selectbox("Dish to use as the comparable MAIN dish" + (" (your hero dish)" if is_me else ""),
                                             labels, key=f"mpick_{rdir.name}")
                    anc_pick = st.selectbox(f"Dish to use as the comparable {anchor_item}", labels, key=f"apick_{rdir.name}")
                    if st.button("💾 Save picked prices", disabled=main_pick == "(none)" and anc_pick == "(none)"):
                        item = lambda lab: mr["items"][labels.index(lab) - 1] if lab != "(none)" else None
                        main_i, anc_i = item(main_pick), item(anc_pick)
                        src = f"read by Gemini from {mr['src']}, picked by owner"
                        if is_me:
                            m = profile.setdefault("menu", {})
                            if main_i:
                                m.update(hero_dish_name=main_i["name"], hero_dish_price=main_i["price"])
                            if anc_i:
                                m["anchor_price"] = anc_i["price"]
                            m["source"] = src
                        else:
                            m = profile.setdefault("competitor_menus", {}).setdefault(mr["whose"], {})
                            if main_i:
                                m["entree_price"] = main_i["price"]
                            if anc_i:
                                m["anchor_price"] = anc_i["price"]
                            m["source"] = src + " (" + ", ".join(i["name"] for i in (main_i, anc_i) if i) + ")"
                        save_profile(profile)
                        st.session_state.pop("menu_read")
                        st.rerun()

        with t_list:
            st.caption("Copy these numbers from the public Google Maps / Yelp pages and from searching best-of lists, "
                       "press, Reddit and YouTube. Leave a cell blank if unknown — blanks are never guessed.")
            cols = ["google_rating", "google_reviews", "google_price_level", "yelp_rating", "yelp_reviews",
                    "best_of_lists", "press_mentions", "reddit_mentions", "youtube_mentions", "source"]
            def lrow(n):
                d = src_data.get(n, {})
                g, y, m = d.get("listings", {}).get("google", {}), d.get("listings", {}).get("yelp", {}), d.get("mentions", {})
                return {"restaurant": n, "google_rating": g.get("rating"), "google_reviews": g.get("review_count"),
                        "google_price_level": g.get("price_level"), "yelp_rating": y.get("rating"),
                        "yelp_reviews": y.get("review_count"), "best_of_lists": m.get("best_of_lists"),
                        "press_mentions": m.get("press_mentions"), "reddit_mentions": m.get("reddit_mentions"),
                        "youtube_mentions": m.get("youtube_mentions"), "source": d.get("source", "")}
            ldf = st.data_editor(pd.DataFrame([lrow(n) for n in [target] + names], columns=["restaurant"] + cols),
                                 disabled=["restaurant"], width="stretch", key=f"list_{rdir.name}",
                                 column_config={"google_price_level": st.column_config.NumberColumn("google_price_level (1-4)", min_value=1, max_value=4)})
            if st.button("💾 Save listings & mentions"):
                out = {}
                for r in ldf.to_dict("records"):
                    v = lambda k: (None if num(r[k]) is None else
                                   num(r[k]) if k.endswith("rating") else int(num(r[k])))  # counts/levels are whole numbers
                    if not any(v(k) is not None for k in cols[:-1]):
                        continue
                    drop = lambda d: {k: x for k, x in d.items() if x is not None}
                    out[r["restaurant"]] = {
                        "listings": {"google": drop({"rating": v("google_rating"), "review_count": v("google_reviews"),
                                                     "price_level": v("google_price_level")}),
                                     "yelp": drop({"rating": v("yelp_rating"), "review_count": v("yelp_reviews")})},
                        "mentions": drop({k: v(k) for k in ("best_of_lists", "press_mentions", "reddit_mentions", "youtube_mentions")}),
                        "source": r["source"] if isinstance(r["source"], str) else ""}
                save_sources(rdir / "sources.json", out)
                st.rerun()

        with t_rev:
            st.caption("REAL reviews only — copy them from Google Maps (or another public review site). "
                       "PlateRank never writes or simulates reviews. One review per line, as:  rating | review text")
            rev_all = load_reviews(rdir / "reviews.json") or {"restaurants": {}}
            have_rev = {n: len(d["reviews"]) for n, d in rev_all["restaurants"].items()}
            st.caption("Saved so far: " + (", ".join(f"{n} ({k} reviews)" for n, k in have_rev.items()) or "none"))
            rwho = st.selectbox("Reviews for", [target] + names, key=f"rwho_{rdir.name}")
            g = src_data.get(rwho, {}).get("listings", {}).get("google", {})
            cur = rev_all["restaurants"].get(rwho, {})
            r1, r2 = st.columns(2)
            avg = r1.number_input("Google average rating", value=num(cur.get("avg_rating") or g.get("rating")),
                                  min_value=1.0, max_value=5.0, step=0.1, key=f"ravg_{rdir.name}_{rwho}")
            tot = r2.number_input("Total reviews on Google", value=num(cur.get("review_count") or g.get("review_count")),
                                  min_value=0.0, step=1.0, key=f"rtot_{rdir.name}_{rwho}")
            pasted = st.text_area("Paste reviews (rating | text, one per line)",
                                  "\n".join(f"{x['rating']} | {x['text']}" for x in cur.get("reviews", [])),
                                  height=200, key=f"rtxt_{rdir.name}_{rwho}")
            rsrc = st.text_input("Where were these copied from? (required)", cur.get("source", ""), key=f"rsrc_{rdir.name}_{rwho}")
            parsed, bad = [], 0
            for line in pasted.splitlines():
                if not line.strip():
                    continue
                left, sep, text = line.partition("|")
                try:
                    rating = int(float(left.strip()))
                    assert sep and 1 <= rating <= 5 and text.strip()
                    parsed.append({"rating": rating, "text": text.strip()})
                except Exception:
                    bad += 1
            st.caption(f"{len(parsed)} reviews read" + (f" · {bad} lines skipped (format must be  rating | text)" if bad else ""))
            if st.button("💾 Save reviews", disabled=not (parsed and avg and rsrc.strip())):
                rev_all["restaurants"][rwho] = {"avg_rating": avg, "review_count": int(tot or len(parsed)),
                                                "price_level": g.get("price_level"), "reviews": parsed,
                                                "source": rsrc.strip()}
                save_reviews(rdir / "reviews.json", rev_all)
                st.rerun()

# ---------------------------------------------------------------- DISCOVERY run
BADGE = {LIVE: "🟢 LIVE", CACHED: "🔵 CACHED", DEMO: "🟡 DEMO", FAILED: "🔴 FAILED"}

if run:
    queries = example_queries() if is_example else generate_queries(profile)
    bar = st.progress(0.0, text="Starting Discovery…")
    all_rows = []
    for platform in chosen:
        def tick(done, total, note, platform=platform):
            bar.progress(done / total, text=f"{platform}: {done}/{total} · {note[:90]}")
        try:
            all_rows += run_discovery(queries, target, names, platform, runs=runs, aliases=aliases,
                                      cache_path=None if is_example else rdir / "answers.json",
                                      use_cache=reuse, progress=tick)
        except Exception as e:  # unexpected (e.g. a bad key): say so plainly, keep what other platforms gave
            st.error(f"{platform} couldn't be used ({type(e).__name__}). Check its key in .env, then try again.")
    bar.empty()
    ok_rows = [r for r in all_rows if r["status"] != FAILED]
    if not ok_rows:
        st.error("No answers came back, so there is nothing to score. The AI service is probably busy or your "
                 "free daily quota is used up — try again in a few minutes. Answers that did arrive were saved.")
        st.stop()
    save_answers(target, all_rows)
    card = scorecard(ok_rows, target, names)
    row = card[card.restaurant == target].iloc[0]
    counts = {s: sum(r["status"] == s for r in all_rows) for s in (LIVE, CACHED, DEMO, FAILED)}
    save_run(target, "+".join(chosen), {"mention_rate": float(row.mention_rate), "mentions": int(row.mentions),
                                       "avg_rank": None if pd.isna(row.avg_rank) else float(row.avg_rank),
                                       "share_of_voice": float(row.share_of_voice), "answers": len(ok_rows),
                                       "runs": runs, **{k.lower(): v for k, v in counts.items()}})
    st.session_state.update(results=all_rows, card=card, run_for=target, run_counts=counts)
    st.session_state.pop("site_audits", None)

if st.session_state.get("run_for") != target or "results" not in st.session_state:
    st.info(f"Press ▶ Run Discovery to test how AI assistants answer {len(example_queries()) if is_example else 30} "
            f"customer questions about {profile['cuisine']} restaurants near {profile['area']}.")
    st.stop()

all_rows, card, counts = st.session_state["results"], st.session_state["card"], st.session_state["run_counts"]
results = [r for r in all_rows if r["status"] != FAILED]  # Analysis never counts failed calls
me = card[card.restaurant == target]
rivals = card[card.restaurant != target]
rival = rivals.iloc[0] if not rivals.empty else None
cats = by_category(results, target)
if counts[DEMO]:
    st.warning(f"🟡 DEMO — {counts[DEMO]} SAMPLE answers from the example dataset, not real AI output.")
else:
    st.success(f"🟢 LIVE results — {counts[LIVE]} answers fetched now, {counts[CACHED]} real answers reused from "
               f"earlier live runs ({', '.join(sorted({r['platform'] for r in results}))}).")
if counts[FAILED]:
    st.warning(f"🔴 {counts[FAILED]} questions got no answer (service busy or quota used up) and are left out of "
               "every number below. Run again later to fill them in — saved answers are reused.")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Mention rate", f"{me.iloc[0].mention_rate:.0%}", help=f"Share of AI answers that name {target}")
m2.metric("Avg rank", me.iloc[0].avg_rank if me.iloc[0].avg_rank is not None else "—",
          help="Position in the answer when mentioned (1 = named first)")
if rival is not None:
    m3.metric(rival.restaurant, f"{rival.mention_rate:.0%}", help="Most-mentioned competitor")
m4.metric("Categories at 0%", f"{(cats.mention_rate == 0).sum()} of {len(cats)}")
runs_seen = max(r["run_id"] for r in results)
st.caption(f"{len(results)} answers scored = {len(results) // max(runs_seen, 1)} questions × {runs_seen} run(s)"
           + (" · SAMPLE answers, not real AI output" if is_example else "")
           + ". Every answer row is logged in data/runs.db.")

tab_disc, tab_anal, tab_creators, tab_vfm, tab_fix = st.tabs(
    ["1 · Discovery", "2 · Analysis", "3 · Creators", "4 · Value-for-Money", "5 · Fix Pack + Measurement"],
    key="screen")  # keyed so a button click doesn't jump back to the first tab

with tab_disc:
    st.subheader("Where do I rank? — visibility scorecard")
    st.dataframe(card, width="stretch")
    st.caption("Mention rate by query category (where are we losing?)")
    st.dataframe(cats, width="stretch")
    with st.expander(f"Raw answers ({len(all_rows)} rows, with their source)"):
        for r in all_rows:
            st.write(f"{BADGE[r['status']]} · {r['platform']} · {r.get('model', '')} · run {r['run_id']} — "
                     f"**{r['query']}** → mentions: {r['ordered_mentions'] or 'none'}")
            st.caption((r.get("note") + " · " if r.get("note") else "") + (r["answer"][:400] or "(no answer)"))
    recs = ai_recommended(results, [target] + names)
    if recs:
        st.markdown("**Who the AI recommends instead** — names pulled from the answers, not on your competitor list")
        st.caption("Read from the answers' formatting, so check each name. These are the places AI actually sends "
                   "your customers to — often better competitors to track than the ones you'd guess.")
        st.dataframe(pd.DataFrame(recs), width="stretch", height=min(400, 38 + 35 * len(recs)))
        if not is_example:
            add = st.multiselect("Add as competitors", [r["restaurant"] for r in recs], key=f"aiadd_{rdir.name}")
            if st.button("➕ Add to my competitors", disabled=not add):
                profile["competitors"] += [{"name": n, "website": ""} for n in add]
                save_profile(profile)
                st.info("Added. Run Discovery again (saved answers are reused, no new calls) to score them.")

with tab_anal:
    st.subheader("Why are competitors beating me? — website audit")
    if rival is None:
        st.info("Add competitors in Setup to compare against.")
        audits = {}
    else:
        top = rival.restaurant
        comp_url = st.text_input(f"Website of top competitor ({top})", urls.get(top, ""), key=f"url_{rdir.name}_{top}")
        live = st.checkbox("Fetch both sites live", value=not is_example,
                           help="Off = cached SAMPLE audit records (Example mode only). Live fetches each site once.")
        if st.button("Audit my site vs top competitor"):
            sample = lambda n: src_data.get(n, {}).get("website") if is_example else None
            st.session_state["site_audits"] = {target: site_audit(website, live, sample(target)),
                                               top: site_audit(comp_url, live, sample(top))}
        audits = st.session_state.get("site_audits", {})
        if target in audits and len(audits) == 2:
            comp_name = next(n for n in audits if n != target)
            (t_audit, t_src), (c_audit, c_src) = audits[target], audits[comp_name]
            st.caption(f"{target}: {t_src} · {comp_name}: {c_src}")
            if not t_audit or not c_audit:
                st.error("Can't compare — one side has no audit data (see the source labels above).")
            else:
                for g in diagnose(t_audit, c_audit, comp_name):
                    st.warning(g)
                with st.expander("Audit details"):
                    st.json({target: t_audit, comp_name: c_audit})

    st.caption("Visibility by price tier (cheap-eats eligibility lives here)")
    st.dataframe(by_dimension(results, target, "price_tier"), width="stretch")
    st.caption("Competitor frequency across all answers")
    st.dataframe(competitor_frequency(results), width="stretch")

    st.subheader("Full source audit + prioritized gaps")
    audit = audit_sources(target, names, src_data)
    for name, (a, _) in audits.items():
        if a:
            audit.setdefault(name, {"listings": {}, "mentions": {}})["website"] = a  # follows the audit above
    if is_example:
        st.caption("Listings, press, Reddit and YouTube counts are SAMPLE records; website rows follow the site audit above.")
    elif not src_data:
        st.caption(f"No listings / press / Reddit / YouTube numbers entered yet for {target}, so the gaps below use the "
                   f"website audit only. They go in data/live/{rdir.name}/sources.json (same format as data/sources_demo.json).")
    st.caption("Each gap names the engine that fixes it: STANDARD → Fix Pack, CREATOR → Creators, VFM → Value-for-Money.")
    cat_rates = {r.category: float(r.mention_rate) for r in cats.itertuples()}
    gaps = prioritized_gaps(audit, target, cat_rates)
    for g in gaps:
        st.warning(f"**[{g['action'].upper()}] {g['gap']}** (priority {g['priority']}) — {g['evidence']}")
    if not gaps:
        st.info("No gaps can be computed yet — run the website audit above and/or add listings data.")
    lost_categories = [c for c, rate in cat_rates.items() if rate < 0.34] or list(cat_rates)[:2]

with tab_creators:
    st.subheader("Creator / influencer engine — relevance where AI looks")
    creator_pool = load_demo_creators() if is_example else load_live_creators()
    if is_example:
        st.caption("SAMPLE creator profiles. YouTube is weighted first: its content is indexed and cited by AI; "
                   "Instagram drives footfall but is rarely cited.")
    st.caption(f"Matched to the categories you're losing: {', '.join(lost_categories)}")
    if not creator_pool:
        st.info("No real creators added yet. Verified finds go in data/live/creators_live.json "
                "(same format as data/creators_demo.json) — that's Phase 5.")
    for c in match_creators(creator_pool, lost_categories, local=local_places(profile)):
        st.write(f"**{c['handle']}** ({c['platform']}, {c['followers']} followers) — relevance {c['relevance_score']}")
        st.caption(c["why"])
        brief = content_briefs(c, profile, lost_categories)[0]
        with st.expander(f"Content brief + outreach — {c['handle']}"):
            st.json(brief)
            draft = st.text_area("Outreach draft", outreach_draft(c, profile, brief), key=f"out_{rdir.name}_{c['handle']}")
            gate(f"outreach_{c['handle'].lstrip('@')}", f"outreach to {c['handle']}", draft)

with tab_vfm:
    st.subheader("Google Reviews — Value-for-Money engine")
    reviews = load_reviews_demo() if is_example else load_reviews(rdir / "reviews.json")
    bench = area_benchmark(profile.get("competitor_menus", {}))
    area_pl, n_pl = avg_price_level(src_data, names)
    st.caption(("SAMPLE reviews and prices. " if is_example else "")
               + f"Area benchmark: main dish {usd(bench['entree_avg'])} "
               f"({benchmark_label(bench)}); area price level {area_pl if area_pl else 'unknown'}"
               + (f" (average Google price level of {n_pl} competitors)" if n_pl else ""))
    tiers = by_dimension(results, target, "price_tier")
    cheap_rate = float(tiers.query("price_tier=='cheap'")["mention_rate"].iloc[0]) if "cheap" in list(tiers["price_tier"]) else 0.0
    target_analysis = None
    if reviews is None:
        st.info(f"No real reviews added for {target} yet. Paste them into data/live/{rdir.name}/reviews.json in the same "
                "format as data/reviews_demo.json (rating + text per review). PlateRank never writes or simulates reviews.")
    else:
        comp_menus = {n: {"hero_dish_price": m.get("entree_price"), "anchor_price": m.get("anchor_price")}
                      for n, m in profile.get("competitor_menus", {}).items()}
        for name, data in reviews["restaurants"].items():
            menu = profile.get("menu", {}) if name == target else comp_menus.get(name, {})
            a = analyse_restaurant(name, data, menu, bench, cheap_rate if name == target else 0.0, area_pl, anchor_item)
            with st.expander(f"{name} — VfM index {a['vfm']['vfm_index']} — {a['vfm']['verdict']}", expanded=(name == target)):
                st.caption(f"{a['reviews_analysed']} review texts analysed (of {a['review_count']} on Google)")
                st.write({k: (v["mentions"], v["pos_ratio"]) for k, v in a["aspects"].items()})
                st.json(a["cheap_eats"])
                for rec in a["recommendations"]:
                    st.info(f"**{rec['area']}** — {rec['recommendation']}\n\nEvidence: {rec['evidence']}\nQuote: “{rec['example_quote']}”")
                if name == target:
                    target_analysis = a
                    if a["recommendations"]:
                        moves = "\n\n".join(f"{r['area']}: {r['recommendation']}\nEvidence: {r['evidence']}"
                                            for r in a["recommendations"])
                        gate("vfm_moves", "these business moves", moves)

with tab_fix:
    st.subheader("What should I change? — fix pack (drafts — the owner approves each one)")
    st.caption("Drafts use only facts we hold: site audit, menu prices and review analysis. "
               "Anything unknown is marked [OWNER TO CONFIRM] rather than invented.")
    t_site = audits.get(target, ({}, ""))[0] or (src_data.get(target, {}).get("website", {}) if is_example else {})
    menu = profile.get("menu", {})
    weak = [k for k, v in (target_analysis or {}).get("aspects", {}).items()
            if v["pos_ratio"] is not None and v["pos_ratio"] < 0.5 and v["mentions"] >= 3]
    facts = {"dietary_tags": t_site.get("dietary_tags_found"), "hero_dish": menu.get("hero_dish_name"),
             "hero_price": menu.get("hero_dish_price"), "anchor_item": profile.get("anchor_item"),
             "anchor_price": menu.get("anchor_price"), "weak_aspects": weak,
             "address": profile.get("address"), "hours": profile.get("hours")}
    faq = st.text_area("FAQ page draft", faq_page(target, profile["area"], facts), height=220, key=f"faq_{rdir.name}")
    gate("faq_page", "FAQ page", faq)
    items = ([{"name": menu["hero_dish_name"], "price": menu["hero_dish_price"]}]
             if menu.get("hero_dish_name") and menu.get("hero_dish_price") else [])
    schema = schema_markup(target, website, items, cuisine=profile.get("cuisine"))
    st.code(schema, language="html")
    gate("schema_markup", "schema markup", schema)
    email = st.text_area("Outreach email draft", outreach_email(profile), height=120, key=f"email_{rdir.name}")
    gate("outreach_email", "outreach email", email)

    st.subheader("Did my visibility improve? — runs over time")
    hist = load_runs(target)
    if hist:
        st.line_chart({"mention_rate": [h["mention_rate"] for h in hist]})
        st.write(hist)
    else:
        st.info("Run Discovery again after fixes to see the before/after trend.")
