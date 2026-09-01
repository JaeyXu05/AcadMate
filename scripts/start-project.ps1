[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Prepare,
    [switch]$LaunchOnly,
    [switch]$NoBrowser,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$CodeRoot = Join-Path $ProjectRoot 'Code'
$PaperRoot = Join-Path $ProjectRoot 'paper-claw-master'
$BackendRoot = Join-Path $PaperRoot 'backend'
$LogRoot = Join-Path $ProjectRoot '.startup-logs'

function Write-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Stop-Startup([string]$Message) { throw $Message }

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Find-Command([string]$Name, [string[]]$Fallbacks = @()) {
    $found = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }
    foreach ($candidate in $Fallbacks) {
        $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
        if (Test-Path -LiteralPath $expanded) { return (Resolve-Path $expanded).Path }
    }
    return $null
}

function Confirm-Install([string]$DisplayName) {
    if ($SkipInstall) { return $false }
    $answer = Read-Host "$DisplayName is required but missing. Install it automatically now? [Y/n]"
    return [string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant() -in @('y', 'yes')
}

function Install-WingetPackage([string]$Id, [string]$DisplayName) {
    $winget = Find-Command 'winget.exe' @('%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe')
    if (-not $winget) {
        Stop-Startup "$DisplayName is missing and Windows Package Manager (winget) is unavailable. Install 'App Installer' from Microsoft Store, then run this launcher again."
    }
    if (-not (Confirm-Install $DisplayName)) { Stop-Startup "$DisplayName is required. Installation was declined." }
    Write-Step "Installing $DisplayName (Windows may ask for administrator permission)"
    & $winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Startup "$DisplayName installation failed (winget exit code $LASTEXITCODE)." }
    Refresh-ProcessPath
}

function Get-MajorVersion([string]$Executable, [string[]]$Arguments) {
    $text = (& $Executable @Arguments 2>$null | Select-Object -First 1)
    if ($text -match '(\d+)') { return [int]$Matches[1] }
    return 0
}

function Ensure-Node {
    $node = Find-Command 'node.exe'
    $major = if ($node) { Get-MajorVersion $node @('--version') } else { 0 }
    if (-not $node -or $major -lt 20) {
        if ($node) { Write-Warn "Node.js $major is too old; this project requires Node.js 20 or newer." }
        Install-WingetPackage 'OpenJS.NodeJS.LTS' 'Node.js LTS 20+'
        $node = Find-Command 'node.exe' @('%ProgramFiles%\nodejs\node.exe')
        $major = if ($node) { Get-MajorVersion $node @('--version') } else { 0 }
    }
    if (-not $node -or $major -lt 20) { Stop-Startup 'Node.js 20+ is still unavailable. Sign out or reboot after installation, then rerun.' }
    $npm = Find-Command 'npm.cmd' @('%ProgramFiles%\nodejs\npm.cmd')
    if (-not $npm) { Stop-Startup 'npm was not found next to Node.js. Reinstall Node.js LTS.' }
    Write-Ok "Node.js $(& $node --version) / npm $(& $npm --version)"
    return @{ Node = $node; Npm = $npm }
}

function Ensure-Uv {
    $uv = Find-Command 'uv.exe' @('%USERPROFILE%\.local\bin\uv.exe', '%LOCALAPPDATA%\Programs\uv\uv.exe')
    if (-not $uv) {
        Install-WingetPackage 'astral-sh.uv' 'uv (Python environment manager)'
        $uv = Find-Command 'uv.exe' @('%USERPROFILE%\.local\bin\uv.exe', '%LOCALAPPDATA%\Programs\uv\uv.exe')
    }
    if (-not $uv) { Stop-Startup 'uv is still unavailable. Sign out or reboot after installation, then rerun.' }
    Write-Ok "$(& $uv --version)"
    return $uv
}

function Ensure-Docker {
    $docker = Find-Command 'docker.exe' @('%ProgramFiles%\Docker\Docker\resources\bin\docker.exe')
    if (-not $docker) {
        Install-WingetPackage 'Docker.DockerDesktop' 'Docker Desktop'
        $docker = Find-Command 'docker.exe' @('%ProgramFiles%\Docker\Docker\resources\bin\docker.exe')
    }
    if (-not $docker) { Stop-Startup 'Docker CLI is still unavailable. A reboot may be required after Docker Desktop installation.' }
    Write-Ok "$(& $docker --version)"
    return $docker
}

function Test-Http([string]$Url, [int]$TimeoutSeconds = 3) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSeconds
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch { return $false }
}

function Wait-Http([string]$Name, [string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Http $Url 2) { Write-Ok "$Name is reachable: $Url"; return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Test-DockerEngine([string]$Docker) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Docker info *> $null
        return $LASTEXITCODE -eq 0
    } finally { $ErrorActionPreference = $previous }
}

