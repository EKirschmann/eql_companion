@echo off
rem EQL Companion - updater. Close the companion windows before running.
rem Git installs update via git; ZIP installs update via the Python
rem downloader - no git needed either way. Relaunches under cmd /k so the
rem window never closes before it can be read.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

if exist .git goto gitpath

python update_companion.py
pause
exit /b 0

:gitpath
echo Pulling the latest version...
git pull --ff-only || (echo. & echo Update failed - if you edited tracked files, run "git stash" first. & pause & exit /b 1)

echo Refreshing Python dependencies...
pip install -q -r requirements.txt

echo Refreshing frontend dependencies...
pushd frontend
call npm install --silent
echo Rebuilding the interface (about a minute)...
set NEXT_DIST_DIR=.next-prod
call npm run build
set NEXT_DIST_DIR=
popd

echo.
echo Updated. Start it again with start_companion.bat
pause
