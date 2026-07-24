@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Location for storing last inputs (next to this script)
set SCRIPT_DIR=%~dp0
set CFG_DIR=%SCRIPT_DIR%cfg
if not exist "%CFG_DIR%" mkdir "%CFG_DIR%"
set HISTORY_FILE=%CFG_DIR%\history_input_02.txt

REM Defaults
set DEF_PY=D:/Programming/Python_dir_38/python.exe
set DEF_INPUT_DIR=./input/excel_directories.txt
set DEF_OUTPUT_DIR=./output
set DEF_KW_FILE=./input/word_excel_keywords.txt
set DEF_INSTALL_DEPS=Y

set file_type=xlsx

call entry.bat

:END
endlocal
pause
