# PlateRank AI — handoff (Oct 22, 2026, evening)

Hackathon: NYU SPS x Pulse Foundry, **Friday Oct 23, 2026, 9:00–19:00**. Live demo restaurant: **YONO Sushi
(by BondST), Moynihan Train Hall, 421 8th Ave, NYC**. Goal: a live, general prototype that works for ANY
restaurant typed in — nothing restaurant-specific hardcoded.

---

## 1. Where things stand

### ✅ Done
**Phase 0 — keys.** `.env` with `GOOGLE_API_KEY` (free AI Studio key). No Anthropic key yet (planned — see backlog #1).

**Phase 1 — baseline.** Demo mode runs end to end; offline checks in `tests/`.

**Phase 2 — works for any restaurant.**
- Sidebar: "Live: my restaurant" (saved profiles in `data/live/<slug>/profile.json`) or "Example: Greenwich Kitchen (SAMPLE data)".
- Profile fields: name, website, cuisine, area, neighbourhood, city, other landmarks, aliases, Google price level,
  signature terms, hero dish + price, everyday "anchor" item + price.
- Query bank builds itself from the profile (30 questions, category x price tier x occasion). The example keeps its own fixed bank.
- Competitors: typed in, or 🔎 Auto-suggest (Gemini; falls back to no-search answers labelled NOT web-verified, checks each website loads). Owner picks — nothing added silently.
- Area price benchmark = average of competitor menu prices you hold, always shown with its sample size.
- Every engine (creators, VfM, gaps, FAQ/email) uses the profile; no NYU/Greenwich wording in logic.

**Phase 3 — live Discovery.**
- Gemini and/or Claude (whichever keys exist), 1–3 runs, progress bar.
- Busy (5xx) -> wait + retry -> backup model `gemini-3.5-flash`. Quota (429) -> stop calling, keep what arrived.
- Every live answer cached to `data/live/<slug>/answers.json` immediately; "Reuse saved answers" avoids re-spending.
- Badges: 🟢 LIVE / 🔵 CACHED / 🟡 DEMO / 🔴 FAILED (failed rows excluded from all numbers).
- Every row logged to SQLite `data/runs.db` (`answers` table) + a run summary (`runs` table).
- Name matching: case-insensitive, word-boundary, short names ("KazuNori: The Original…" -> "KazuNori",
  "Sushi of Gari 46" -> "Sushi of Gari"), owner aliases.

**Phase 4 — YONO live case (tools done, data partly entered).**
- YONO facts verified from yonosushinyc.com and confirmed by the owner: Moynihan location, address, hours
  (daily 11–10, sushi bar 12–7), aliases "YONO" + "YONO Sushi by BondST", omakase $95 (owner-confirmed).
  BONDST is YONO's sister brand — not a competitor.
- Website audit now follows the Menu link: YONO = no Restaurant schema, menu only as 4 PDFs, 139 words on the homepage.
- `0 · Setup` panel tabs: Competitors / Menu prices (📷 read a menu photo, screenshot, PDF or link with Gemini,
  then pick the comparable dish) / Listings & mentions / Reviews (paste `rating | text`, source required).
- Discovery tab: "Who the AI recommends instead" — names extracted from real answers, one click to add as competitors.
- FAQ draft uses the verified address + hours.

### Live data in the repo
| Restaurant | Saved real answers | Model | Notes |
|---|---|---|---|
| YONO Sushi | 45 | gemini-3.5-flash-lite | 6 competitors; area "Penn Station", landmark "Moynihan Train Hall" |
| Malatesta Trattoria | 21 | gemini-3.5-flash-lite | second test restaurant (Italian, West Village), 2 competitors |

### ⏳ Not done yet
- **YONO listings + reviews not entered** (no `sources.json` / `reviews.json`). Value-for-Money for YONO is empty until real reviews are pasted.
- **A complete 90-answer run for YONO** (free Gemini quota stops it around 20 per model per day).
- Phases 5 and 6 (below).

---

## 2. What to build next

### Phase 5 — the two differentiator engines, live
**Creator engine (`creators.py`).**
- Find REAL local food creators who cover the cuisine + area. YouTube first, then TikTok/Instagram/blogs.
  For YONO: NYC sushi/Japanese-food creators, commuter / quick-lunch / budget / omakase / date-night niches.
- Save finds to `data/live/creators_live.json` in exactly the `data/creators_demo.json` record format
  (handle, name, platform, followers, engagement_rate, local_to, niches, best_performing_format). Add a
  `verified` field + `source_url`; label anything unverified on screen. Never invent follower counts or engagement.
- `niches` must use the query-bank category names: generic, signature, cheap, value, lunch, date-night, premium,
  group, dietary, tourist, late-night.
- Re-run the existing scoring UNCHANGED; briefs + outreach come from the real lost categories Discovery found.
- Optional in-app helper: a "find creators" step (Claude web search on a paid key) that proposes candidates for the owner to verify, like competitor auto-suggest.

**VfM engine (`reviews_vfm.py`).**
- Run it on YONO's REAL reviews (entered via Setup -> Reviews, or pasted by the user) with the computed area benchmark.
- Keep the formula transparent; every recommendation needs counts + a quoted review. Price = position + test plan, never a sales prediction.
- Compare like with like: YONO's hero is a $95 omakase AND it sells $17–22 chirashi bowls. Consider benchmarking
  per menu format (sushi-bar omakase vs grab-and-go bowls) instead of one "main dish".
- YONO's website PDF menu is dated Dec 2024 (chirashi $17–19); its Toast ordering page shows Salmon Chirashi $21.95. Ask the owner which is current.

### Phase 6 — hackathon-ready polish
- **Measurement:** after fixes are approved, a "Re-run Discovery" button runs the identical bank fresh
  (`use_cache=False`) and shows before/after mention rate, rank and share of voice from SQLite, labelled
  "directional" for same-day movement. `save_run` already stores mention_rate, avg_rank, share_of_voice and counts.
- **Errors:** no raw tracebacks anywhere — plain English + what to do next.
- **Zero-explanation UI:** label each screen with its owner question (Where do I rank? / Why do competitors win? /
  What should I change? / Can you make the changes? / Did it improve?).
- **README:** run for a NEW restaurant in 5 steps, how to add keys, what is live vs demo. Use `python -m streamlit run app.py`.
- **Final check:** run fresh, one full live cycle for YONO, then an honest list: what is LIVE, what is still SAMPLE, remaining bugs.

### Backlog (agreed, not started)
1. **Switch to Anthropic as the main platform** (the user has billing). Add `ANTHROPIC_API_KEY`; Claude then appears
   in the sidebar platform list. Port the two Gemini-only features to Claude: `suggest_competitors` (use Claude's
   server-side web search tool -> web-verified suggestions) and `read_menu_file` (Claude reads images/PDFs).
   Keep Gemini optional. Load the `claude-api` skill first. Default model `claude-opus-5-5`; ask the user before
   switching to a cheaper model.
2. **Google Places API (New)** — the user will create `GOOGLE_PLACES_API_KEY` later. Use it to fill rating, review
   count and price level for the restaurant + competitors automatically, and fetch up to 5 reviews per place
   (labelled "via Google Places API"). Still allow pasted reviews for depth. Respect Google's caching rules.
3. Delete the throwaway `data/live/test_sushi_bar/` (git-ignored) once the user OKs it.
4. Merge near-duplicate names in "who AI recommends" (e.g. "Zuma New York" / "Zuma NYC").

---

## 3. Teammate setup (step by step)
1. Install **Python 3.11+**, **Git**, **VS Code**, and **Claude Code**.
2. Accept the GitHub invite, then clone:
   `git clone https://github.com/<owner>/platerank.git` and `cd platerank`.
3. Install packages: `python -m pip install -r requirements.txt`.
4. Create your keys file: copy `.env.example` to `.env` and add YOUR OWN keys
   (`GOOGLE_API_KEY` from aistudio.google.com, `ANTHROPIC_API_KEY` from console.anthropic.com).
   `.env` is git-ignored — never commit it or paste keys in chat.
5. Check everything works offline: `python tests/module_checks.py` and `python tests/discovery_checks.py` (expect 17 + 12 passed).
6. Start the app: `python -m streamlit run app.py` -> http://localhost:8501.
7. Try the Example (SAMPLE) mode -> ▶ Run Discovery -> click the 5 tabs. Then pick **YONO Sushi** in Live mode:
   ▶ Run Discovery with "Reuse saved answers" ticked shows the 45 saved real answers without new API calls.
8. Open Claude Code in the folder (`claude`), paste the kickoff prompt below.
9. Work on a branch: `git checkout -b phase-5`, commit often, push, open a pull request.

---

## 4. Kickoff prompt for Claude Code (copy everything in the box)

```
You are joining the PlateRank AI hackathon project (NYU SPS x Pulse Foundry, Oct 23, 2026). Read CLAUDE.md and
HANDOFF.md first, then app.py and every file in platerank/ and data/. Do not change anything yet.

Then STOP and give me, in plain words (I may be new to Claude Code):
1. a 5-line summary of what the app does today,
2. your step-by-step plan for Phase 5 (live creator engine + VfM on real reviews) and Phase 6 (measurement
   re-run with before/after, plain-English errors, labelled screens, README, final live check) from HANDOFF.md,
3. any risks or questions (keys, quotas, missing data).

Rules for the whole session:
- Follow every rule in CLAUDE.md. Never fabricate data (reviews, ratings, creators, prices, competitors, AI
  answers); unknown = say unknown and ask me. Label SAMPLE/LIVE/CACHED/FAILED honestly in the UI.
- Ask me before each phase, before installs, before anything that costs money (paid API calls), before
  deleting data, and before any git commit or push.
- Keep the pipeline and module names. Work inside the existing architecture.
- Keep tests/module_checks.py and tests/discovery_checks.py passing; add checks for what you build.
- After each phase, run the app or the checks and show me the result before moving on.
- Before touching Claude API code, load the claude-api skill.
- Never print or log API keys; check only whether a key exists.
```

---

## 5. Known issues / gotchas
- Gemini free tier: 20 requests/day per model; no Google Search grounding. A full run = 90 calls.
- `gemini-3.5-flash-lite` is set in `.env` on the original laptop (`GEMINI_MODEL=`) because the Flash quota ran out; it's a smaller model than the Gemini app uses.
- Auto-suggested competitors can be wrong or far away — always verify (e.g. "Sushi Seki Times Square" is Midtown, not Penn Station).
- Reading prices straight from websites often fails (PDF / image / ordering-app menus) — use the 📷 menu reader.
- Streamlit: edit a table cell, press Enter, THEN click Save. The Reviews Save button stays grey until "Where were these copied from?" is filled.
- The bare `streamlit` command may not be on PATH — use `python -m streamlit run app.py`.
