@echo off
rem EQL Companion - one-shot installer: dependencies + guided setup.
rem Offers to install Python / Node.js automatically via winget when missing.
rem The first line relaunches under "cmd /k" so this window NEVER closes by
rem itself - whatever happens, the user can read it.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

rem ---- Python (the MS-Store stub fails this check too, which is correct) --
:checkpy
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto havepy
echo.
echo Python 3.11+ was not found on this PC.
where winget >nul 2>nul
if errorlevel 1 goto manualpy
if defined TRIED_PY goto manualpy
choice /c YN /m "Install Python automatically now (uses winget)"
if errorlevel 2 goto manualpy
set TRIED_PY=1
echo Installing Python via winget - this takes a minute...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1"
call :refreshpath
goto checkpy
:manualpy
echo.
echo Please install Python yourself: https://www.python.org/downloads/
echo IMPORTANT: tick "Add python.exe to PATH" on the first screen.
echo Then run install_companion.bat again.
pause
exit /b 1
:havepy

rem ---- Node.js ------------------------------------------------------------
:checknode
call npm --version >nul 2>nul
if not errorlevel 1 goto havenode
echo.
echo Node.js was not found on this PC.
where winget >nul 2>nul
if errorlevel 1 goto manualnode
if defined TRIED_NODE goto manualnode
choice /c YN /m "Install Node.js automatically now (uses winget)"
if errorlevel 2 goto manualnode
set TRIED_NODE=1
echo Installing Node.js LTS via winget - this takes a minute...
winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
call :refreshpath
goto checknode
:manualnode
echo.
echo Please install Node.js yourself: https://nodejs.org/ (the LTS version).
echo Then run install_companion.bat again.
pause
exit /b 1
:havenode

echo Installing Python dependencies...
pip install -r requirements.txt || (echo pip install failed & pause & exit /b 1)

echo Installing frontend dependencies...
pushd frontend
call npm install || (echo npm install failed & pause & exit /b 1)
echo Building the interface (one time, about a minute)...
set NEXT_DIST_DIR=.next-prod
call npm run build || (echo interface build failed & pause & exit /b 1)
set NEXT_DIST_DIR=
popd

python setup_wizard.py

echo.
set /p LAUNCH="Launch the companion now? (Y/n): "
if /i not "%LAUNCH%"=="n" call start_companion.bat
echo.
echo All done - you can close this window.
exit /b 0

rem ---- re-read PATH from the registry so a just-installed tool is found
rem ---- in THIS window (a fresh install only lands on future consoles)
:refreshpath
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%p"
exit /b 0
