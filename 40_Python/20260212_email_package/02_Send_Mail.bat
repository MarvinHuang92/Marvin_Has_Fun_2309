@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Location for storing last inputs (next to this script)
set SCRIPT_DIR=%~dp0
set CFG_DIR=%SCRIPT_DIR%cfg
if not exist "%CFG_DIR%" mkdir "%CFG_DIR%"
set HISTORY_FILE=%CFG_DIR%\history_input_02.txt

REM Defaults
set DEF_PY=C:/TCC/Tools/python3/3.7.4-29_WIN64_2/python.exe
set DEF_RECEIVER=marvinhuang@qq.com
set DEF_ATTCH_DIR=./attachments
set DEF_SIZE_LIMIT=20
set DEF_INTERVAL=10
set DEF_SENDING_APP=1
set DEF_TEST_MODE=Y

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
		) else if not defined LINE5 (
            set "LINE5=%%A"
        ) else if not defined LINE6 (
            set "LINE6=%%A"
        ) else if not defined LINE7 (
            set "LINE7=%%A"
        )
	)
	rem Expect 7 values in history: PY_PATH, RECEIVER, ATTCH_DIR, SIZE_LIMIT, INTERVAL, SENDING_APP, TEST_MODE
	if defined LINE7 (
		set "DEF_PY=!LINE1!"
		set "DEF_RECEIVER=!LINE2!"
		set "DEF_ATTCH_DIR=!LINE3!"
        set "DEF_SIZE_LIMIT=!LINE4!"
		set "DEF_INTERVAL=!LINE5!"
		set "DEF_SENDING_APP=!LINE6!"
		set "DEF_TEST_MODE=!LINE7!"
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
if not "%DEF_ATTCH_DIR%"=="" goto SAN_DEF_DIR
goto AFTER_SAN_DEF_DIR
:SAN_DEF_DIR
if "%DEF_ATTCH_DIR:~-1%"==")" set "DEF_ATTCH_DIR=%DEF_ATTCH_DIR:~0,-1%"
:AFTER_SAN_DEF_DIR
if not "%DEF_SIZE_LIMIT%"=="" goto SAN_DEF_SIZE
goto AFTER_SAN_DEF_SIZE
:SAN_DEF_SIZE
if "%DEF_SIZE_LIMIT:~-1%"==")" set "DEF_SIZE_LIMIT=%DEF_SIZE_LIMIT:~0,-1%"
:AFTER_SAN_DEF_SIZE
if not "%DEF_INTERVAL%"=="" goto SAN_DEF_INTERVAL
goto AFTER_SAN_DEF_INTERVAL
:SAN_DEF_INTERVAL
if "%DEF_INTERVAL:~-1%"==")" set "DEF_INTERVAL=%DEF_INTERVAL:~0,-1%"
:AFTER_SAN_DEF_INTERVAL
if not "%DEF_SENDING_APP%"=="" goto SAN_DEF_SENDING_APP
goto AFTER_SAN_DEF_SENDING_APP
:SAN_DEF_SENDING_APP
if "%DEF_SENDING_APP:~-1%"==")" set "DEF_SENDING_APP=%DEF_SENDING_APP:~0,-1%"
:AFTER_SAN_DEF_SENDING_APP
if not "%DEF_TEST_MODE%"=="" goto SAN_DEF_TEST_MODE
goto AFTER_SAN_DEF_TEST_MODE
:SAN_DEF_TEST_MODE
if "%DEF_TEST_MODE:~-1%"==")" set "DEF_TEST_MODE=%DEF_TEST_MODE:~0,-1%"
:AFTER_SAN_DEF_TEST_MODE

REM Prompt user for inputs
echo.
echo === Auto Pack Attachments Inputs ===
set "PROMPT_PY=Python path [%DEF_PY%]: "
set /p PY_PATH="!PROMPT_PY!"
if not defined PY_PATH set "PY_PATH=%DEF_PY%"
if "%PY_PATH:~-1%"==")" set "PY_PATH=%PY_PATH:~0,-1%"

set "PROMPT_RECEIVER=Email receiver [%DEF_RECEIVER%]: "
set /p receiver="!PROMPT_RECEIVER!"
if not defined receiver set "receiver=%DEF_RECEIVER%"
if "%receiver:~-1%"==")" set "receiver=%receiver:~0,-1%"

set "PROMPT_DIR=Attachments directory [%DEF_ATTCH_DIR%]: "
set /p attch_dir="!PROMPT_DIR!"
if not defined attch_dir set "attch_dir=%DEF_ATTCH_DIR%"
if "%attch_dir:~-1%"==")" set "attch_dir=%attch_dir:~0,-1%"

set "PROMPT_SIZE=Attachment size limit (MB) [%DEF_SIZE_LIMIT%]: "
set /p size_limit="!PROMPT_SIZE!"
if not defined size_limit set "size_limit=%DEF_SIZE_LIMIT%"
if "%size_limit:~-1%"==")" set "size_limit=%size_limit:~0,-1%"

set "PROMPT_INTERVAL=Interval (seconds) [%DEF_INTERVAL%]: "
set /p interval="!PROMPT_INTERVAL!"
if not defined interval set "interval=%DEF_INTERVAL%"
if "%interval:~-1%"==")" set "interval=%interval:~0,-1%"

set "PROMPT_SENDING_APP=Sending App (1.Outlook, 2.SMTP) [%DEF_SENDING_APP%]: "
set /p sending_app="!PROMPT_SENDING_APP!"
if not defined sending_app set "sending_app=%DEF_SENDING_APP%"
if "%sending_app:~-1%"==")" set "sending_app=%sending_app:~0,-1%"

set "PROMPT_TEST=Test mode (Y/N) [%DEF_TEST_MODE%]: "
set /p test_mode="!PROMPT_TEST!"
if not defined test_mode set "test_mode=%DEF_TEST_MODE%"
if "%test_mode:~-1%"==")" set "test_mode=%test_mode:~0,-1%"

REM =====================
REM Save inputs to history file for next run (2 header lines + 7 values)
REM =====================
REM Clear previous history
>"%HISTORY_FILE%" echo NOTE: Values recorded below; trailing ')' is not part of the value.
>>"%HISTORY_FILE%" echo ===============================================
>>"%HISTORY_FILE%" echo(!PY_PATH!)
>>"%HISTORY_FILE%" echo(!receiver!)
>>"%HISTORY_FILE%" echo(!attch_dir!)
>>"%HISTORY_FILE%" echo(!size_limit!)
>>"%HISTORY_FILE%" echo(!interval!)
>>"%HISTORY_FILE%" echo(!sending_app!)
>>"%HISTORY_FILE%" echo(!test_mode!)

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

REM Validate size limit (integer > 0)
echo %size_limit%| findstr /R "^[0-9][0-9]*$" >nul || (set "VALID=0" & echo [Error] Size limit must be an integer: %size_limit%)
if "%size_limit%"=="0" set "VALID=0" & echo [Error] Size limit must be greater than 0

REM Validate interval (integer > 0)
echo %interval%| findstr /R "^[0-9][0-9]*$" >nul || (set "VALID=0" & echo [Error] Interval must be an integer: %interval%)
if "%interval%"=="0" set "VALID=0" & echo [Error] Interval must be greater than 0

REM Validate sending_app (must be 1 or 2)
if "%sending_app%"=="1" (
	set sending_app=outlook
) else if "%sending_app%"=="2" (
	set sending_app=smtp
) else (
	set "VALID=0" & echo [Error] Sending App must be 1 or 2
)

REM Validate attachments directory exists, if not, create it
if not exist "%attch_dir%" mkdir "%attch_dir%" & echo [Info] Attachments directory created: %attch_dir%

if "%VALID%"=="0" (
	echo.
	echo [FAIL] Validation failed. Please correct inputs and retry.
	goto END
)

REM Show summary
echo.
echo ------------ Selected Inputs ------------
echo Python path                : %PY_PATH%
echo Email receiver             : %receiver%
echo Attachments directory      : %attch_dir%
echo Attachment size limit (MB) : %size_limit%
echo Interval (seconds)         : %interval%
echo Sending App                : %sending_app%
echo Test mode (Y/N)            : %test_mode%
echo -----------------------------------------

set command=%PY_PATH% scripts\send_email_with_auto_packed_attachments.py %receiver% %attch_dir% %size_limit% %interval% %sending_app% %test_mode%
echo.
echo Running command: %command%
call %command%


:END
endlocal
pause
