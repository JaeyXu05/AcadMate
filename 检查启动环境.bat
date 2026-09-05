@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" -Prepare
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  pause
  exit /b %EXIT_CODE%
)

echo.
echo Environment preparation completed. API configuration is optional.
echo Run 启动项目.bat, then configure a private API for the logged-in account only when a model feature is needed.
exit /b 0
