@echo off
rem EQL Companion - updater: pull the latest release and refresh dependencies.
rem Close the companion (backend + frontend windows) before running.
cd /d %~dp0

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
