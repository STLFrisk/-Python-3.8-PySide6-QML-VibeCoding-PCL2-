@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 用 pythonw.exe 启动, 不产生 cmd 控制台窗口; 找不到时退回 python.exe
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0main.py" %*
) else (
    python.exe "%~dp0main.py" %*
    if errorlevel 1 pause
)
