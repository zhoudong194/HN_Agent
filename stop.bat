@echo off
REM ============================================================
REM HN_Agent - Stop server (kill anything on port 8000)
REM ============================================================
SETLOCAL EnableDelayedExpansion
SET "PORT=8000"

echo [*] Looking for process on port %PORT%...
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    echo [~] Killing PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
    IF !ERRORLEVEL! EQU 0 (
        echo [OK] Killed PID %%P
    ) ELSE (
        echo [!] Failed to kill PID %%P
    )
)
echo [+] Done.
ENDLOCAL
