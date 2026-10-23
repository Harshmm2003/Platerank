"""Install the git safety net (run once per laptop):  python tools/install_hooks.py

After this, every `git push` first runs `python check.py` (free, offline, ~10 s).
If a check fails, the push is stopped and nothing broken reaches GitHub.
Emergency override (avoid): git push --no-verify
"""
import stat, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
hooks = root / ".git" / "hooks"
if not (root / ".git").is_dir():
    sys.exit("No .git folder here - run this inside the cloned PlateRank repo.")
hooks.mkdir(exist_ok=True)

hook = hooks / "pre-push"
# Git for Windows runs hooks with its own sh, so a POSIX script works on Windows, macOS and Linux.
hook.write_text(
    "#!/bin/sh\n"
    "# PlateRank: run the offline checks before every push (installed by tools/install_hooks.py)\n"
    'echo "PlateRank: running checks before push..."\n'
    "PY=python\n"
    "command -v python >/dev/null 2>&1 || PY=python3\n"
    '"$PY" check.py || { echo "Push stopped: fix the failing checks above (or paste them into Claude Code)."; exit 1; }\n',
    encoding="utf-8", newline="\n")
hook.chmod(hook.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
print(f"Installed {hook.relative_to(root)} - every git push now runs `python check.py` first.")
