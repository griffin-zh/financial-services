@echo off
REM 持仓每日检查 - 由 Windows 任务计划程序 16:00 调用
REM 手动: schtasks /Run /TN "PortfolioDaily"
REM 卸载: schtasks /Delete /TN "PortfolioDaily" /F

set PY=D:\tools\miniconda\envs\financial\python.exe
set SCRIPT=d:\work\study\financial-services\plugins\partner-built\china-market\portfolio_daily.py
set LOG_DIR=d:\work\study\financial-services\投资建议\日报\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 用 ISO 日期做 log 文件名 (避开 locale-dependent 的 %date%)
for /f "tokens=*" %%i in ('%PY% -c "from datetime import date; print(date.today().isoformat())"') do set TODAY=%%i

echo === %TIME% portfolio_daily start === >> "%LOG_DIR%\%TODAY%.log"
"%PY%" "%SCRIPT%" >> "%LOG_DIR%\%TODAY%.log" 2>&1
echo === %TIME% portfolio_daily end (exit %ERRORLEVEL%) === >> "%LOG_DIR%\%TODAY%.log"
