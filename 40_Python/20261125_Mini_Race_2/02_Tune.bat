@echo off
rem Tuning console launcher: find a Python with tkinter (no pygame needed).
cd /d "%~dp0"

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
        %%P -c "import tkinter" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%~P""
    )
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD (
        "%%P" -c "import tkinter" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%P""
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python with tkinter found.
    echo         Reinstall Python with the "tcl/tk and IDLE" option enabled,
    echo         or add its path to the candidate list in 02_Tune.bat.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%
"%PYTHON_CMD%" scripts\tune_panel.py
if errorlevel 1 (
    echo.
    echo [ERROR] The tuning console exited with an error.
    pause
    exit /b 1
)
