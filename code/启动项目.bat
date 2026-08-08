@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem   Mentor Recommendation Platform - one-click launcher
rem   Double-click this file in the project root folder.
rem ============================================================

echo.
echo ======================================================
echo    Mentor Platform - Starting...
echo ======================================================
echo.

rem ---- 1. cd to this script's folder (project root) ----
cd /d "%~dp0"

rem ---- 2. check Node.js ----
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+:
    echo         https://nodejs.org/
    pause
    exit /b 1
)
for /f "delims=" %%v in ('node -v') do set NODE_VER=%%v
echo [1/4] Node.js version: %NODE_VER%

rem ---- 3. enter Code/ ----
pushd "%~dp0Code"
if not exist package.json (
    echo [ERROR] Code\package.json not found.
    echo         Make sure the script is in the project root folder.
    pause
    popd & exit /b 1
)

rem ---- 4. ensure .env exists ----
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo [2/4] Created .env from .env.example.
    ) else (
        echo [ERROR] .env.example missing.
        pause
        popd & exit /b 1
    )
) else (
    echo [2/4] .env already exists.
)

rem ---- 5. check deps installed ----
set NEED_INSTALL=0
if not exist "node_modules\.bin\tsx.cmd" (
    set NEED_INSTALL=1
)

if "%NEED_INSTALL%"=="1" (
    echo [3/4] First run - installing dependencies, please wait...
    call npm install
    if errorlevel 1 (
        echo.
        echo [ERROR] npm install failed.
        echo         If you see better-sqlite3 build errors, make sure
        echo         Node is 18+ or better-sqlite3 is ^13.0.3.
        pause
        popd & exit /b 1
    )
) else (
    echo [3/4] Dependencies already installed.
)

rem ---- 6. open browser after 6s ----
echo [4/4] Starting services and opening browser...
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:5173"

rem ---- 7. run dev server (frontend + backend) ----
echo.
echo ---------------------------------------------------
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:3001/api/health
echo   Press Ctrl+C to stop all services.
echo ---------------------------------------------------
call npm run dev

popd
endlocal