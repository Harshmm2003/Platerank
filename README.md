# PlateRank AI — AISO Agent for Restaurants

**Problem:** Customers ask Claude/ChatGPT/Gemini where to eat. Restaurants invisible in those answers lose the customer before Google even matters. Owners have no way to see their AI ranking, know why competitors win, fix it, or prove improvement.

**Product:** Give it a restaurant name + website. It runs Discovery → Analysis → Action → Measurement in a loop.

## Architecture (4 modules = 4 judging stages)
```
queries.py     -> 20-40 varied customer queries (intent/cuisine/price/occasion)
discovery.py   -> run queries on Claude / Gemini (or demo cache), log mention + rank
scrape.py      -> audit target vs competitor sites: JSON-LD schema, menu PDF?, FAQ?, dietary tags
analysis.py    -> deterministic scorecard: mention rate, avg rank, share of voice, by category
content_gen.py -> FAQ page, schema markup, outreach email (drafts, owner approves)
store.py       -> SQLite: every run saved, before/after trend in the dashboard
app.py         -> Streamlit UI tying it together
```

## Run it
```bash
cd platerank
pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY / GOOGLE_API_KEY, or leave blank for demo mode
streamlit run app.py
```
Demo mode works fully offline with `data/sample_run.json` (Greenwich Kitchen sample from the brief).

## Team split (4 people)
1. Discovery — queries.py + discovery.py (API calls, mention parsing)
2. Analysis — scrape.py + analysis.py (audits, scorecard)
3. Action — content_gen.py (artifacts + approval flow)
4. UI/Demo — app.py + measurement chart + 3-min pitch

## Build order on Friday
1. Demo mode end-to-end first (scorecard on screen by ~11am)
2. Swap demo → one real platform (Claude) for one real restaurant
3. Live site audit for target + top competitor
4. Content generation + approve button
5. Re-run + chart. Freeze features by 5pm, rehearse demo twice.

## Honesty rules for the demo
- Label demo/cached vs live platform results.
- Don't claim ChatGPT/Perplexity if you didn't query them — say how it generalizes.
- A same-day re-run won't shift real model answers; sell the scheduled loop + baseline.
