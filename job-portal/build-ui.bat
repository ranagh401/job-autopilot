@echo off
REM Rebuilds the React frontend into frontend\dist (served by the backend).
REM Invokes vite via node directly - npm's shim breaks on paths containing "&".
cd /d "%~dp0frontend"
if not exist node_modules (
  echo Installing frontend dependencies...
  call npm install --no-audit --no-fund
)
node node_modules\vite\bin\vite.js build
echo.
echo UI rebuilt. Restart run.bat if the server is not already running.
