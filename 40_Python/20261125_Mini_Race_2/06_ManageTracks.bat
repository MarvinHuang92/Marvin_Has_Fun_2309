@echo off
rem Mini Race 2 - track candidate manager (tkinter).
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
        %%P -c "import tkinter, cv2, scipy, shapely, numpy" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%~P""
    )
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD (
        "%%P" -c "import tkinter, cv2, scipy, shapely, numpy" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%P""
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python with tkinter + opencv + scipy + shapely + numpy found.
    echo Use the Python 3.8 environment:
    echo     "D:\Programming\Python_dir_38\python.exe" -m pip install opencv-python scipy shapely numpy
    pause
    exit /b 1
)

"%PYTHON_CMD%" scripts\track_manager_gui.py
if errorlevel 1 (
    echo.
    echo [ERROR] Track Manager exited with an error.
    pause
    exit /b 1
)
