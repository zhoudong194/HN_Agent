@echo off
REM ============================================================
REM HN_Agent - Start server
REM ============================================================
SETLOCAL
SET "PROJECT_DIR=%~dp0"
SET "PORT=8000"

cd /d "%PROJECT_DIR%"

REM Check if port is in use
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    echo [X] Port %PORT% is already in use by PID %%P
    echo     Run restart.bat instead, or:
    echo     taskkill /PID %%P /F
    exit /b 1
)

echo [+] Port %PORT% is free. Starting server...
python server.py
ENDLOCAL
