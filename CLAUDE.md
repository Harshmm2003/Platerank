# PlateRank AI — project guide for Claude Code

AI Search Optimization (AISO) agent for ONE independent restaurant, built for the
NYU SPS x Pulse Foundry hackathon (Oct 23, 2026). Customers ask Claude/ChatGPT/Gemini
where to eat; PlateRank measures how often a restaurant is recommended, explains why
competitors win, generates fixes, and re-tests over time.
Status of every phase + the to-do list: see HANDOFF.md.

## Run it
- **Web app (main):** `python run.py` -> http://127.0.0.1:8000 . Backend = `api.py` (FastAPI), frontend = `web/` (React,
  prebuilt into `web/dist`, so running needs only Python). Old Streamlit UI still works: `python -m streamlit run app.py`.
- Python 3.11+. `pip install -r requirements.txt`. Frontend edits need Node.js: `cd web && npm install` once,
  `npm run dev` (live reload on :5173, talks to `python run.py` on :8000), then `npm run build` before committing.
- Keys live in `.env` (copy `.env.example`), no quotes. Never print, log or commit a key; check only that it exists.
- **Tests - one command:** `python check.py` (free, offline, ~10 s) runs every check file + the frontend type check.
  `python check.py --live` also checks the real Claude key + web search + web fetch (~$0.02).
  `python tools/install_hooks.py` (once per laptop) makes every `git push` run `python check.py` first.
- **Always run `python check.py` and show the result before asking to commit.** Add checks in `tests/` for every
  new feature; checks must never make paid or network calls (fake them - see `tests/api_checks.py`).
- Ready-made prompts for each next phase: `PROMPTS.md`.
- **Standing rule for hackathon day (Oct 23, 2026) only:** after every feature, once `python check.py` passes,
  commit AND push to `origin frontend-v2` without asking. Never push to `main`, never force-push, never commit `.env`.
  Still ask before paid API calls, installs and deleting data. From Oct 24 on, rule 9 applies again in full.

## Pipeline (do not change the order or rename modules)
Setup -> Discovery -> Analysis -> 3 Action tracks (Fix Pack / Creators / Value-for-Money) -> owner approval -> Measurement.

