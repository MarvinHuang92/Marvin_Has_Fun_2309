@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Location for storing last inputs (next to this script)
set SCRIPT_DIR=%~dp0
set CFG_DIR=%SCRIPT_DIR%cfg
if not exist "%CFG_DIR%" mkdir "%CFG_DIR%"
set HISTORY_FILE=%CFG_DIR%\history_input_03.txt

REM Defaults
set DEF_PY=C:/TCC/Tools/python3/3.7.4-29_WIN64_2/python.exe
set DEF_ATTCH_DIR=./attachments
set DEF_OUTPUT_DIR=./output

REM Load history if present (skip first two header lines)
if exist "%HISTORY_FILE%" (
	set "COUNT=0"
	for /f "usebackq tokens=* delims=" %%A in ("%HISTORY_FILE%") do (
		set /a COUNT+=1
		if !COUNT! LEQ 2 (
			rem skip header lines
		) else if not defined LINE1 (
			set "LINE1=%%A"
		) else if not defined LINE2 (
			set "LINE2=%%A"
		) else if not defined LINE3 (
			set "LINE3=%%A"
		)
	)
	rem Expect 3 values in history: PY_PATH, ATTCH_DIR, OUTPUT_DIR
	if defined LINE3 (
		set "DEF_PY=!LINE1!"
		set "DEF_ATTCH_DIR=!LINE2!"
		set "DEF_OUTPUT_DIR=!LINE3!"
	)
)

REM Sanitize loaded defaults: remove trailing ')' if present
if not "%DEF_PY%"=="" goto SAN_DEF_PY
goto AFTER_SAN_DEF_PY
:SAN_DEF_PY
if "%DEF_PY:~-1%"==")" set "DEF_PY=%DEF_PY:~0,-1%"
:AFTER_SAN_DEF_PY
if not "%DEF_ATTCH_DIR%"=="" goto SAN_DEF_ATTCH_DIR
goto AFTER_SAN_DEF_ATTCH_DIR
:SAN_DEF_ATTCH_DIR
if "%DEF_ATTCH_DIR:~-1%"==")" set "DEF_ATTCH_DIR=%DEF_ATTCH_DIR:~0,-1%"
:AFTER_SAN_DEF_ATTCH_DIR
if not "%DEF_OUTPUT_DIR%"=="" goto SAN_DEF_OUTPUT_DIR
goto AFTER_SAN_DEF_OUTPUT_DIR
:SAN_DEF_OUTPUT_DIR
if "%DEF_OUTPUT_DIR:~-1%"==")" set "DEF_OUTPUT_DIR=%DEF_OUTPUT_DIR:~0,-1%"
:AFTER_SAN_DEF_OUTPUT_DIR

REM Prompt user for inputs
echo.
echo === Auto Pack Attachments Inputs ===
set "PROMPT_PY=Python path [%DEF_PY%]: "
set /p PY_PATH="!PROMPT_PY!"
if not defined PY_PATH set "PY_PATH=%DEF_PY%"
if "%PY_PATH:~-1%"==")" set "PY_PATH=%PY_PATH:~0,-1%"

set "PROMPT_ATTCH_DIR=Attachments directory [%DEF_ATTCH_DIR%]: "
set /p attch_dir="!PROMPT_ATTCH_DIR!"
if not defined attch_dir set "attch_dir=%DEF_ATTCH_DIR%"
if "%attch_dir:~-1%"==")" set "attch_dir=%attch_dir:~0,-1%"

set "PROMPT_OUTPUT_DIR=Output directory [%DEF_OUTPUT_DIR%]: "
set /p output_dir="!PROMPT_OUTPUT_DIR!"
if not defined output_dir set "output_dir=%DEF_OUTPUT_DIR%"
if "%output_dir:~-1%"==")" set "output_dir=%output_dir:~0,-1%"

REM =====================
REM Save inputs to history file for next run (2 header lines + 3 values)
REM =====================
REM Clear previous history
>"%HISTORY_FILE%" echo NOTE: Values recorded below; trailing ')' is not part of the value.
>>"%HISTORY_FILE%" echo ===============================================
>>"%HISTORY_FILE%" echo(!PY_PATH!)
>>"%HISTORY_FILE%" echo(!attch_dir!)
>>"%HISTORY_FILE%" echo(!output_dir!)

REM =====================
REM Basic validation
REM =====================
set "VALID=1"

REM Validate Python path (absolute file or command on PATH)
set "PY_FOUND=0"
if exist "%PY_PATH%" set "PY_FOUND=1"
if "!PY_FOUND!"=="0" (
	where /Q %PY_PATH% >nul 2>&1
	if not errorlevel 1 set "PY_FOUND=1"
)
if "!PY_FOUND!"=="0" set "VALID=0" & echo [Error] Python not found: %PY_PATH%

REM Validate attachments directory exists, if not, create it
if not exist "%attch_dir%" mkdir "%attch_dir%" & echo [Info] Attachments directory created: %attch_dir%

REM Validate output directory exists, if not, create it
if not exist "%output_dir%" mkdir "%output_dir%" & echo [Info] Output directory created: %output_dir%

if "%VALID%"=="0" (
	echo.
	echo [FAIL] Validation failed. Please correct inputs and retry.
	goto END
)

REM Show summary
echo.
echo ------------ Selected Inputs ------------
echo Python path                : %PY_PATH%
echo Attachments directory      : %attch_dir%
echo Output directory           : %output_dir%
echo -----------------------------------------

set command=%PY_PATH% scripts\package_restore_folder.py restore %attch_dir% %output_dir%
echo.
echo Running command: %command%
call %command%


:END
endlocal
pause
