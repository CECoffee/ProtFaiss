@echo off
REM dev.bat — Start daemon, API backend, and Vue frontend.
REM Usage: scripts\dev.bat

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

REM Daemon
echo [daemon] Starting core daemon on 127.0.0.1:9812 ...
start /b "" python -m app.daemon
set "DAEMON_STARTED=1"

REM Wait for daemon to be ready
echo [daemon] Waiting for daemon to start...
set /a TRIES=0
:wait_loop
set /a TRIES+=1
python -c "import socket,sys; s=socket.create_connection(('127.0.0.1',9812),timeout=1); s.close(); sys.exit(0)" 2>nul
if %errorlevel%==0 (
    echo [daemon] Ready.
    goto daemon_ready
)
if %TRIES% geq 30 (
    echo [daemon] ERROR: Daemon did not start in 30s. Check logs.
    goto cleanup
)
timeout /t 1 /nobreak >nul
goto wait_loop

:daemon_ready

REM API
echo [api] Starting FastAPI on http://localhost:8000 ...
start /b "" uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

REM Frontend
cd /d "%PROJECT_ROOT%\frontend"
echo [frontend] Starting Vite dev server on http://localhost:5173 ...
start /b "" npm run dev

echo.
echo   Daemon   ^-^> 127.0.0.1:9812 (IPC)
echo   Backend  ^-^> http://localhost:8000
echo   Frontend ^-^> http://localhost:5173
echo   CLI      ^-^> python -m app.cli
echo.
echo Press Ctrl+C to stop all.

:keep_alive
timeout /t 5 /nobreak >nul
goto keep_alive

:cleanup
echo Shutting down...
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im node.exe >nul 2>&1
exit /b 1
