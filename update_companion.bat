@echo off
rem EQL Companion - updater: pull the latest release and refresh dependencies.
rem Close the companion (backend + frontend windows) before running.
cd /d %~dp0

if not exist .git (
  echo This copy was installed from a ZIP - no git needed, updating is manual:
  echo   1. Download the new ZIP: https://github.com/EKirschmann/eql_companion
  echo      ^(green "Code" button -^> Download ZIP^)
  echo   2. Extract it OVER this folder, replacing files when asked.
  echo   Your settings ^(.env^) and data folder are yours and stay untouched.
  echo   3. Run install_companion.bat once afterward to refresh dependencies.
  pause
  exit /b 0
)

echo Pulling the latest version...
git pull --ff-only || (echo. & echo Update failed - if you edited tracked files, run "git stash" first. & pause & exit /b 1)

echo Refreshing Python dependencies...
pip install -q -r requirements.txt

echo Refreshing frontend dependencies...
pushd frontend
call npm install --silent
popd

echo.
echo Updated. Start it again with start_companion.bat
pause
