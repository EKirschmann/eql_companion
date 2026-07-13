@echo off
rem EQL Companion - one-shot installer: dependencies + guided setup.
cd /d %~dp0

where python >nul 2>nul || (echo Python 3.11+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
where npm    >nul 2>nul || (echo Node.js 18+ is required: https://nodejs.org/ & pause & exit /b 1)

echo Installing Python dependencies...
pip install -r requirements.txt || (echo pip install failed & pause & exit /b 1)

echo Installing frontend dependencies...
pushd frontend
call npm install || (echo npm install failed & pause & exit /b 1)
popd

python setup_wizard.py

echo.
set /p LAUNCH="Launch the companion now? (Y/n): "
if /i not "%LAUNCH%"=="n" call start_companion.bat
