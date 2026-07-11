@echo off
rem EQL Companion launcher - starts backend (FastAPI :8000) and frontend (Next.js :3000)

start "EQL Companion - Backend" cmd /k "cd /d G:\projects\eql_mods && call conda activate eql-companion && uvicorn backend.main:app --reload"

start "EQL Companion - Frontend" cmd /k "cd /d G:\projects\eql_mods\frontend && npm run dev"

rem Give the servers a moment, then open the dashboard
timeout /t 6 /nobreak >nul
start "" http://localhost:3000