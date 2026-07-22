# Installing the EQL Companion — the plain-language guide

Written for people who have never installed a program from a ZIP file.
You do NOT need git, GitHub knowledge, or anything a programmer uses.
Total time: about ten minutes, most of it watching progress bars.

**Before you start, you need:**
- Windows 10 or 11
- EverQuest Legends installed (and run at least once)
- About 1 GB of free disk space

The companion is passive — it only **reads** your combat log. It never
touches game files, never injects, never automates anything in-game.

---

## Step 1 — Download and unzip

1. Open <https://github.com/EKirschmann/eql_companion/releases> in your
   browser.
2. Under the newest version (the one at the top), click
   **Source code (zip)** to download it.
3. Open your Downloads folder, **right-click the ZIP → Extract All… →
   Extract**. Put it somewhere easy, like `Documents\eql_companion`.

> ⚠ **The one mistake everyone makes:** double-clicking INTO the ZIP
> without extracting first. Nothing works from inside a ZIP. If your
> folder path starts with something like `Downloads\eql_companion.zip\`,
> you are inside the ZIP — go back and use **Extract All**.

**You'll know it worked when:** you have a normal folder containing
files like `install_companion.bat` and `README.md`.

## Step 2 — Run the installer

1. In that folder, double-click **install_companion.bat**.
   - If Windows shows a blue **"Windows protected your PC"** box, click
     **More info → Run anyway**. That warning appears for any script
     Windows hasn't seen before; this one is plain text you can open in
     Notepad and read.
2. A black window opens and stays open. If Python or Node.js are
   missing, it **offers to install them for you — just press Y** and
   wait. (No winget on your PC? Install Python from
   <https://www.python.org/downloads/> — **tick "Add python.exe to
   PATH"** on the first screen — and the LTS from <https://nodejs.org/>,
   then run the installer again.)
3. After a few minutes of progress bars, a short wizard asks:
   - **Your game folder** — it finds this by itself, even custom
     installs (it reads the game's own registry entry, then scans every
     drive). Press **Enter** to accept what it found. You should never
     need to type a path.
   - **Map pack** — press **y** to download the community maps.
   - **Counsel model** — press **Enter** for **None**. Everything works
     without one, and you can pick a model later inside the app.
4. When it asks to launch — press **Enter**. A browser tab opens with
   your HUD.

**You'll know it worked when:** the browser shows the dark-gold EQL
Companion page (it may say "waiting" — that's normal until Step 3).

## Step 3 — In the game (once per character)

Type these two lines in the EQL chat box:

    /log on
    /who

That's all the companion needs. The HUD fills in as you play.

**For the Advisor tab** (optional but worth it), also type:

    /outputfile spellbook
    /outputfile inventory
    /outputfile missingspells
    /alternateadv list

then press **check exports** in the app's Advisor tab.

**You'll know it worked when:** killing one mob makes rows appear in
the War Ledger within a second.

## Day to day

- **Start it:** double-click **start_companion.bat** (right-click →
  Send to → Desktop to make a shortcut).
- **The overlay** (in-game meter): press the **Overlay** button in the
  app header. Scroll Lock ON lets you move/adjust it; OFF makes clicks
  pass through to the game.
- **Updates:** the version number in the app header shows a badge when
  a new version exists. Double-click **update_companion.bat** — it
  downloads the newest release itself and never touches your settings.
- **Alerts:** edit `data\tracked_rules.json` in Notepad to get a chime
  when a rare item drops (the file has an example to copy).

## If something goes wrong

| What you see | What to do |
|---|---|
| "python is not recognized" | Press **Y** when the installer offers Python — or install it yourself with **Add python.exe to PATH** ticked, then re-run the installer |
| "winget is not recognized" | Your Windows is older — install Python and Node.js manually from the links in Step 2.2, then re-run |
| Nothing happens on double-click | You're inside the ZIP — do Step 1.3 (**Extract All**) first |
| The wizard can't find the game | Only happens on very unusual setups: find the folder containing `eqgame.exe` (right-click your desktop EQL shortcut → Open file location), copy the address bar, paste it into the wizard |
| App opens but everything says "waiting" | Type `/log on` in the game — the companion is blind without the log |
| It worked yesterday, empty today | The game turns logging off sometimes — type `/log on` again. The Vitals panel reminds you when the log goes quiet |
| Antivirus quarantines something | Restore it and add the folder to exclusions — everything here is plain readable Python/JavaScript, no compiled blobs |
| Something else | Close the black window, run **start_companion.bat** again, and read the last lines it prints — they usually say exactly what's missing |