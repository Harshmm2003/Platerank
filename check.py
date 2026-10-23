"""ONE command to test PlateRank before you ship anything:

    python check.py          # free, offline: every check file + frontend checks   (~10 seconds)
    python check.py --live   # also checks the real Claude key + web tools          (costs ~2 cents)

Exit code 0 = safe to commit/push. The git pre-push hook (python tools/install_hooks.py)
runs the free version automatically and blocks the push if anything fails.
"""
import re, shutil, subprocess, sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to cp1252 and crash on ✓ / ✗
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _can_print(s: str) -> bool:
    try:
        s.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


TICK, CROSS = ("✓", "✗") if _can_print("✓✗") else ("OK", "X")

ROOT = Path(__file__).resolve().parent
PY = sys.executable
GREEN, RED, YELLOW, END = ("\033[92m", "\033[91m", "\033[93m", "\033[0m") if sys.stdout.isatty() else ("", "", "", "")

steps = [
    ("Engines (scoring, VfM, creators, drafts)", [PY, "tests/module_checks.py"]),
    ("Discovery (name matching, cache, quota)", [PY, "tests/discovery_checks.py"]),
    ("Web app backend + Claude helper + map search", [PY, "tests/api_checks.py"]),
    ("Old Streamlit app still imports", [PY, "-c", "import ast,sys; ast.parse(open('app.py',encoding='utf-8').read()); print('ok')"]),
]
npm = shutil.which("npm")
if npm and (ROOT / "web" / "node_modules").exists():
    steps.append(("Frontend type check", [npm, "run", "typecheck", "--prefix", "web"]))
if "--live" in sys.argv:
    steps.append(("LIVE Claude key + web search + web fetch (~$0.02)", [PY, "tools/check_live.py", "--yes"]))

failed = []
for name, cmd in steps:
    t = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip()
    summary = next((l for l in reversed(out.splitlines()) if "passed" in l), "ok" if p.returncode == 0 else "")
    if p.returncode == 0 and not re.search(r"\b[1-9]\d* failed", summary):
        print(f"{GREEN}PASS{END}  {name}  ({time.time() - t:.1f}s)  {summary}")
    else:
        failed.append(name)
        print(f"{RED}FAIL{END}  {name}")
        for line in out.splitlines():
            if line.startswith("FAIL") or "Error" in line or "error" in line:
                print("      " + line[:300])

if not npm or not (ROOT / "web" / "node_modules").exists():
    print(f"{YELLOW}SKIP{END}  Frontend type check (Node.js not installed or `npm install` not run in web/ - fine if you didn't change web/src)")
print()
if failed:
    print(f"{RED}{CROSS} {len(failed)} check(s) failed - don't commit or push yet.{END} Fix them, or paste this output into Claude Code.")
    sys.exit(1)
print(f"{GREEN}{TICK} All checks passed - safe to commit and push.{END}")
