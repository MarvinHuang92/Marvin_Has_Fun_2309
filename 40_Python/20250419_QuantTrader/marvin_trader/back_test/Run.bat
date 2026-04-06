@echo off
@REM 个人电脑
set python3="D:\Program Files\Python3133\python.exe"

@REM 工作电脑
@REM set python3="D:\Python313\python.exe"

@REM 安装依赖库
@REM %python3% -m pip install pandas
@REM %python3% -m pip install numpy
@REM %python3% -m pip install matplotlib
@REM %python3% -m pip install yfinance
@REM %python3% -m pip install baostock

@REM 运行
%python3% trader.py

pause