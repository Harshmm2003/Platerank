# PlateRank AI — project guide for Claude Code

AI Search Optimization (AISO) agent for ONE independent restaurant, built for the
NYU SPS x Pulse Foundry hackathon (Oct 23, 2026). Customers ask Claude/ChatGPT/Gemini
where to eat; PlateRank measures how often a restaurant is recommended, explains why
competitors win, generates fixes, and re-tests over time.
Status of every phase + the to-do list: see HANDOFF.md.

## Run it
- `python -m streamlit run app.py` (the bare `streamlit` command may not be on PATH).
- Python 3.11+. `pip install -r requirements.txt`.
- Keys live in `.env` (copy `.env.example`). Never print, log or commit a key; check only that it exists.
- Offline checks (no API calls, run from the repo root):
  `python tests/module_checks.py` and `python tests/discovery_checks.py`. Keep them passing; add checks for new features.

## Pipeline (do not change the order or rename modules)
Setup -> Discovery -> Analysis -> 3 Action tracks (Fix Pack / Creators / Value-for-Money) -> owner approval -> Measurement.

| Module | Stage | Job |
|---|---|---|
| `queries.py` | Discovery | ~30 questions built from the profile (cuisine, area, neighbourhood, city, landmarks, price level, signature terms), tagged category x price tier x occasion |
| `discovery.py` | Discovery | Calls Gemini/Claude, retries + backup model, quota handling, answer cache, multi-run, name matching (aliases), competitor auto-suggest |
| `analysis.py` | Analysis | Deterministic scorecard (mention rate, avg rank, share of voice, slices), "who AI recommends instead" extractor |
| `scrape.py` | Analysis | Website audit (schema, PDF menus via the Menu link, FAQ, dietary tags), menu reading from photo/PDF/link with Gemini |
| `sources_audit.py` | Analysis | Listings/mentions per restaurant -> prioritized gaps, each routed to `standard` / `creator` / `vfm` |
| `reviews_vfm.py` | Analysis + Action C | Aspect sentiment over REAL review text, VfM index, area price benchmark from competitor menus, price position scenarios |
| `creators.py` | Action B | Creator scoring (niche fit, locality, engagement, platform citation value, tier), content briefs, outreach drafts |
| `content_gen.py` | Action A | FAQ page, schema.org markup, outreach email — facts only, unknowns become `[OWNER TO CONFIRM: ...]` |
| `store.py` | Setup + Measurement | Restaurant profiles in `data/live/<slug>/`, SQLite `data/runs.db` (runs + every answer row) |
| `app.py` | UI | Sidebar setup form, `0 · Setup` panel (Competitors / Menu prices / Listings / Reviews), 5 tabs |

Data contracts: Discovery's log rows are the only input Analysis trusts; Analysis's routed gap list is the only
input Action trusts. Every score is deterministic code — LLMs only answer the customer questions, read menus,
suggest competitors and draft text.

## Data layout
- `data/` (flat files) = the SAMPLE example dataset (fictional Greenwich Kitchen). Always labelled SAMPLE/DEMO in the UI.
- `data/live/<slug>/` = one real restaurant: `profile.json`, `answers.json` (cached live AI answers),
  `sources.json` (listings/mentions), `reviews.json` (real reviews). Same JSON shapes as the sample files.
- `data/live/creators_live.json` = real, verified creator finds (same record format as `data/creators_demo.json`).
- Answer status labels: LIVE (fetched now), CACHED (saved real answer), DEMO (sample), FAILED (no answer — excluded from all numbers).

## Non-negotiable rules
1. Never fabricate data: no invented reviews, ratings, creators, prices, competitors or AI answers. Unknown = say unknown / leave blank / ask.
2. Sample data is labelled SAMPLE on screen. Live vs cached vs demo is always visible.
3. A failed live call is shown as FAILED, never silently replaced.
4. The owner approves every draft; nothing is published or sent automatically.
5. Price outputs are a position + a test plan, never a sales prediction.
6. Don't claim a same-day ranking improvement — measurement is directional; the claim is the repeated re-test loop.
7. Instagram is reach, not AI citation; YouTube, listicles, Reddit and reviews are the AI-cited surfaces.
8. Never certify a dish as safe for an allergy.
9. Ask the user before: installs, paid API usage, deleting data, git commits/pushes.
10. Speak plainly to the user (they are new to Claude Code); short summaries.

## Gotchas
- Gemini FREE tier = 20 requests/day PER MODEL (`gemini-3.6-flash`, `gemini-3.5-flash`, ...). A full Discovery
  run is 90 calls (30 questions x 3 runs). Free-tier keys also have NO Google Search grounding.
- `GEMINI_MODEL` / `CLAUDE_MODEL` in `.env` override the defaults (`gemini-3.6-flash`, `claude-opus-5-5`).
- Before writing or changing Claude API code, load the `claude-api` skill (current model IDs and API shapes).
- Streamlit widgets inside `st.form` only commit on submit; `st.data_editor` cells commit on Enter / leaving the cell.
- Inline Python heredocs with long f-strings break in Git Bash on Windows — write a .py file and run it.
