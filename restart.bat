@echo off
echo ========================================
echo   MES NL2SQL Service Restart
echo ========================================

echo.
echo [1] Stopping old processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    echo     Found PID: %%a
    taskkill /F /PID %%a /T >nul 2>&1
    if errorlevel 1 (
        echo     PID %%a not found
    ) else (
        echo     Killed PID %%a
    )
)

echo.
echo [2] Waiting for port release...
timeout /t 2 /nobreak >nul

echo.
echo [3] Starting new service...
cd /d "%~dp0"
uv run python src/main.py