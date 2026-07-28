@echo off
REM ============================================================
REM HN_Agent - Restart and verify (kill + start + health check)
REM ============================================================
SETLOCAL EnableDelayedExpansion
SET "PROJECT_DIR=%~dp0"
SET "PORT=8000"

cd /d "%PROJECT_DIR%"

echo ============================================================
echo  Step 1 of 3: Kill old process on port %PORT%
echo ============================================================
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    echo [~] Killing PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo [+] Step 1 done.

echo.
echo ============================================================
echo  Step 2 of 3: Start server in background
echo ============================================================

REM Locate absolute path to python.exe from PATH
SET "PY_EXE="
FOR /F "delims=" %%P IN ('where python 2^>nul') DO (
    IF NOT DEFINED PY_EXE SET "PY_EXE=%%P"
)
IF NOT DEFINED PY_EXE (
    echo [X] python.exe not found in PATH.
    exit /b 1
)
echo [~] Using python: %PY_EXE%
echo [~] Working dir: %PROJECT_DIR%

REM Launch in background. stdout/stderr from this launcher goes to _stdout.log
REM (server.py owns server.log; do not collide).
start /B "HN_Agent" "%PY_EXE%" server.py 1>_stdout.log 2>&1

echo [+] Launch command issued.

REM Poll /api/health until it answers 200 (max ~60s)
echo [~] Waiting for http://localhost:%PORT%/api/health ...
SET /A TRIES=0
:WAIT_LOOP
SET /A TRIES+=1
powershell -NoProfile -Command "(try { (Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode } catch { '0' })" > _health.txt 2>&1
SET /P HEALTH=<_health.txt
del _health.txt >nul 2>&1
IF "!HEALTH!"=="200" GOTO HEALTH_OK
IF !TRIES! GEQ 30 (
    echo [X] Server did not respond after 60s.
    echo.
    echo ----- _stdout.log (last 30 lines) -----
    IF EXIST _stdout.log (
        powershell -NoProfile -Command "Get-Content '_stdout.log' -Tail 30"
    ) ELSE (
        echo ^(file missing^)
    )
    echo.
    echo ----- server.log (last 30 lines) -----
    IF EXIST server.log (
        powershell -NoProfile -Command "Get-Content 'server.log' -Tail 30"
    ) ELSE (
        echo ^(file missing^)
    )
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto WAIT_LOOP

:HEALTH_OK
echo [+] Server is up!

echo.
echo ============================================================
echo  Step 3 of 3: Run health check + sample query
echo ============================================================
echo.
echo ----- GET /api/health -----
powershell -NoProfile -Command "(Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/health' -UseBasicParsing).Content"
echo.
echo.
echo ----- POST /api/query (no token, expects 401) -----
powershell -NoProfile -Command ^
  "$body = '{\"question\":\"\u6211\u6709\u591a\u5c11\u5929\u5e74\u5047\uff1f\",\"top_k\":3}';" ^
  "try {" ^
  "  $r = Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/query' -Method POST -ContentType 'application/json; charset=utf-8' -Body $body -UseBasicParsing;" ^
  "  Write-Host ('status: ' + $r.StatusCode + ' body: ' + $r.Content)" ^
  "} catch { Write-Host ('status: ' + $_.Exception.Response.StatusCode.value__ + ' message: ' + $_.Exception.Message) }"

echo.
echo ----- POST /api/auth/login (admin) -----
powershell -NoProfile -Command ^
  "$body = '{\"email\":\"admin@example.com\",\"password\":\"admin123\"}';" ^
  "try {" ^
  "  $r = Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/auth/login' -Method POST -ContentType 'application/json; charset=utf-8' -Body $body -UseBasicParsing;" ^
  "  $j = $r.Content | ConvertFrom-Json;" ^
  "  Write-Host ('login ok: ' + $j.user.email + ' roles=' + ($j.user.roles -join ',') + ' is_admin=' + $j.user.is_admin)" ^
  "  Write-Host ('token len: ' + $j.access_token.Length);" ^
  "  $global:TOKEN = $j.access_token" ^
  "} catch { Write-Host ('login failed: ' + $_.Exception.Message) }"

echo.
echo ============================================================
echo  Server is running on http://localhost:%PORT%
echo  python logs:    server.log    (managed by server.py)
echo  stdout/stderr:  _stdout.log   (from this launcher)
echo  Stop:           stop.bat      (or taskkill /IM python.exe /F)
echo ============================================================
ENDLOCAL