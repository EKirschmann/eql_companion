@echo off
rem EQL Companion launcher - backend (:8000) + frontend (:3000).
rem Default = production mode: no file watchers, no hot reload, ~350MB less
rem RAM. Developers: start_companion.bat dev
cd /d %~dp0
if /i "%~1"=="dev" goto devmode

start "EQL Companion - Backend" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & uvicorn backend.main:app"
start "EQL Companion - Frontend" cmd /k "cd /d %~dp0frontend && set NEXT_DIST_DIR=.next-prod&& npm run start"
goto open

:devmode
start "EQL Companion - Backend (dev)" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & uvicorn backend.main:app --reload"
start "EQL Companion - Frontend (dev)" cmd /k "cd /d %~dp0frontend && npm run dev"

:open
timeout /t 6 /nobreak >nul
start "" http://localhost:3000
