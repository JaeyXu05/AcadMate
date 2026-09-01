@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0scripts\start-project.ps1" (
    echo [ERROR] Missing scripts\start-project.ps1
    echo Please make sure the complete repository was downloaded.
    pause
    exit /b 1
)

start "" "%~dp0scripts\startup-status.html"
if not exist "%~dp0.startup-logs" mkdir "%~dp0.startup-logs"
start "" /b powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" -LaunchOnly -NoBrowser %* >>"%~dp0.startup-logs\launcher.log" 2>&1
exit /b 0
