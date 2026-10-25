@echo off
rem ============================================================
rem  PersonalProfile one-click service control
rem  Usage:
rem    pp.bat            start web server (default) + open browser
rem    pp.bat start      same as above
rem    pp.bat stop       kill the web server on port 8765
rem    pp.bat restart    stop + start
rem    pp.bat status     show whether the service is running
rem ============================================================
setlocal
set PY=C:\Users\32025\.workbuddy\binaries\python\versions\3.13.12\python.exe
set ROOT=E:\doc\workbuddy\PersonalProfile
set PORT=8765

if "%~1"=="stop"    goto stop
if "%~1"=="status"  goto status
if "%~1"=="restart" goto restart
if "%~1"=="start"   goto start
if "%~1"==""        goto start
echo [pp] unknown arg: %~1  (use start / stop / restart / status)
goto :eof

:check_running
netstat -ano | findstr "LISTENING" | findstr ":%PORT% " >nul
goto :eof

:start
call :check_running
if not errorlevel 1 (
    echo [pp] already running on port %PORT%, nothing to do.
    goto :eof
)
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
start "pp-web" /min cmd /c ""%PY%" -m personal_profile.web.server >> "%ROOT%\logs\service.log" 2>&1"
rem wait until the port is listening (max ~10s)
set /a tries=0
:wait_loop
ping -n 2 127.0.0.1 >nul
call :check_running
if errorlevel 1 (
    set /a tries+=1
    if %tries% lss 10 goto wait_loop
    echo [pp] ERROR: server did not come up, see %ROOT%\logs\service.log
    goto :eof
)
echo [pp] web server started: http://127.0.0.1:%PORT%/
start "" "http://127.0.0.1:%PORT%/"
goto :eof

:stop
call :check_running
if errorlevel 1 (
    echo [pp] not running.
    goto :eof
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%PORT% "') do taskkill /F /PID %%p >nul 2>&1
ping -n 2 127.0.0.1 >nul
call :check_running
if errorlevel 1 (echo [pp] stopped.) else (echo [pp] ERROR: still running, kill it manually.)
goto :eof

:restart
call %0 stop
call %0 start
goto :eof

:status
call :check_running
if errorlevel 1 (echo [pp] status: STOPPED) else (echo [pp] status: RUNNING on port %PORT%)
goto :eof
