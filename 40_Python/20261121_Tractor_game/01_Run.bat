@echo off
rem Python is auto-detected (no prompt). Edit the candidate list below if needed.
cd /d "%~dp0"

rem ========== pick a Python interpreter (first one that exists wins) ==========
set "PYTHON_CMD="
for %%P in (
    "D:\Python314\python.exe"
    "D:\Programming\Python_dir_38\python.exe"
    "D:\Programming\Python_dir_3133\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if not defined PYTHON_CMD if exist %%P set "PYTHON_CMD="%%~P""
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD="%%P""
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where py 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found. Install Python 3 or add its path to the candidate list in this bat.
    echo.
    pause
    exit /b 1
)

rem ========== make sure tkinter is available ==========
%PYTHON_CMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The python below has no tkinter support:
    echo         %PYTHON_CMD%
    echo         Reinstall Python with the "tcl/tk and IDLE" option enabled.
    echo.
    pause
    exit /b 1
)

rem ========== launch the GUI without a console window ==========
rem python.exe -> pythonw.exe, so the GUI does not keep this console alive
set "PYTHONW=%PYTHON_CMD%"
set "PYTHONW=%PYTHONW:python.exe=pythonw.exe%"
if /i "%PYTHONW%"=="%PYTHON_CMD%" set "PYTHONW="

if not defined PYTHONW goto RUN_IN_CONSOLE

for /f "tokens=2 delims=:" %%C in ('chcp') do set "OLDCP=%%C"
if not exist "%~dp0logs" mkdir "%~dp0logs"
rem drop the previous run log: a missing log after the check means the GUI never got going
del "%~dp0logs\run.log" >nul 2>&1

start "" %PYTHONW% scripts\main.py %*

rem wait ~3 seconds, then close this console window by itself
ping -n 4 127.0.0.1 >nul 2>&1

if not exist "%~dp0logs\run.log" goto STARTUP_FAILED
findstr /c:"Traceback" "%~dp0logs\run.log" >nul 2>&1
if not errorlevel 1 goto STARTUP_FAILED
findstr /c:"启动失败" "%~dp0logs\run.log" >nul 2>&1
if not errorlevel 1 goto STARTUP_FAILED

exit /b 0

:STARTUP_FAILED
echo.
echo [ERROR] The game failed to start.
if exist "%~dp0logs\run.log" (
    echo ---------------------------------------------------------------
    chcp 65001 >nul
    type "%~dp0logs\run.log"
    chcp %OLDCP% >nul
    echo ---------------------------------------------------------------
) else (
    echo No log was written - the script died before logging started.
    echo Run it manually to see the error:
    echo     %PYTHON_CMD% scripts\main.py
)
echo Close this window when you are done reading.
pause
exit /b 1

:RUN_IN_CONSOLE
rem fallback: no pythonw.exe found, keep the console attached
echo Using Python: %PYTHON_CMD%
%PYTHON_CMD% scripts\main.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] The game exited with an error. See the log above.
    pause
    exit /b 1
)
