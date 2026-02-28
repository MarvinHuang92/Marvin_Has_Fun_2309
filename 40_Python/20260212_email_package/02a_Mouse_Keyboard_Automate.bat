@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Location for storing last inputs (next to this script)
set SCRIPT_DIR=%~dp0
set CFG_DIR=%SCRIPT_DIR%cfg
if not exist "%CFG_DIR%" mkdir "%CFG_DIR%"
set HISTORY_FILE=%CFG_DIR%\history_input_02a.txt

REM Defaults
set DEF_PY=C:/TCC/Tools/python3/3.7.4-29_WIN64_2/python.exe
set DEF_RECEIVER=marvinhuang@qq.com
set DEF_TEST_MODE=Y
set DEF_START_ATTCH_ID=1

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
		) else if not defined LINE4 (
			set "LINE4=%%A"
		)
	)
	rem Expect 4 values in history: PY_PATH, RECEIVER, TEST_MODE, START_ATTCH_ID
	if defined LINE4 (
		set "DEF_PY=!LINE1!"
		set "DEF_RECEIVER=!LINE2!"
		set "DEF_TEST_MODE=!LINE3!"
		set "DEF_START_ATTCH_ID=!LINE4!"
	)
)

REM Sanitize loaded defaults: remove trailing ')' if present
if not "%DEF_PY%"=="" goto SAN_DEF_PY
goto AFTER_SAN_DEF_PY
:SAN_DEF_PY
if "%DEF_PY:~-1%"==")" set "DEF_PY=%DEF_PY:~0,-1%"
:AFTER_SAN_DEF_PY
if not "%DEF_RECEIVER%"=="" goto SAN_DEF_RECEIVER
goto AFTER_SAN_DEF_RECEIVER
:SAN_DEF_RECEIVER
if "%DEF_RECEIVER:~-1%"==")" set "DEF_RECEIVER=%DEF_RECEIVER:~0,-1%"
:AFTER_SAN_DEF_RECEIVER
if not "%DEF_TEST_MODE%"=="" goto SAN_DEF_TEST_MODE
goto AFTER_SAN_DEF_TEST_MODE
:SAN_DEF_TEST_MODE
if "%DEF_TEST_MODE:~-1%"==")" set "DEF_TEST_MODE=%DEF_TEST_MODE:~0,-1%"
:AFTER_SAN_DEF_TEST_MODE
if not "%DEF_START_ATTCH_ID%"=="" goto SAN_DEF_START_ATTCH_ID
goto AFTER_SAN_DEF_START_ATTCH_ID
:SAN_DEF_START_ATTCH_ID
if "%DEF_START_ATTCH_ID:~-1%"==")" set "DEF_START_ATTCH_ID=%DEF_START_ATTCH_ID:~0,-1%"
:AFTER_SAN_DEF_START_ATTCH_ID

REM Prompt user for inputs
echo.
echo === Auto Pack Attachments Inputs ===
set "PROMPT_PY=Python path [%DEF_PY%]: "
set /p PY_PATH="!PROMPT_PY!"
if not defined PY_PATH set "PY_PATH=%DEF_PY%"
if "%PY_PATH:~-1%"==")" set "PY_PATH=%PY_PATH:~0,-1%"

set "PROMPT_RECEIVER=Receiver [%DEF_RECEIVER%]: "
set /p receiver="!PROMPT_RECEIVER!"
if not defined receiver set "receiver=%DEF_RECEIVER%"
if "%receiver:~-1%"==")" set "receiver=%receiver:~0,-1%"

set "PROMPT_TEST=Test mode (Y/N) [%DEF_TEST_MODE%]: "
set /p test_mode="!PROMPT_TEST!"
if not defined test_mode set "test_mode=%DEF_TEST_MODE%"
if "%test_mode:~-1%"==")" set "test_mode=%test_mode:~0,-1%"

set "PROMPT_START_ATTCH_ID=Start attachment ID [%DEF_START_ATTCH_ID%]: "
set /p start_attch_id="!PROMPT_START_ATTCH_ID!"
if not defined start_attch_id set "start_attch_id=%DEF_START_ATTCH_ID%"
if "%start_attch_id:~-1%"==")" set "start_attch_id=%start_attch_id:~0,-1%"

REM =====================
REM Save inputs to history file for next run (2 header lines + 4 values)
REM =====================
REM Clear previous history
>"%HISTORY_FILE%" echo NOTE: Values recorded below; trailing ')' is not part of the value.
>>"%HISTORY_FILE%" echo ===============================================
>>"%HISTORY_FILE%" echo(!PY_PATH!)
>>"%HISTORY_FILE%" echo(!receiver!)
>>"%HISTORY_FILE%" echo(!test_mode!)
>>"%HISTORY_FILE%" echo(!start_attch_id!)

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

REM Validate email receiver (very basic pattern)
echo %receiver%| findstr /R "^[^@ ][^@ ]*@[^@ ][^@ ]*[.][^@ ][^@ ]*$" >nul || (set "VALID=0" & echo [Error] Invalid email: %receiver%)

REM Validate test mode (Y/N)
if /I not "%test_mode%"=="Y" if /I not "%test_mode%"=="N" set "VALID=0" & echo [Error] Test mode must be Y or N: %test_mode%

REM Validate start attachment ID (positive integer)
if not "%start_attch_id%"=="" (
    for /f "delims=0123456789" %%A in ("%start_attch_id%") do (
        set "VALID=0"
        echo [Error] Start attachment ID must be a positive integer: %start_attch_id%
    )
)

if "%VALID%"=="0" (
	echo.
	echo [FAIL] Validation failed. Please correct inputs and retry.
	goto END
)

REM Show summary
echo.
echo ------------ Selected Inputs ------------
echo Python path                : %PY_PATH%
echo Receiver                   : %receiver%
echo Test mode (Y/N)            : %test_mode%
echo Start attachment ID        : %start_attch_id%
echo -----------------------------------------

set command=%PY_PATH% scripts\mouse_keyboard_automate.py %receiver% %test_mode% %start_attch_id%
echo.
echo Running command: %command%
call %command%


:END
endlocal
pause
