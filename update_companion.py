#!/usr/bin/env python3
"""EQL Companion — git-free updater.

Downloads the latest code ZIP straight from GitHub (the same content the
green "Download ZIP" button serves) and lays it over this install,
preserving your settings and data. No git required — Python (already a
requirement) does everything. Run via update_companion.bat, or directly:

    python update_companion.py [--no-deps]
"""
import io
import ssl
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


def _ssl_context() -> ssl.SSLContext:
    """certifi's CA bundle when available — some Windows Pythons (and
    antivirus HTTPS scanning) can't validate GitHub with the default store.
    Verification is NEVER disabled: this downloads code."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(req, timeout):
    try:
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=_ssl_context())
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            raise RuntimeError(
                "your PC's certificate store is blocking Python's HTTPS "
                "(often antivirus HTTPS-scanning). Fix: open this window's "
                "folder in a terminal and run   pip install certifi   then "
                "run the updater again — or download the ZIP in your "
                "browser from github.com/" + REPO + "/releases") from e
        raise

import json

ROOT = Path(__file__).resolve().parent
REPO = "EKirschmann/eql_companion"
FALLBACK_ZIP = f"https://github.com/{REPO}/archive/refs/heads/main.zip"


def latest_tag() -> str | None:
    """Newest release tag (semver max) — updates track RELEASES, not
    whatever is mid-development on main. API first, plain tags page as a
    fallback (the API rate-limits shared IPs; the website does not)."""
    import re

    def ver(v):
        return tuple(int(x) for x in re.findall(r"[0-9]+", v)[:3]) or (0,)

    def from_api():
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/tags?per_page=30",
            headers={"User-Agent": "eql-companion-updater"})
        with _open(req, 20) as r:
            return [str(t.get("name", "")) for t in json.loads(r.read())]

    def from_page():
        req = urllib.request.Request(
            f"https://github.com/{REPO}/tags",
            headers={"User-Agent": "eql-companion-updater"})
        with _open(req, 20) as r:
            html = r.read().decode("utf-8", "replace")
        return re.findall(rf"/{REPO}/releases/tag/(v[0-9.]+)", html)

    for source in (from_api, from_page):
        try:
            names = source()
            best = max((n for n in names if n), key=ver, default=None)
            if best:
                return best
        except Exception:
            continue
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
    with _open(req, 120) as r:
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
