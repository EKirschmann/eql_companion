#!/usr/bin/env python3
"""EQL Companion — git-free updater.

Downloads the latest code ZIP straight from GitHub (the same content the
green "Download ZIP" button serves) and lays it over this install,
preserving your settings and data. No git required — Python (already a
requirement) does everything. Run via update_companion.bat, or directly:

    python update_companion.py [--no-deps]
"""
import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import json

ROOT = Path(__file__).resolve().parent
REPO = "EKirschmann/eql_companion"
FALLBACK_ZIP = f"https://github.com/{REPO}/archive/refs/heads/main.zip"


def latest_tag() -> str | None:
    """Newest release tag (semver max) — updates track RELEASES, not
    whatever is mid-development on main."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/tags?per_page=30",
            headers={"User-Agent": "eql-companion-updater"})
        with urllib.request.urlopen(req, timeout=20) as r:
            tags = json.loads(r.read())
        names = [str(t.get("name", "")) for t in tags]
        def ver(v):
            import re
            return tuple(int(x) for x in re.findall(r"[0-9]+", v)[:3]) or (0,)
        return max((n for n in names if n), key=ver, default=None)
    except Exception:
        return None

# never touched by the updater — user state and heavy build artifacts
PRESERVE = {".env", ".env.bak", "data", "node_modules", ".next", ".git",
            "backup"}
# a running script/batch must not be rewritten mid-run — changed versions
# land beside them as *.new with a notice
SELF = {"update_companion.py", "update_companion.bat"}


def say(t=""):
    print(t, flush=True)


def download() -> zipfile.ZipFile:
    tag = latest_tag()
    url = (f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip"
           if tag else FALLBACK_ZIP)
    say(f"Downloading {tag or 'the latest code'} from github.com/{REPO} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "eql-companion-updater"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    say(f"  {len(data) // 1024} KB received")
    return zipfile.ZipFile(io.BytesIO(data))


def apply(z: zipfile.ZipFile) -> int:
    changed = 0
    for info in z.infolist():
        parts = Path(info.filename).parts
        if len(parts) < 2 or info.is_dir():
            continue  # skip the "repo-main/" wrapper itself and dirs
        rel = Path(*parts[1:])
        if rel.parts[0] in PRESERVE:
            continue
        new = z.read(info)
        target = ROOT / rel
        if target.exists() and target.read_bytes() == new:
            continue
        if rel.name in SELF and target.exists():
            side = target.with_suffix(target.suffix + ".new")
            side.write_bytes(new)
            say(f"  ! {rel} changed upstream — saved as {side.name} "
                "(swap it in after this run)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new)
        changed += 1
    return changed


def deps() -> None:
    say("Refreshing Python dependencies ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    str(ROOT / "requirements.txt")], check=False)
    say("Refreshing frontend dependencies ...")
    subprocess.run("npm install --silent", shell=True,
                   cwd=str(ROOT / "frontend"), check=False)


def main() -> None:
    say("=" * 56)
    say("EQL Companion updater (no git needed)")
    say("Your .env and data folder are never touched.")
    say("=" * 56)
    try:
        z = download()
    except Exception as e:
        say(f"Download failed ({type(e).__name__}: {e}) — check your "
            "connection, or update manually via a fresh ZIP.")
        sys.exit(1)
    changed = apply(z)
    say(f"Updated {changed} file(s)." if changed else
        "Already up to date — nothing changed.")
    if changed and "--no-deps" not in sys.argv:
        deps()
    say("Done. Start the companion with start_companion.bat")


if __name__ == "__main__":
    main()
