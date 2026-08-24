@echo off
REM Starts the portal and keeps it running. Logs to data\server.log so a
REM crash leaves evidence instead of just vanishing.
cd /d "%~dp0"
if not exist frontend\dist (
  echo Frontend not built yet - building now...
  call build-ui.bat
  cd /d "%~dp0"
)
if not exist data mkdir data

:start
echo.
echo   Job Mania running at http://127.0.0.1:8000
echo   Log: data\server.log      Press Ctrl+C twice to stop.
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> data\server.log 2>&1
echo.
echo   Server stopped (exit %errorlevel%). Restarting in 5s - Ctrl+C to quit.
timeout /t 5 >nul
goto start
