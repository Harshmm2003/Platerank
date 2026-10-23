# PlateRank AI — AISO agent for one restaurant

Built for the NYU SPS × Pulse Foundry hackathon (Oct 23, 2026). Live case: **Café Athena**, Greek & Mediterranean,
1846 Garnet Ave, Pacific Beach, San Diego (open since 1990).

**Problem.** Diners now ask AI assistants where to eat. A restaurant AI doesn't name loses the customer before a
search page is ever opened, and owners can't see their AI ranking, why competitors win, or whether a fix worked.

**What PlateRank does.** It asks AI the questions customers ask, measures who gets recommended, explains why with
source links, drafts the fixes (the owner approves every one), and re-checks over time.

## Café Athena, live (one check of 36 questions, Claude + web search, Oct 23)
| | Mentioned in AI answers |
|---|---|
| **Café Athena** | **83%** (average position 1.2) |
| Spitz - Pacific Beach | 56% |
| Slowly Restaurant & Lounge | 17% |
| Mr Shawarma | 11% |
| Shawarma Shack | 6% |

**The gap:** AI names Café Athena **0%** of the time for *happy hour* and *drinks*, even though it runs a daily 3–6pm
happy hour and a full bar with Greek-mythology cocktails. Its website never says so where AI looks (no FAQ; the
title and description never mention happy hour or cocktails), and none of the 10 verified reviews mention the bar.
One run is directional - AI answers vary, which is why the re-check exists.

## The 7 tabs
1. **Where you rank** - mention rate, average position, share of voice vs competitors, results per question type.
   Every AI answer is kept with its source links.
2. **Housekeeping** - reads the real website (homepage, robots.txt, llms.txt) and drafts the fixes: a visible FAQ,
   title + meta description, robots.txt for AI search bots, schema (JSON-LD), llms.txt, About us, landing page.
   Each shows *Now (with link) → Proposed → Why → Evidence strength*. Written by code from confirmed facts only.
3. **Social media** - real local creators found by web search; only verified profiles are scored, each with a
   content brief and an outreach draft.
4. **Business value** - food, service, ambience and value from verified review quotes; complaints first, then
   "Gap: never mentioned" actions (e.g. 0 of 10 reviews mention drinks). No menu price-change advice.
5. **Data farming** - Reddit: finds subreddits and threads, drafts posts in the owner's voice; the owner posts them
   via a prefilled link. **Two-agent review:** a Promoter and a Skeptic debate each draft against 7 rules
   (owner disclosed, facts true, no fake reviews, no review incentives, no unprovable "best", fits the community,
   subreddit rules read). Code - not AI - turns their checks into the verdict; the same draft gets the same answer.
6. **Your to-do list** - one ranked list built from every tab.
7. **Did it improve?** - re-run all questions or only chosen question types and compare with the first check.

## Honesty rules (enforced in code and checks)
- **Evidence ledger:** every fact from the internet is *verified* (page read or search citation), *unverified* or
  *rejected*. Only verified items feed scores and drafts.
- Labels everywhere: **LIVE / CACHED / SAMPLE / FAILED** (failed answers are left out of every number).
- No invented reviews, ratings, creators, prices or competitors; unknowns become `[OWNER TO CONFIRM]`.
- Nothing is published or sent automatically. The owner approves, then posts or sends it themselves.
- Never certifies a dish as allergy-safe. No same-day ranking claims.

## Run it (Windows / Mac, Python 3.11+)
```bash
pip install -r requirements.txt
copy .env.example .env        # Mac: cp .env.example .env  - then add ANTHROPIC_API_KEY=... (no quotes)
python check.py               # offline checks, free, ~20 s - all must PASS
python run.py                 # opens http://127.0.0.1:8000
```
No key? The app still runs on saved answers and the SAMPLE restaurant (Greenwich Kitchen, fictional).
`python check.py --live` also tests the real key + web search + web fetch (~$0.02).
`python tools/recheck.py` re-runs the check from the command line (`--categories happy-hour,drinks` for a subset).

## Check a new restaurant
1. Home → **Check a restaurant** → pick the city, type the name (not on the map? **Find it on the web**).
2. Confirm the basics and owner details.
3. Pick competitors within a radius, or **Suggest competitors** (with sources).
4. **Run the check** (the estimate is shown first), then read the 7 tabs.

## How it's built
- **Backend:** FastAPI (`api.py`) over `platerank/` (pipeline, discovery, analysis, evidence, reddit, review_agents,
  aiso, creators, reviews_vfm, content_gen). All Claude calls go through `platerank/llm.py`.
- **Frontend:** React + Vite + Tailwind in `web/`, prebuilt into `web/dist` (running needs only Python).
- **Data:** OpenStreetMap (map search), Claude with web search / web fetch (answers, facts, reviews, creators),
  plain page reads (websites). Per-restaurant data in `data/live/<slug>/`.
- **Tests:** `python check.py` runs every offline check (fake AI and fake web - no paid calls) plus the frontend
  type check. `python tools/install_hooks.py` once per laptop blocks pushes that fail.

## For developers
Architecture and rules: `CLAUDE.md`. Earlier status notes: `HANDOFF.md`. Prompts used with Claude Code: `PROMPTS.md`.
Frontend edits: `cd web && npm install && npm run dev`, then `npm run build` before committing.
