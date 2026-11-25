@echo off
rem Python is auto-detected (no prompt). Edit the candidate list below if needed.
rem Requirement: a Python 3.6+ interpreter with pygame installed.
cd /d "%~dp0"

rem ========== choose renderer ==========
echo.
echo   Mini Race 2
echo   -------------
echo   1. 2D interface (pygame, default)
echo   2. 3D interface (Panda3D prototype)
echo.
set "RENDER_CHOICE="
set /p "RENDER_CHOICE=Select [1/2, Enter = 2D]: "
if "%RENDER_CHOICE%"=="2" (
    call "%~dp003_Run3D.bat" %*
    exit /b %errorlevel%
)
if /i "%RENDER_CHOICE%"=="3D" (
    call "%~dp003_Run3D.bat" %*
    exit /b %errorlevel%
)

rem ========== pick a Python interpreter that has pygame ==========
rem Candidates are tried in order; the first one that imports pygame wins.
set "PYTHON_CMD="
for %%P in (
    "D:\Programming\Python_dir_38\python.exe"
    "D:\Program Files\Python36\python.exe"
    "D:\Python314\python.exe"
    "D:\Programming\Python_dir_3133\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if not defined PYTHON_CMD if exist %%P (
        %%P -c "import pygame" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%~P""
    )
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD (
        "%%P" -c "import pygame" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%P""
    )
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where py 2^>nul') do (
    if not defined PYTHON_CMD (
        py -3 -c "import pygame" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python with pygame found.
    echo.
    echo Install pygame for one of these interpreters, or add its path to the
    echo candidate list at the top of 01_Run.bat:
    echo     D:\Programming\Python_dir_38\python.exe   ^(Python 3.8 + pygame 2.6.1^)
    echo     D:\Program Files\Python36\python.exe      ^(Python 3.6 + pygame 2.0.0^)
    echo.
    echo e.g.  "D:\Programming\Python_dir_38\python.exe" -m pip install pygame
    echo.
    pause
    exit /b 1
)

rem ========== launch the simulator without a console window ==========
rem python.exe -> pythonw.exe, so the console does not stay open behind the game
set "PYTHONW=%PYTHON_CMD%"
set "PYTHONW=%PYTHONW:python.exe=pythonw.exe%"
if /i "%PYTHONW%"=="%PYTHON_CMD%" set "PYTHONW="

set "RUN_LOG=%~dp0logs\run.log"
if not exist "%~dp0logs" mkdir "%~dp0logs"
rem drop the previous run log: a missing log after the check means the GUI never got going
del "%RUN_LOG%" >nul 2>&1

if not defined PYTHONW goto RUN_IN_CONSOLE

start "" %PYTHONW% scripts\main.py %*

rem wait ~3 seconds, then close this console window by itself
ping -n 4 127.0.0.1 >nul 2>&1

if not exist "%RUN_LOG%" goto STARTUP_FAILED
findstr /c:"Traceback" "%RUN_LOG%" >nul 2>&1
if not errorlevel 1 goto STARTUP_FAILED

exit /b 0

:STARTUP_FAILED
echo.
echo [ERROR] The simulator failed to start.
if exist "%RUN_LOG%" (
    echo ---------------------------------------------------------------
    chcp 65001 >nul
    type "%RUN_LOG%"
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
    echo [ERROR] The simulator exited with an error. See the log above.
    pause
    exit /b 1
)