function Ensure-DockerEngine([string]$Docker) {
    if (Test-DockerEngine $Docker) { Write-Ok 'Docker engine is running'; return }
    $desktop = Find-Command 'Docker Desktop.exe' @('%ProgramFiles%\Docker\Docker\Docker Desktop.exe', '%LOCALAPPDATA%\Docker\Docker Desktop.exe')
    if (-not $desktop) { Stop-Startup 'Docker Desktop is installed but its application could not be located.' }
    Write-Step 'Starting Docker Desktop'
    Write-Warn 'Docker Desktop may display its first-run agreement or WSL setup. Complete that window once; the launcher will keep waiting.'
    Start-Process -FilePath $desktop | Out-Null
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine $Docker) { Write-Ok 'Docker engine is ready'; return }
    } while ((Get-Date) -lt $deadline)
    Stop-Startup 'Docker did not become ready within 3 minutes. Open Docker Desktop, finish its first-run agreement/WSL setup, then rerun.'
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function Ensure-EnvFiles {
    $codeEnv = Join-Path $CodeRoot '.env'
    if (-not (Test-Path -LiteralPath $codeEnv)) {
        $example = Get-Content -LiteralPath (Join-Path $CodeRoot '.env.example') -Raw
        $secret = New-RandomSecret
        $content = $example -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$secret"
        [IO.File]::WriteAllText($codeEnv, $content, (New-Object Text.UTF8Encoding($false)))
        Write-Ok 'Created Code/.env with a random JWT secret'
    } else {
        $content = Get-Content -LiteralPath $codeEnv -Raw
        $match = [regex]::Match($content, '(?m)^JWT_SECRET=(.*)$')
        $unsafe = -not $match.Success -or $match.Groups[1].Value.Trim().Length -lt 32 -or $match.Groups[1].Value -match 'replace-with|change-me|secret'
        if ($unsafe) {
            $secret = New-RandomSecret
            if ($match.Success) { $content = [regex]::Replace($content, '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$secret") }
            else { $content = "JWT_SECRET=$secret`r`n$content" }
            [IO.File]::WriteAllText($codeEnv, $content, (New-Object Text.UTF8Encoding($false)))
            Write-Ok 'Replaced missing/example JWT secret in Code/.env'
        } else { Write-Ok 'Code/.env already exists and has a non-default JWT secret' }
    }

    $paperEnv = Join-Path $PaperRoot '.env'
    if (-not (Test-Path -LiteralPath $paperEnv)) {
        Copy-Item -LiteralPath (Join-Path $PaperRoot '.env.example') -Destination $paperEnv
        Write-Ok 'Created paper-claw-master/.env from .env.example'
        Write-Warn 'Chat/API-key features stay disabled until PAPER_CLAW_CHAT_* values are filled. Deterministic mentor retrieval can still start.'
    } else { Write-Ok 'paper-claw-master/.env already exists' }
}

function Ensure-Dependencies([string]$Npm, [string]$Uv) {
    Write-Step 'Checking D-side Node dependencies'
    Push-Location $CodeRoot
    try {
        & $Npm ls --depth=0 *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Step 'Installing/updating D-side Node dependencies'
            & $Npm install
            if ($LASTEXITCODE -ne 0) { Stop-Startup 'npm install failed. Check network/proxy settings and available disk space.' }
        }
        Write-Ok 'D-side Node dependencies are complete'
    } finally { Pop-Location }

    Write-Step 'Checking A-side Python 3.12+ environment and dependencies'
    & $Uv sync --project $BackendRoot --dev
    if ($LASTEXITCODE -ne 0) { Stop-Startup 'uv sync failed. Check network/proxy settings and available disk space.' }
    Write-Ok 'A-side Python environment is complete'
}

function Start-ServiceWindow([string]$Title, [string]$WorkingDirectory, [string]$Command, [string]$LogFile) {
    $full = "title $Title && cd /d `"$WorkingDirectory`" && $Command 1>>`"$LogFile`" 2>&1"
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d', '/c', $full) -WorkingDirectory $WorkingDirectory -WindowStyle Hidden | Out-Null
}

function Test-ExternalNetwork {
    try {
        $addresses = [Net.Dns]::GetHostAddresses('faculty.ustc.edu.cn')
        $hasV4 = $addresses.AddressFamily -contains [Net.Sockets.AddressFamily]::InterNetwork
        if (-not $hasV4) { Write-Warn 'USTC faculty site has no IPv4 DNS result. Live evidence enrichment may time out; local RAG remains available.' }
    } catch { Write-Warn 'Cannot resolve faculty.ustc.edu.cn. Live evidence enrichment may time out; local RAG remains available.' }
}

function Get-ExistingTools {
    $node = Find-Command 'node.exe' @('%ProgramFiles%\nodejs\node.exe')
    $npm = Find-Command 'npm.cmd' @('%ProgramFiles%\nodejs\npm.cmd')
    $uv = Find-Command 'uv.exe' @('%USERPROFILE%\.local\bin\uv.exe', '%LOCALAPPDATA%\Programs\uv\uv.exe')
    $docker = Find-Command 'docker.exe' @('%ProgramFiles%\Docker\Docker\resources\bin\docker.exe')
    if (-not $node -or -not $npm -or -not $uv -or -not $docker) {
        Stop-Startup 'The prepared environment is incomplete. Run the environment-check BAT file first.'
    }
    if ((Get-MajorVersion $node @('--version')) -lt 20) {
        Stop-Startup 'Node.js is older than version 20. Run the environment-check BAT file first.'
    }
    return @{ Node = $node; Npm = $npm; Uv = $uv; Docker = $docker }
}

function Start-Postgres([string]$Docker) {
    Write-Step 'Starting PostgreSQL'
    & $Docker compose -f (Join-Path $PaperRoot 'docker-compose.yml') up -d postgres
    if ($LASTEXITCODE -ne 0) { Stop-Startup 'PostgreSQL container failed to start.' }
    $deadline = (Get-Date).AddMinutes(2)
    $health = ''
    do {
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $health = (& $Docker inspect --format '{{.State.Health.Status}}' paper-claw-postgres 2>$null)
        } finally { $ErrorActionPreference = $previous }
        if ($health -eq 'healthy') { Write-Ok 'PostgreSQL is healthy on port 5432'; return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Stop-Startup 'PostgreSQL did not become healthy. Check Docker Desktop and .startup-logs.'
}

function Apply-Migrations([string]$Uv) {
    Write-Step 'Applying database migrations'
    Push-Location $PaperRoot
    try {
        & $Uv run --project backend alembic -c backend/alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) { Stop-Startup 'Database migration failed.' }
    } finally { Pop-Location }
    Write-Ok 'Database migrations are current'
}

function Start-ApplicationServices([hashtable]$Tools) {
    $aLog = Join-Path $LogRoot 'a-backend.log'
    if (-not (Test-Http 'http://127.0.0.1:8000/api/health')) {
        Write-Step 'Starting A-side backend'
        Start-ServiceWindow 'Mentor Platform - A Backend' $PaperRoot "`"$($Tools.Uv)`" run --project backend uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port 8000" $aLog
    } else { Write-Ok 'A-side backend is already running' }

    $dLog = Join-Path $LogRoot 'd-web.log'
    if (-not (Test-Http 'http://127.0.0.1:3001/api/health') -or -not (Test-Http 'http://localhost:5173')) {
        Write-Step 'Starting D-side frontend and backend'
        Start-ServiceWindow 'Mentor Platform - Web' $CodeRoot "`"$($Tools.Npm)`" run dev" $dLog
    } else { Write-Ok 'D-side frontend and backend are already running' }

    if (-not (Wait-Http 'A-side backend' 'http://127.0.0.1:8000/api/health' 120)) { Stop-Startup "A-side backend failed. See $aLog" }
    if (-not (Wait-Http 'D-side backend' 'http://127.0.0.1:3001/api/health' 90)) { Stop-Startup "D-side backend failed. See $dLog" }
    if (-not (Wait-Http 'Frontend' 'http://localhost:5173' 90)) { Stop-Startup "Frontend failed. See $dLog" }
}

try {
    Write-Host 'Mentor Platform portable launcher' -ForegroundColor White
    Write-Host "Project: $ProjectRoot"
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    foreach ($required in @($CodeRoot, $BackendRoot, (Join-Path $PaperRoot 'docker-compose.yml'))) {
        if (-not (Test-Path -LiteralPath $required)) { Stop-Startup "Required project path is missing: $required" }
    }

    if ($LaunchOnly) {
        $tools = Get-ExistingTools
        if (-not $NoBrowser) { Start-Process (Join-Path $PSScriptRoot 'startup-status.html') | Out-Null }
        Ensure-DockerEngine $tools.Docker
        Start-Postgres $tools.Docker
        Start-ApplicationServices $tools
    } else {
        Write-Step 'Checking and preparing the complete environment'
        $nodeTools = Ensure-Node
        $uv = Ensure-Uv
        $docker = Ensure-Docker
        Test-ExternalNetwork
        Ensure-EnvFiles
        if ($CheckOnly) { Write-Ok 'Basic tool/config check completed. Use the environment-check BAT file for complete preparation.'; exit 0 }
        Ensure-Dependencies $nodeTools.Npm $uv
        Ensure-DockerEngine $docker
        Start-Postgres $docker
        Apply-Migrations $uv
        Write-Host "`nEnvironment preparation completed." -ForegroundColor Green
        Write-Host 'You can now use the one-click launcher for fast daily startup.'
        exit 0
    }

    Write-Host "`nAll core services are running:" -ForegroundColor Green
    Write-Host '  Frontend:   http://localhost:5173'
    Write-Host '  D backend:  http://localhost:3001/api/health'
    Write-Host '  A backend:  http://localhost:8000/api/health'
    Write-Host '  PostgreSQL: localhost:5432'
    Write-Host "  Logs:       $LogRoot"
    exit 0
} catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Logs: $LogRoot" -ForegroundColor Yellow
    exit 1
}
