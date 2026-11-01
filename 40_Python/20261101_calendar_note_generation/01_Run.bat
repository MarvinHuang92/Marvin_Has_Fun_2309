@echo off
rem ================================================================
rem  Calendar Note Generator - one click launcher.
rem  Python is detected automatically (no prompt). If your Python is
rem  somewhere else, just add its full path to the list below.
rem ================================================================
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
for %%P in (
    "D:\Programming\Python_dir_38\python.exe"
    "D:\Python314\python.exe"
    "D:\Programming\Python_dir_3133\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if not defined PYTHON_CMD if exist %%P set "PYTHON_CMD=%%~P"
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD=%%P"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found on this machine.
    echo         Install Python 3, or add its path to the list inside this bat file.
    echo.
    pause
    exit /b 1
)

"%PYTHON_CMD%" -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3 is required, but this one is not Python 3:
    echo         %PYTHON_CMD%
    echo.
    pause
    exit /b 1
)

rem ---------- make sure the libraries in dependencies.txt are there ----------
"%PYTHON_CMD%" "%~dp0scripts\check_dependencies.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Required libraries are missing. See the messages above.
    echo.
    pause
    exit /b 1
)

rem ---------- generate the calendar workbook ----------
"%PYTHON_CMD%" "%~dp0scripts\generate_calendar.py"
if errorlevel 1 (
    echo.
    echo [ERROR] The calendar file was not generated. See the messages above.
    echo.
    pause
    exit /b 1
)

exit /b 0