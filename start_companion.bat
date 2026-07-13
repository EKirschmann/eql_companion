@echo off
rem EQL Companion launcher - backend (FastAPI :8000) + frontend (Next.js :3000)
rem Runs from wherever the repo lives. If you use a venv/conda env, activate
rem it first (or edit the ACTIVATE line below).
set ACTIVATE=call conda activate eql-companion 2^>nul

start "EQL Companion - Backend" cmd /k "cd /d %~dp0 && %ACTIVATE% & uvicorn backend.main:app --reload"

start "EQL Companion - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

rem Give the servers a moment, then open the dashboard
timeout /t 6 /nobreak >nul
start "" http://localhost:3000
