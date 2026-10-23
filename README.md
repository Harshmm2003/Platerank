# PlateRank AI — AISO Agent for Restaurants

**Problem:** Customers ask Claude/ChatGPT/Gemini where to eat. Restaurants invisible in those answers lose the customer before Google even matters. Owners have no way to see their AI ranking, know why competitors win, fix it, or prove improvement.

**Product:** Pick a restaurant. PlateRank asks AI the questions customers ask, shows who it recommends instead and why, drafts the fixes (owner approves each), and re-tests over time.

## Run it (Windows / Mac, Python 3.11+)
```bash
pip install -r requirements.txt
copy .env.example .env        # Mac: cp .env.example .env  - then paste ANTHROPIC_API_KEY=sk-ant-... (no quotes)
python check.py               # all checks should pass
python run.py                 # opens http://127.0.0.1:8000
```
No key? The app still runs: open the SAMPLE restaurant, or re-show saved answers.

## Check a NEW restaurant in 5 steps
1. Home -> **Check a restaurant** -> start typing the name, pick it from the dropdown (address, cuisine, website, hours fill in).
2. Check the basics; optionally **Search the web** for price level / rating (with sources). Owner details are optional.
3. Tick competitors from the **radius** list, or **Suggest competitors** (Claude + web search, with sources).
4. **Run the check** (1x for a first look; the cost estimate is shown first).
5. Read the 5 tabs: Where do I rank? · Why are competitors winning? · What should I change? · Make the changes (approve drafts) · Did it improve?

## What is live vs sample
- **LIVE / CACHED**: real AI answers (fetched now / saved earlier). **SAMPLE**: the fictional Greenwich Kitchen example. **FAILED**: no answer - left out of every number.
- Map data: OpenStreetMap. Web facts: Claude web search, always with a link. Reviews: only real ones you paste.

## For developers
- Architecture + rules: `CLAUDE.md`. Status + to-do: `HANDOFF.md`. Prompts for Claude Code: `PROMPTS.md`.
- Before every commit: `python check.py`. Once per laptop: `python tools/install_hooks.py` (blocks pushes that fail checks).
- Frontend: `cd web && npm install && npm run dev` (needs Node.js), then `npm run build` before committing.
