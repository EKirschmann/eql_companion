#!/usr/bin/env python3
"""EQL Companion — first-run setup wizard.

Interactive, dependency-free (stdlib only). Everything you choose here is
written to .env — you can change any answer later by editing that file.
Run me directly (python setup_wizard.py) or via install_companion.bat.
"""
import re
import string
import sys
import tempfile
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAME_SUFFIX = r"Daybreak Game Company\Installed Games\EverQuest Legends"
MAPS_PAGE = "https://www.eqmaps.info/eq-map-files/"


def say(text=""):
    print(text)


def ask(prompt, default=""):
    tail = f" [{default}]" if default else ""
    val = input(f"{prompt}{tail}: ").strip()
    return val or default


def yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    val = input(f"{prompt} ({d}): ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


# ------------------------------------------------------------ game folder

def looks_like_eql(p: Path) -> bool:
    try:
        # eqgame.exe or zone archives — a bare "Logs" dir is not enough
        # (C:\Windows has one of those too)
        return p.is_dir() and (
            (p / "eqgame.exe").exists()
            or next(p.glob("*.s3d"), None) is not None
        )
    except OSError:
        return False


def find_installs() -> list:
    """The game's own registry entry first (finds CUSTOM install paths
    with zero typing), then a scan of every drive's standard spots."""
    hits = []
    try:
        from backend.config import _registry_game_dir
        reg = _registry_game_dir()
        if reg and looks_like_eql(Path(reg)):
            hits.append(Path(reg))
    except Exception:
        pass
    for drive in string.ascii_uppercase:
        for pattern in (
            rf"{drive}:\Users\Public\{GAME_SUFFIX}",
            rf"{drive}:\{GAME_SUFFIX}",
            rf"{drive}:\Program Files (x86)\{GAME_SUFFIX}",
            rf"{drive}:\Program Files\{GAME_SUFFIX}",
        ):
            p = Path(pattern)
            if looks_like_eql(p) and p not in hits:
                hits.append(p)
    return hits


def choose_game_dir() -> str:
    say()
    say("== 1/3 · Your EverQuest Legends install ==")
    say("Looking for the game (registry entry, then every drive) ...")
    hits = find_installs()
    if hits:
        for i, h in enumerate(hits, 1):
            say(f"  {i}. {h}")
        pick = ask("Use which one? (number, or paste a different path)", "1")
        if pick.isdigit() and 1 <= int(pick) <= len(hits):
            return str(hits[int(pick) - 1])
        candidate = pick
    else:
        say("Not found in the usual places.")
        say(r"It normally looks like ...\Daybreak Game Company\Installed Games\EverQuest Legends")
        candidate = ask("Paste your EverQuest Legends folder path")
    while candidate:
        p = Path(candidate.strip().strip('"'))
        if looks_like_eql(p):
            return str(p)
        say("  That folder doesn't look like an EQL install (no eqgame.exe / .s3d files).")
        if yesno("  Use it anyway?", False):
            return str(p)
        candidate = ask("Paste your EverQuest Legends folder path (blank to skip)")
    say("  Skipping — set EQL_GAME_DIR in .env later.")
    return ""


# ------------------------------------------------------------- map files

def try_download_brewall(maps_dir: Path) -> bool:
    """Best-effort: find a Brewall zip link on the eqmaps.info page and
    extract it into maps/Dark Brewall. The site layout can change — any
    failure falls back to opening the page in the browser."""
    say("Looking for the Brewall map pack download ...")
    req = urllib.request.Request(MAPS_PAGE, headers={"User-Agent": "eql-companion-setup"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    links = re.findall(r'href="([^"]+\.zip)"', html, re.I)
    link = next((l for l in links if "brewall" in l.lower()), None)
    if not link:
        return False
    if link.startswith("/"):
        link = "https://www.eqmaps.info" + link
    say(f"  Downloading {link.rsplit('/', 1)[-1]} ...")
    target = maps_dir / "Dark Brewall"
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as tmp:
        req = urllib.request.Request(link, headers={"User-Agent": "eql-companion-setup"})
        with urllib.request.urlopen(req, timeout=120) as r:
            while chunk := r.read(1 << 20):
                tmp.write(chunk)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".txt")]
            for n in names:
                data = z.read(n)
                (target / Path(n).name).write_bytes(data)
    count = len(list(target.glob("*.txt")))
    say(f"  Extracted {count} map files into {target}")
    return count > 0


def setup_maps(game_dir: str) -> None:
    say()
    say("== 2/3 · Atlas map files ==")
    say("The 3D view and 'true walls' mine the game's own files — nothing to")
    say("download for those. The 2D chart view uses community map files; the")
    say("Brewall pack adds ~1700 charts including dungeons.")
    if not game_dir:
        say(f"  (No game folder set — grab maps later from {MAPS_PAGE})")
        return
    maps_dir = Path(game_dir) / "maps"
    brewall = maps_dir / "Dark Brewall"
    if brewall.is_dir() and next(brewall.glob("*.txt"), None):
        say(f"  Brewall pack already present at {brewall} — nothing to do.")
        return
    if not yesno("Download the Brewall map pack now?", True):
        say(f"  Skipped. Maps live at: {MAPS_PAGE}")
        say(f"  Extract them into: {brewall}")
        return
    try:
        if try_download_brewall(maps_dir):
            return
        say("  Couldn't find a direct download link on the page.")
    except Exception as e:
        say(f"  Download failed ({type(e).__name__}: {e}).")
    say("  Opening the maps page in your browser instead — download the")
    say(f"  Brewall pack and extract the .txt files into: {brewall}")
    try:
        webbrowser.open(MAPS_PAGE)
    except Exception:
        say(f"  (Open it manually: {MAPS_PAGE})")


# ------------------------------------------------------------ LLM choice

def choose_llm() -> dict:
    say()
    say("== 3/3 · Advisor counsel model ==")
    say("The Advisor works with NO model at all (deterministic counsel).")
    say("A model adds reasoned, tactical advice. You can switch anytime in")
    say("the Advisor tab, or by editing .env.")
    say("  1. None            - no setup, instant, deterministic (default)")
    say("  2. LM Studio       - free local models (needs LM Studio running)")
    say("  3. OpenAI          - best quality (needs an API key)")
    say("  4. Custom endpoint - Groq / OpenRouter / any OpenAI-compatible URL")
    pick = ask("Choice", "1")
    env = {}
    if pick == "2":
        env["LLM_PROVIDER"] = "lmstudio"
        env["MODEL"] = ask("Model id as LM Studio shows it (blank = set later)")
    elif pick == "3":
        env["LLM_PROVIDER"] = "openai"
        say("  Your key stays in your local .env — never committed or uploaded.")
        env["OPENAI_API_KEY"] = ask("OpenAI API key (blank = paste into .env later)")
        env["OPENAI_MODEL"] = ask("Model", "o3")
    elif pick == "4":
        env["LLM_PROVIDER"] = "custom"
        env["CUSTOM_BASE_URL"] = ask("Base URL (e.g. https://api.groq.com/openai/v1)")
        env["CUSTOM_API_KEY"] = ask("API key (blank if none needed)")
        env["CUSTOM_MODEL"] = ask("Model id")
    else:
        env["LLM_PROVIDER"] = "none"
    return env


# -------------------------------------------------------------- .env write

def write_env(values: dict) -> None:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.exists():
        say()
        if not yesno(".env already exists — overwrite it with these answers?", False):
            say("  Keeping your existing .env. Answers NOT saved — edit it by hand.")
            return
        env_path.replace(ROOT / ".env.bak")
        say("  (previous version saved as .env.bak)")
    text = example.read_text(encoding="utf-8")
    for key, val in values.items():
        if val is None:
            continue
        pattern = re.compile(rf"^(# )?{re.escape(key)}=.*$", re.M)
        if pattern.search(text):
            # lambda keeps backslashes in val literal (paths break re escapes)
            text = pattern.sub(lambda m: f"{key}={val}", text, count=1)
        else:
            text += f"{key}={val}" + chr(10)
    env_path.write_text(text, encoding="utf-8")
    say(f"  Wrote {env_path}")


def main() -> None:
    say("=" * 62)
    say("EQL Companion setup")
    say("Every answer here just fills in the .env file — you can change")
    say("any of it later by editing .env in this folder.")
    say("=" * 62)
    game_dir = choose_game_dir()
    setup_maps(game_dir)
    env = choose_llm()
    if game_dir:
        env["EQL_GAME_DIR"] = game_dir
    write_env(env)
    say()
    say("Done! Next steps:")
    say("  1. start_companion.bat   (backend + UI, opens the browser)")
    say("  2. In game:  /log on   then   /who")
    say("  3. For the Advisor:  /outputfile spellbook + inventory +")
    say("     missingspells, /alternateadv list — then 'check exports'")
    say("Change anything later in .env (game folder, model, keys).")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        say(chr(10) + "Setup cancelled — run me again anytime. Nothing was broken.")
        sys.exit(1)
