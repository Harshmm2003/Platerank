"""LIVE smoke test for the Claude key and its tools. Costs a few cents - run it on purpose.

    python tools/check_live.py            # shows what it would test, spends nothing
    python tools/check_live.py --yes      # key + model + web search + web fetch  (~$0.02)
    python tools/check_live.py --yes --discovery claude-sonnet-5-5 claude-opus-5-5
                                          # + one real Discovery question per model, with cost,
                                          #   so you can estimate a full run (~$0.10-0.30 each)

Never prints the key. Exit code 0 = everything passed.
"""
import argparse, sys, time
from pathlib import Path
for _s in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to cp1252 and crash on non-ASCII (· and error text)
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from platerank import llm

ap = argparse.ArgumentParser()
ap.add_argument("--yes", action="store_true", help="actually call Claude (costs a few cents)")
ap.add_argument("--discovery", nargs="*", default=[], help="models to price one Discovery question on")
args = ap.parse_args()

CHEAP = "claude-haiku-5-5"
results, spent = [], 0.0

def step(name, fn):
    global spent
    t = time.time()
    try:
        detail, cost = fn()
        spent += cost
        results.append(True)
        print(f"PASS  {name} ({time.time() - t:.1f}s, ${cost:.4f}) - {detail}")
    except Exception as e:
        results.append(False)
        print(f"FAIL  {name} - {e}")

import anthropic
print("1. Key in .env:", "found" if llm.has_key() else "MISSING", f"· anthropic package {anthropic.__version__}")
if not llm.has_key():
    print("   Add ANTHROPIC_API_KEY=... to .env (no quotes needed), then run again.")
    sys.exit(1)
if not args.yes:
    print("Dry run - nothing was sent. Add --yes to run the live checks (about $0.02).")
    sys.exit(0)

def plain():
    r = llm.claude_call("Reply with exactly: OK", model=CHEAP, max_tokens=20, effort=None)
    return f"model {r.model} answered {r.text.strip()[:20]!r}", r.cost_usd

def default_model():
    r = llm.claude_call("Reply with exactly: OK", max_tokens=50, effort="low")
    return f"{r.model} works with the app's settings (effort + fallbacks)", r.cost_usd

def search():
    # tool_choice "any" makes Claude use the tool, so a pass/fail here is about the tool, not the model's choice
    r = llm.claude_call("Search the web: what street address is Moynihan Train Hall in New York on? One line.",
                        model=CHEAP, tools=[llm.web_search_tool(max_uses=1)], max_tokens=600, effort=None,
                        tool_choice={"type": "any"})
    if not r.searches:
        raise RuntimeError("Claude didn't run a search even when told to - check Settings -> Capabilities "
                           "(web search) in console.anthropic.com.")
    return f"{r.searches} search, {len(r.sources)} sources, answer: {r.text.strip()[:70]!r}", r.cost_usd

def fetch():
    r = llm.claude_call("Fetch https://example.com and reply with only the page's main heading.",
                        model=CHEAP, tools=[llm.web_fetch_tool(max_uses=1, max_content_tokens=2000)],
                        max_tokens=400, effort=None, tool_choice={"type": "any"})
    if not r.fetches:
        raise RuntimeError("Claude answered without fetching - web fetch may be off for this organisation.")
    return f"{r.fetches} fetch, answer: {r.text.strip()[:60]!r}", r.cost_usd

step("2. Key + credit (cheap model)", plain)
step(f"3. App's default model ({llm.default_model()})", default_model)
step("4. Web search tool", search)
step("5. Web fetch tool", fetch)

for m in args.discovery:
    def disc(m=m):
        from platerank.discovery import SYSTEM
        r = llm.claude_call("best sushi near Penn Station, New York", system=SYSTEM, model=m,
                            tools=[llm.web_search_tool(max_uses=3, location={"city": "New York", "region": "New York",
                                                                             "country": "US", "timezone": "America/New_York"})])
        return (f"{r.searches} searches, {r.input_tokens} in / {r.output_tokens} out tokens -> "
                f"30 questions ≈ ${30 * r.cost_usd:.2f}, 90 ≈ ${90 * r.cost_usd:.2f}"), r.cost_usd
    step(f"6. One Discovery question on {m}", disc)

print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed · spent about ${spent:.3f}")
sys.exit(0 if all(results) else 1)
