@echo off
rem EQL Companion launcher - backend (:8000) + frontend (:3000).
rem Default = production mode (fast, light). It auto-rebuilds the UI when
rem source changed since the last build, so you never see a stale version.
rem Developers iterating rapidly: start_companion.bat dev  (hot reload)
cd /d %~dp0
if /i "%~1"=="dev" goto devmode

rem --- rebuild the production UI only if source is newer than the last build
set NEED=0
if not exist frontend\next-prod\BUILD_ID set NEED=1
if "%NEED%"=="0" (
  powershell -NoProfile -Command "$b=(Get-Item 'frontend/.next-prod/BUILD_ID').LastWriteTime; $n=Get-ChildItem -Recurse frontend/app,frontend/components,frontend/lib,frontend/next.config.js -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $b } | Select-Object -First 1; if($n){exit 1}else{exit 0}"
  if errorlevel 1 set NEED=1
)
if "%NEED%"=="1" (
  echo Building the interface ^(source changed - about a minute^)...
  pushd frontend
  set NEXT_DIST_DIR=.next-prod
  call npm run build || (echo UI build failed & popd & pause & exit /b 1)
  set NEXT_DIST_DIR=
  popd
)

start "EQL Companion - Backend" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & uvicorn backend.main:app"
start "EQL Companion - Frontend" cmd /k "cd /d %~dp0frontend && set NEXT_DIST_DIR=.next-prod&& npm run start"
goto open

:devmode
start "EQL Companion - Backend (dev)" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & uvicorn backend.main:app --reload"
start "EQL Companion - Frontend (dev)" cmd /k "cd /d %~dp0frontend && npm run dev"

:open
timeout /t 6 /nobreak >nul
start "" http://localhost:3000
