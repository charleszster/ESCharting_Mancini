@echo off
start "ES Backend"  cmd /k "cd /d %~dp0backend  && venv\Scripts\activate && uvicorn main:app --reload"
start "ES Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
