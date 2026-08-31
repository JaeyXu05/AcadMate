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

rem ---- 2. prepare the shared Node/Python environment when available ----
if exist "D:\Anaconda\envs\paper\node.exe" set "PATH=D:\Anaconda\envs\paper;D:\Anaconda\envs\paper\Scripts;%PATH%"

rem ---- 3. start Docker/PostgreSQL dependency ----
set "PAPER_CLAW_ROOT=%~dp0paper-claw-master"
if exist "%PAPER_CLAW_ROOT%\docker-compose.yml" (
    docker info >nul 2>nul
    if errorlevel 1 (
        if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
            echo [2/6] Starting Docker Desktop...
            start "" /b "C:\Program Files\Docker\Docker\Docker Desktop.exe"
            set DOCKER_READY=0
            for /l %%i in (1,1,30) do (
                docker info >nul 2>nul
                if not errorlevel 1 set DOCKER_READY=1
                if "!DOCKER_READY!"=="1" goto docker_ready
                timeout /t 2 /nobreak >nul
            )
            :docker_ready
        )
    )
    docker info >nul 2>nul
    if errorlevel 1 echo [WARN] Docker engine unavailable; A端数据库可能无法启动。
    if not errorlevel 1 (
        pushd "%PAPER_CLAW_ROOT%"
        docker compose up -d postgres
        if errorlevel 1 echo [WARN] PostgreSQL container failed to start.
        if exist "D:\Anaconda\envs\paper\Scripts\uv.exe" (
            echo [3/6] Applying A端 database migrations...
            call "D:\Anaconda\envs\paper\Scripts\uv.exe" run --project backend alembic -c backend/alembic.ini upgrade head
        )
        if not exist "D:\Anaconda\envs\paper\Scripts\uv.exe" echo [WARN] uv not found; skip A端 migration.
        netstat -ano | findstr ":8000" >nul 2>nul
        if errorlevel 1 (
            echo [4/6] Starting PaperClaw A端...
            if exist "D:\Anaconda\envs\paper\Scripts\uv.exe" start "PaperClaw A" /min cmd /d /c "cd /d ""%PAPER_CLAW_ROOT%"" && ""D:\Anaconda\envs\paper\Scripts\uv.exe"" run --project backend uvicorn backend.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000"
        ) else echo [4/6] PaperClaw A端 already running.
        popd
    )
) else echo [WARN] paper-claw-master not found; skip A端 startup.

rem ---- 5. check Node.js ----
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+:
    echo         https://nodejs.org/
    pause
    exit /b 1
)
for /f "delims=" %%v in ('node -v') do set NODE_VER=%%v
    echo [1/6] Node.js version: %NODE_VER%

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
        echo [5/6] Created .env from .env.example.
    ) else (
        echo [ERROR] .env.example missing.
        pause
        popd & exit /b 1
    )
) else (
    echo [5/6] .env already exists.
)

rem ---- 5. check deps installed ----
set NEED_INSTALL=0
if not exist "node_modules\.bin\tsx.cmd" (
    set NEED_INSTALL=1
)

if "%NEED_INSTALL%"=="1" (
    echo [5/6] First run - installing dependencies, please wait...
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
    echo [5/6] Dependencies already installed.
)

rem ---- 6. open browser after 6s ----
echo [6/6] Starting D端前后端 and opening browser...
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
