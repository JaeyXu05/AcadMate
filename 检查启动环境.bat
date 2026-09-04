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
set /p "SETUP_API=Do you want to launch the app and configure your own LLM API now? [Y/n]: "
if /I "%SETUP_API%"=="Y" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" -LaunchOnly -ConfigureApi
) else if /I "%SETUP_API%"=="" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" -LaunchOnly -ConfigureApi
) else (
  echo API setup skipped. Run start-project.ps1 -LaunchOnly -ConfigureApi later.
)
exit /b 0
