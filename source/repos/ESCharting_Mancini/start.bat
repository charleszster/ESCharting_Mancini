@echo off
cd /d %~dp0

echo Starting ES backend...
start "ES Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && uvicorn main:app --reload"
timeout /t 2 /nobreak >nul

echo Starting ES frontend (Ctrl+C here to stop both)...
cd /d %~dp0frontend && npm run dev

echo.
echo Frontend stopped. Killing backend...
taskkill /fi "WindowTitle eq ES Backend*" /t /f >nul 2>&1
echo Done.
