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

rem Keep this window visible: a hidden failure is indistinguishable from a page that never opens.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" -LaunchOnly -PauseOnFailure %*
exit /b %ERRORLEVEL%
