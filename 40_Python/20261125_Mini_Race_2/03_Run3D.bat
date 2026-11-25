@echo off
rem Panda3D 3D prototype launcher (physics still uses scripts/minirace)
rem Requires Python 3.8 + panda3d (pip install panda3d)
cd /d "%~dp0"

set "PYTHON_CMD=D:\Programming\Python_dir_38\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
"%PYTHON_CMD%" -c "import panda3d" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No Python with panda3d found.
    echo         Install it with: python -m pip install panda3d
    echo         Recommended: D:\Programming\Python_dir_38\python.exe
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%
"%PYTHON_CMD%" scripts\main3d.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] The 3D prototype exited with an error.
    pause
    exit /b 1
)
