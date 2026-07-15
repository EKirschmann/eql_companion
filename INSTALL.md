# Installing the EQL Companion — the plain-language guide

No experience needed. You do NOT need git, GitHub knowledge, or anything a
programmer uses — just two free installs and a ZIP file. Total time: about
ten minutes, most of it watching progress bars.

## Step 1 — Install Python (one time)

1. Go to <https://www.python.org/downloads/> and click the big yellow
   **Download Python** button.
2. Run the file it downloads. **IMPORTANT: on the first screen, tick the
   checkbox that says "Add python.exe to PATH"** (bottom of the window) —
   this is the one step people miss.
3. Click **Install Now** and let it finish.

## Step 2 — Install Node.js (one time)

1. Go to <https://nodejs.org/> and download the **LTS** version.
2. Run it. Next → Next → Finish. No checkboxes to worry about.

## Step 3 — Download the companion

1. Go to <https://github.com/EKirschmann/eql_companion>.
2. Click the green **<> Code** button → **Download ZIP**.
3. Find the ZIP in your Downloads, **right-click it → Extract All…** and
   put it somewhere easy, like `Documents\eql_companion`.
   **Do not skip extracting** — opening the ZIP and double-clicking inside
   it will not work.

## Step 4 — Run the installer

1. Open the extracted folder and double-click **install_companion.bat**.
   - If Windows shows a blue "protected your PC" box: click **More info**,
     then **Run anyway**. (It is a plain script — you can open it in
     Notepad and read it.)
2. It installs the app's pieces (a few minutes), then asks a few questions:
   - It finds your EverQuest Legends folder by itself on most PCs — press
     **Enter** to accept.
   - It offers to download the community map pack — say **y**.
   - Counsel model: press **Enter** for **None**. Everything works without
     one; you can change this later inside the app.
3. When it offers to launch — say yes. A browser tab opens with your HUD.

## Step 5 — In the game (once per character)

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
| "python is not recognized" | Re-run the Python installer, tick **Add python.exe to PATH**, then run install_companion.bat again |
| The window flashes and closes instantly | You ran it from inside the ZIP — extract first (Step 3.3) |
| "game not found" in the wizard | Paste the folder that contains `eqgame.exe` when it asks |
| App opens but everything says waiting | Type `/log on` in game — the companion reads your combat log |
