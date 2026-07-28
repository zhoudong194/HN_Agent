@echo off
REM ============================================================
REM HN_Agent - Restart server (kill old + start fresh)
REM ============================================================
SETLOCAL EnableDelayedExpansion
SET "PROJECT_DIR=%~dp0"
SET "PORT=8000"

cd /d "%PROJECT_DIR%"

echo [*] Looking for process on port %PORT%...

SET "KILLED=0"
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    echo [~] Killing PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
    IF !ERRORLEVEL! EQU 0 (
        SET "KILLED=1"
        echo [OK] Killed PID %%P
    ) ELSE (
        echo [!] Failed to kill PID %%P
    )
)

IF %KILLED% EQU 0 (
    echo [i] No process was using port %PORT%
)

REM Wait for the OS to release the socket
timeout /t 2 /nobreak >nul

REM Verify port is now free
netstat -aon | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
IF !ERRORLEVEL! NEQ 0 (
    echo [+] Port %PORT% is now free.
) ELSE (
    echo [X] Port %PORT% still busy. Aborting.
    exit /b 1
)

echo [+] Starting server...
python server.py 2>nul
ENDLOCAL
