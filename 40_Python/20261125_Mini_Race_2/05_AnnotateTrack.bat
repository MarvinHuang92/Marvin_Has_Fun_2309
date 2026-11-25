@echo off
rem Semi-automatic track annotation launcher.
rem Defaults to the Baoshan map; press Enter to accept the defaults.
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
        %%P -c "import tkinter, PIL, cv2, scipy, numpy" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%~P""
    )
)
if not defined PYTHON_CMD for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD (
        "%%P" -c "import tkinter, PIL, cv2, scipy, numpy" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD="%%P""
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python with tkinter + Pillow + opencv + scipy + numpy found.
    echo.
    echo Use the Python 3.8 environment and install the build dependencies:
    echo     "D:\Programming\Python_dir_38\python.exe" -m pip install pillow opencv-python scipy numpy
    echo.
    pause
    exit /b 1
)

echo.
echo   Mini Race 2 - track corner annotator
echo   -----------------------------------
echo   Default image: images\track_baoshan_kartin.bmp
echo   Default track: cfg\tracks\track_baoshan.json
echo.
echo   Drag an image onto this .bat to use it as the image.
echo.

set "IMAGE=%~1"
if not defined IMAGE (
    set /p "IMAGE=Image path [Enter = default]: "
)
if not defined IMAGE set "IMAGE=images\track_baoshan_kartin.bmp"

set "TRACK=%~2"
if not defined TRACK (
    set /p "TRACK=Track JSON path [Enter = default]: "
)
if not defined TRACK set "TRACK=cfg\tracks\track_baoshan.json"

set "OUT=%~3"
if not defined OUT (
    set /p "OUT=Output JSON path [Enter = same as track]: "
)
if not defined OUT set "OUT=%TRACK%"

if not exist "%IMAGE%" (
    echo [ERROR] Image not found: %IMAGE%
    pause
    exit /b 1
)
if not exist "%TRACK%" (
    echo [ERROR] Track JSON not found: %TRACK%
    pause
    exit /b 1
)

echo.
echo Using Python: %PYTHON_CMD%
echo Image:  %IMAGE%
echo Track:  %TRACK%
echo Output: %OUT%
echo.
"%PYTHON_CMD%" scripts\annotate_track.py --image "%IMAGE%" --track "%TRACK%" --out "%OUT%"
if errorlevel 1 (
    echo.
    echo [ERROR] The annotator exited with an error.
    pause
    exit /b 1
)