| Module | Stage | Job |
|---|---|---|
| `queries.py` | Discovery | ~30 questions built from the profile (cuisine, area, neighbourhood, city, landmarks, price level, signature terms), tagged category x price tier x occasion |
| `discovery.py` | Discovery | Calls Gemini/Claude, retries + backup model, quota handling, answer cache, multi-run, name matching (aliases), competitor auto-suggest |
| `analysis.py` | Analysis | Deterministic scorecard (mention rate, avg rank, share of voice, slices), "who AI recommends instead" extractor |
| `scrape.py` | Analysis | Website audit (schema, PDF menus via the Menu link, FAQ, dietary tags), menu reading from photo/PDF/link with Claude (Gemini fallback) |
| `sources_audit.py` | Analysis | Listings/mentions per restaurant -> prioritized gaps, each routed to `standard` / `creator` / `vfm` |
| `reviews_vfm.py` | Analysis + Action C | Aspect sentiment over REAL review text, VfM index, area price benchmark from competitor menus, price position scenarios |
| `creators.py` | Action B | Creator scoring (niche fit, locality, engagement, platform citation value, tier), content briefs, outreach drafts; `find_creators` = real creators via Claude web search, checked in the evidence ledger |
| `content_gen.py` | Action A | FAQ page, schema.org markup, outreach email — facts only, unknowns become `[OWNER TO CONFIRM: ...]` |
| `store.py` | Setup + Measurement | Restaurant profiles in `data/live/<slug>/`, SQLite `data/runs.db` (runs + every answer row) |
| `llm.py` | all | The ONE place Claude is called: models, web search / web fetch tools, cost per call, plain-English errors |
| `evidence.py` | all | Evidence ledger: every web-sourced fact/quote is re-fetched from its cited page and marked verified / unverified / rejected |
| `reddit.py` | Action (Data farming) | Reddit agent: verified subreddits + rules + live threads, owner-voiced reply/post drafts; the owner posts (never PlateRank) |
| `review_agents.py` | Action (owner approval) | Promoter vs Skeptic review of post drafts on one code-built context packet; step-0 fact check, verdict + summary computed by code, cached by hash |
| `places.py` | Setup | OpenStreetMap restaurant search (dropdown), place details, radius search for competitors; Claude web facts (price level, rating) with sources |
| `aiso.py` | Action A | AI-readability: reads the real site + robots.txt + llms.txt (free page fetches), then CODE drafts title/meta, visible FAQ, JSON-LD, robots.txt, llms.txt with evidence strength + research notes (`aiso_research.json`). No AI writes markup |
| `pipeline.py` | all | The pipeline as functions for the web app: run Discovery, build the results bundle per owner question, approvals, reviews/listings saving |
| `api.py` | UI backend | FastAPI routes over `pipeline`/`places`; plain-English errors; serves `web/dist` |
| `web/src/` | UI | React: Home, Setup wizard (find restaurant -> competitors in a radius -> run), Results with 5 owner-question tabs |
| `app.py` | UI (fallback) | Old Streamlit screen - keep it working, don't add features here |

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
5. No menu price-change advice (removed Oct 23). Price appears only as review sentiment.
6. Don't claim a same-day ranking improvement — measurement is directional; the claim is the repeated re-test loop.
7. Instagram is reach, not AI citation; YouTube, listicles, Reddit and reviews are the AI-cited surfaces.
8. Never certify a dish as safe for an allergy.
9. Ask the user before: installs, paid API usage, deleting data, git commits/pushes
   (exception on Oct 23, 2026: commits/pushes to `frontend-v2` after a green `python check.py` - see "Run it").
10. Speak plainly to the user (they are new to Claude Code); short summaries.
11. No web-sourced claim reaches the owner unless it is in the evidence ledger (`platerank/evidence.py`,
    `data/live/<slug>/evidence.json`); only verified claims feed scores and drafts. New web features call
    `evidence.record_and_verify()` / `check_facts()` - unverified = greyed "check the link", rejected = counted, never shown as fact.

## Gotchas
- Gemini FREE tier = 20 requests/day PER MODEL (`gemini-3.6-flash`, `gemini-3.5-flash`, ...). A full Discovery
  run is 90 calls (30 questions x 3 runs). Free-tier keys also have NO Google Search grounding.
- `GEMINI_MODEL` / `CLAUDE_MODEL` in `.env` override the defaults (`gemini-3.6-flash`, `claude-opus-5-5`).
- Before writing or changing Claude API code, load the `claude-api` skill (current model IDs and API shapes).
  All Claude calls go through `platerank/llm.py` - don't create a second client elsewhere.
- Claude costs (Oct 2026): web search $10 / 1,000 searches + tokens. Opus 5.5 $4/$20, Sonnet 5.5 $2/$10,
  Haiku 5.5 $0.10/$0.50 per million tokens (in/out). A Discovery question with web search is roughly
  $0.03 (Haiku) - $0.08 (Sonnet) - $0.15 (Opus); 30 questions x runs. Show the estimate and ask before big runs.
- Web search / web fetch must be enabled for the org in the Claude Console, else a 400 (llm.py explains it).
- OpenStreetMap (Photon + Overpass) is free but can be incomplete or busy; every lookup has a type-it-in fallback.
- `data/live/*/last_run.json` and `data/example_state/` are per-machine runtime state (git-ignored).
- Streamlit widgets inside `st.form` only commit on submit; `st.data_editor` cells commit on Enter / leaving the cell.
- Inline Python heredocs with long f-strings break in Git Bash on Windows — write a .py file and run it.
