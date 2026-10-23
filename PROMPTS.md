# Prompts for Claude Code (VS Code)

Copy a whole box into Claude Code. Each one follows the same safe loop:
**plan → you approve → build on a branch → `python check.py` → show result → you approve the commit.**

> Tip: start every new Claude Code session with prompt 0. Use prompt 1 for any new feature,
> prompt 8 for any bug. Prompts 2–7 are the planned work, in order.

---

## 0 · Start of every session

```
Read CLAUDE.md, HANDOFF.md and PROMPTS.md first. Then run `python check.py` and tell me in 3 lines:
what the app does, whether all checks pass, and which git branch we're on.
Don't change anything yet. Follow every rule in CLAUDE.md for the whole session:
never fabricate data, label SAMPLE/LIVE/CACHED/FAILED honestly, never print API keys,
ask me before installs, paid API calls, deleting data, and any git commit/push/PR.
Speak plainly - I'm new to Claude Code.
```

## 1 · Ship any new feature (template - fill in the first line)

```
Feature: <describe it in one or two sentences, and which owner question it helps answer>

1. Read the files involved and give me a short plan: which files change, what the user sees,
   what could go wrong, and whether it costs API money. Wait for my OK.
2. Create a branch (git checkout -b feature/<short-name>) - never work on main.
3. Build it inside the existing architecture (CLAUDE.md table). Backend logic goes in platerank/,
   HTTP routes in api.py, screens in web/src/. Keep api.py thin.
4. Add offline checks for it in tests/ (fake any Claude / map / website call - checks must be free).
5. If you changed web/src, run `cd web && npm run build`.
6. Run `python check.py` and show me the output. Fix anything red.
7. Tell me in plain words how to try it in the app (python run.py), then ask before committing.
```

## 2 · Phase 5a - live creator engine (real, verified creators)

```
Phase 5a from HANDOFF.md: real local food creators for the selected restaurant.
Plan first and wait for my OK.
- Add a "Find creators" step: Claude + web search (platerank/llm.py, web_search_tool with the restaurant's
  location) proposes YouTube creators first, then TikTok/Instagram/blogs, who cover this cuisine + area
  and the categories the restaurant is losing (from the latest Discovery run). Each proposal must include
  a source_url (the channel/profile page) - drop any without one.
- Show proposals in the "Make the changes" tab with a checkbox each; only the ones I tick are saved to
  data/live/creators_live.json in the exact data/creators_demo.json format plus "verified": false,
  "source_url", "found_for": <restaurant>. I mark verified myself after checking follower counts.
- Never invent follower counts or engagement: if the page doesn't show them, store null and show "unknown".
- Score with creators.score_creator UNCHANGED (treat null engagement/followers as unknown, not zero -
  add that handling in one place and a check for it). niches must use the query-bank category names.
- Show the cost before running (it's one web-search call per click). Add offline checks with a fake
  Claude reply. Then python check.py, show me, ask before commit.
```

## 3 · Phase 5b - Value-for-Money on real reviews + hero dish from the real menu

```
Phase 5b from HANDOFF.md. Plan first and wait for my OK.
- In Setup step 1 "Owner details", add "Read my menu": upload a PDF/photo or paste a menu link ->
  scrape.read_menu_file / read_menu_from_link (Claude) -> a DROPDOWN of the real dishes with prices.
  The owner picks the hero dish and the everyday item from the dropdown; prices fill in from the menu.
  Nothing is saved until they pick. Show "read from <source>" next to each price.
- Same for competitors in step 2: "Read their menu" on each ticked competitor fills competitor_menus
  (entree_price / anchor_price + source) so the area benchmark has a real sample size.
- Compare like with like: let the owner tag a menu format (e.g. "omakase" vs "bowls") and benchmark per
  format (see the YONO note in HANDOFF.md). Keep reviews_vfm formulas unchanged and transparent.
- Reviews stay owner-pasted only (Change tab form). Never generate or "simulate" reviews.
- Offline checks with fake Claude replies; npm run build; python check.py; show me; ask before commit.
```

## 4 · Phase 6a - measurement: before/after that a judge believes

```
Phase 6a. Plan first.
- In "Did it improve?", add a clear before/after: pick any two saved runs (default: first vs latest) and
  show mention rate, average rank and share of voice side by side, per question category too.
- Only compare runs that used the same question bank, platform(s) and web-search setting - otherwise say
  "not comparable" and why.
- Label same-day movement "directional - AI answers vary run to run" (CLAUDE.md rule 6).
- Add a "Re-check now (fresh answers)" button that runs with reuse=false after confirming the cost.
- Offline checks using a temp SQLite DB (see tests/module_checks.py); python check.py; show me; ask before commit.
```

## 5 · Phase 6b - plain-English everywhere + zero-explanation UI

```
Phase 6b. Plan first.
- Walk every screen of the new app (python run.py) and every api.py route. Anywhere a raw error,
  traceback, JSON blob or jargon ("schema", "SOV", "aspect sentiment") reaches the user, replace it with a
  plain sentence + what to do next (keep the technical detail behind a "details" toggle).
- Each results tab must state, in one line at the top, the answer to its owner question.
- Keep the screen uncluttered: one headline number, max 3 key points, everything else under "Show more".
- Add checks for any new error paths. npm run build; python check.py; show me screenshots or describe
  what changed; ask before commit.
```

## 6 · Final live check for the demo restaurant (costs money - asks first)

```
Final live check for <restaurant name>. Before ANY paid call, tell me the plan and the estimated cost
(use /api/restaurants/<slug>/estimate and tools/check_live.py numbers) and wait for my OK.
1. python tools/check_live.py --yes  (key + web search + web fetch).
2. In the app: run Discovery with Claude + web search, 1 run first; show me the headline numbers.
3. Run the website check, "Find public ratings" (I approve each value), and paste-in reviews if I have them.
4. Then an honest report in plain words: what is LIVE, what is CACHED, what is still SAMPLE or empty,
   total money spent, and any bug you saw. Don't fix anything without asking.
```

## 7 · Before you push to GitHub

```
Run `python check.py`. If anything fails, explain why in plain words and propose a fix (don't apply it yet).
If everything passes, show me `git status` and `git diff --stat`, suggest a one-line commit message,
and wait for my OK before committing and pushing to this branch (never to main). Then open a pull request
with a short summary of what changed and how it was tested.
```

## 8 · Fix a bug

```
Bug: <what I did, what I expected, what happened - paste any error text>
First reproduce it (or explain why you can't), then tell me the cause in one or two sentences and the
smallest fix. Wait for my OK. After fixing, add a check in tests/ that would have caught it,
run `python check.py`, show me, and ask before committing.
```

## 9 · Explain something to me

```
Explain <file / feature / error> to me like I'm new to coding: what it does, how data flows through it,
and what would break if I changed it. Use a short example. Don't change any files.
```
