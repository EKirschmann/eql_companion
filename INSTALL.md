# Installing the EQL Companion — the plain-language guide

No experience needed. You do NOT need git, GitHub knowledge, or anything a
programmer uses — just two free installs and a ZIP file. Total time: about
ten minutes, most of it watching progress bars.

## Step 1 — Download the companion

1. Go to <https://github.com/EKirschmann/eql_companion/releases> and,
   under the newest version at the top, download **Source code (zip)**.
3. Find the ZIP in your Downloads, **right-click it → Extract All…** and
   put it somewhere easy, like `Documents\eql_companion`.
   **Do not skip extracting** — opening the ZIP and double-clicking inside
   it will not work.

## Step 2 — Run the installer

1. Open the extracted folder and double-click **install_companion.bat**.
   - If Windows shows a blue "protected your PC" box: click **More info**,
     then **Run anyway**. (It is a plain script — you can open it in
     Notepad and read it.)
2. If Python or Node.js are missing, it **offers to install them for you**
   — just press **Y**. (If that fails on your PC, install them yourself:
   Python from <https://www.python.org/downloads/> — tick **"Add
   python.exe to PATH"** on the first screen — and the LTS version from
   <https://nodejs.org/> — then run the installer again.)
3. It installs the app's pieces (a few minutes), then asks a few questions:
   - It finds your EverQuest Legends folder by itself on most PCs — press
     **Enter** to accept.
   - It offers to download the community map pack — say **y**.
   - Counsel model: press **Enter** for **None**. Everything works without
     one; you can change this later inside the app.
3. When it offers to launch — say yes. A browser tab opens with your HUD.

## Step 3 — In the game (once per character)

Type these in the EQL chat box:

    /log on
    /who

That's it. The HUD starts filling in as you play. For the Advisor tab,
also run: `/outputfile spellbook`, `/outputfile inventory`,
`/outputfile missingspells`, and `/alternateadv list`, then press
**check exports** in the app.

## Day to day

- Start it with **start_companion.bat** (make a shortcut if you like).
- Click the **version number** in the app header to check for updates.
- To update: double-click **update_companion.bat** — it downloads the
  newest version itself and never touches your settings or data. (No git
  or anything else needed.)

## If something goes wrong

| Symptom | Fix |
|---|---|
| "python is not recognized" | Say **Y** when the installer offers to install Python — or install it yourself with the **Add python.exe to PATH** box ticked |
| Nothing seems to happen | Make sure you extracted the ZIP first (Step 1.3) — the installer window always stays open now, so read what it says |
| "game not found" in the wizard | Paste the folder that contains `eqgame.exe` when it asks |
| App opens but everything says waiting | Type `/log on` in game — the companion reads your combat log |
