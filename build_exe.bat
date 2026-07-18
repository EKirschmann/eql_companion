@echo off
rem Build the LITE single-file EQL Companion executable (deterministic mode:
rem no OCR, no LLM). Produces dist\EQLCompanion.exe with no runtime deps.
rem Prereqs on the BUILD machine only: Python 3.11+, Node 18+.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

echo [1/5] Python build deps (lite set + pyinstaller + pywebview)...
pip install -r requirements-lite.txt pyinstaller pywebview || (echo pip failed & exit /b 1)

echo [2/5] Building the static UI...
pushd frontend
call npm install || (echo npm install failed & popd & exit /b 1)
set NEXT_EXPORT=1
call npm run build || (echo UI build failed & popd & exit /b 1)
set NEXT_EXPORT=
popd

echo [3/5] Bundling the eqlbuilds data snapshot (exact spell/AA levels)...
if not exist data\eqlbuilds mkdir data\eqlbuilds
if exist "%MCP_SERVER_DIR%\dist\data\eqlbuilds\classes.json" (
  copy /y "%MCP_SERVER_DIR%\dist\data\eqlbuilds\classes.json" data\eqlbuilds\ >nul
) else (
  echo   ^(no MCP snapshot found - the exe will fall back to wiki HTTP for levels^)
)

echo [4/5] Running PyInstaller...
pyinstaller --noconfirm --onefile --name EQLCompanion ^
  --add-data "frontend/out;frontend/out" ^
  --add-data "data/eqlbuilds;data/eqlbuilds" ^
  --collect-submodules backend ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  run_companion.py || (echo PyInstaller failed & exit /b 1)

echo [5/5] Done -> dist\EQLCompanion.exe
echo Ship that single file. Users need nothing installed. First run creates
echo data\ next to it and reads logs per .env (EQL_GAME_DIR).
