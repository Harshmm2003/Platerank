"""Fresh re-check for one restaurant: the SAME question bank, asked again without saved answers.
Costs money (one Claude call per question) - it asks first, or pass --yes (needed for Task Scheduler).

    python tools/recheck.py cafe_athena          # shows the plan + rough cost, asks "yes"
    python tools/recheck.py cafe_athena --yes    # no question (scheduled weekly runs)

Saves the run, prints first vs latest (mention rate, average rank, share of voice, per question type)
and appends one line to data/live/<slug>/recheck_log.txt. Exit code 0 = a fresh check was saved.
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from platerank import llm, pipeline


def _pct(x):
    return "-" if x is None else f"{round(x * 100)}%"


def report(cmp: dict) -> str:
    if not cmp.get("comparable"):
        return f"Before/after: {cmp['reason']}"
    f, l, d = cmp["first"], cmp["latest"], cmp["change"]
    rank = lambda x: "-" if x is None else f"{x:.1f}"
    lines = [f"Before/after ({cmp['label']})",
             f"  {'':22}{'first ' + f['when']:>22}{'latest ' + l['when']:>24}   change",
             f"  {'AI names you in':22}{_pct(f['mention_rate']):>22}{_pct(l['mention_rate']):>24}   "
             f"{'-' if d['mention_rate'] is None else f'{round(d['mention_rate'] * 100):+d} pts'}",
             f"  {'Average position':22}{rank(f['avg_rank']):>22}{rank(l['avg_rank']):>24}   "
             f"{'-' if d['avg_rank'] is None else f'{d['avg_rank']:+.1f} (lower is better)'}",
             f"  {'Share of voice':22}{_pct(f['share_of_voice']):>22}{_pct(l['share_of_voice']):>24}   "
             f"{'-' if d['share_of_voice'] is None else f'{round(d['share_of_voice'] * 100):+d} pts'}",
             "  Per question type:"]
    lines += [f"    {c['category']:18}{_pct(c['first']):>8} -> {_pct(c['latest']):<6}" for c in cmp["by_category"]]
    if cmp.get("skipped"):
        lines.append(f"  ({cmp['skipped']} earlier check(s) used different questions or platforms - not compared.)")
    return "\n".join(lines)


def main(argv=None, ask=input, interactive=None) -> int:
    ap = argparse.ArgumentParser(description="Fresh re-check (costs money).")
    ap.add_argument("slug", help="restaurant folder name, e.g. cafe_athena")
    ap.add_argument("--yes", action="store_true", help="don't ask - for scheduled runs")
    ap.add_argument("--runs", type=int, default=1, choices=(1, 2, 3))
    args = ap.parse_args(argv)
    interactive = sys.stdin.isatty() if interactive is None else interactive

    profile = pipeline.get_profile(args.slug)
    if profile is None or args.slug == pipeline.EXAMPLE_SLUG:
        print(f"'{args.slug}' isn't a saved restaurant. Saved: {', '.join(p.parent.name for p in (pipeline.DATA / 'live').glob('*/profile.json'))}")
        return 2
    if not profile.get("competitors"):
        print(f"{profile['name']} has no competitors yet - add them in the app (Setup step 2) first. Nothing was spent.")
        return 2
    # same platforms + web-search setting as the latest check, so the result is comparable
    last = (pipeline.load_runs(profile["name"]) or [None])[-1]
    platforms = (last or {}).get("platforms") or ["claude"]
    web_search = (last or {}).get("web_search", True)
    missing = [p for p in platforms if p not in pipeline.available_platforms()]
    if missing:
        print(f"No key for {', '.join(missing)} in .env - add it (ANTHROPIC_API_KEY for Claude) and run again. Nothing was spent.")
        return 2
    est = pipeline.estimate_calls(args.slug, args.runs, platforms)
    print(f"Re-check {profile['name']}: {est['questions']} questions x {args.runs} run(s) on {' + '.join(platforms)}"
          f"{' with web search' if web_search else ''}, fresh answers (model {est['model']}). Rough cost: up to ${est['rough_max_cost_usd']:.2f}.")
    if not args.yes:
        if not interactive:
            print("Not run: no one here to confirm the cost. Add --yes for scheduled runs. Nothing was spent.")
            return 1
        try:
            answer = ask("Type yes to go ahead: ")
        except EOFError:  # no keyboard after all (e.g. a scheduled run without --yes)
            answer = ""
        if answer.strip().lower() != "yes":
            print("Cancelled - nothing was spent.")
            return 1

    t = time.time()
    def progress(done, total, note):
        print(f"\r  {done}/{total} {note[:60]:60}", end="", flush=True)
    try:
        meta = pipeline.run(args.slug, args.runs, reuse=False, platforms=platforms, web_search=web_search, progress=progress)
    except (ValueError, llm.ClaudeUnavailable, llm.QuotaError) as e:
        print(f"\nThe re-check stopped: {e}")
        return 1
    print()
    c = meta["counts"]
    print(f"Done in {time.time() - t:.0f}s: {c['LIVE']} fresh, {c['CACHED']} saved (used when a fresh answer failed), "
          f"{c['FAILED']} no answer. Spent about ${meta['cost_usd']:.2f}.")
    cmp = pipeline.improvement(args.slug)
    print(report(cmp))
    line = (f"{meta['when']}  fresh={c['LIVE']} saved={c['CACHED']} failed={c['FAILED']}  cost=${meta['cost_usd']:.2f}  " +
            (f"mention {_pct(cmp['first']['mention_rate'])} -> {_pct(cmp['latest']['mention_rate'])}" if cmp.get("comparable") else cmp["reason"]))
    log = pipeline.state_dir(args.slug) / "recheck_log.txt"
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return 0 if c["LIVE"] > 0 else 1


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    sys.exit(main())
