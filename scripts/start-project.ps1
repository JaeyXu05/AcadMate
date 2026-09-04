[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Prepare,
    [switch]$LaunchOnly,
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$PauseOnFailure
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$CodeRoot = Join-Path $ProjectRoot 'Code'
$PaperRoot = Join-Path $ProjectRoot 'paper-claw-master'
$BackendRoot = Join-Path $PaperRoot 'backend'
$LogRoot = Join-Path $ProjectRoot '.startup-logs'
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.uv-cache'

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
    if ($found -and $found.Source) { return $found.Source }
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
    if (-not $winget) { Stop-Startup "$DisplayName is missing and Windows Package Manager (winget) is unavailable. Install App Installer, then run this launcher again." }
    if (-not (Confirm-Install $DisplayName)) { Stop-Startup "$DisplayName is required. Installation was declined." }
    Write-Step "Installing $DisplayName (Windows may ask for administrator permission)"
    & $winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Startup "$DisplayName installation failed (winget exit code $LASTEXITCODE)." }
    Refresh-ProcessPath
}

function Get-NodeVersion([string]$Node) {
    $raw = (& $Node --version 2>$null | Select-Object -First 1).Trim()
    if ($raw -match '^v?(\d+)\.(\d+)\.(\d+)') {
        return @{ Raw = $raw; Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Patch = [int]$Matches[3] }
    }
    return $null
}

function Test-SupportedNode([hashtable]$Version) {
    return ($Version.Major -eq 20 -and $Version.Minor -ge 19) -or
        ($Version.Major -gt 22) -or
        ($Version.Major -eq 22 -and $Version.Minor -ge 12)
}

function Test-NodeRuntime([string]$Node) {
    # Keep this probe independent from the hosting account.  Sandboxed runners can
    # deliberately use a service token while inheriting the desktop user's HOME,
    # which makes os.userInfo() fail even though Node and the application are fine.
    $process = Start-Process -FilePath $Node -ArgumentList @('-e', "process.stdout.write(process.version)") -Wait -PassThru -WindowStyle Hidden
    return $process.ExitCode -eq 0
}

function Ensure-Node {
    $node = Find-Command 'node.exe'
    $version = if ($node) { Get-NodeVersion $node } else { $null }
    if (-not $version -or -not (Test-SupportedNode $version)) {
        if ($version) { Write-Warn "Node.js $($version.Raw) is unsupported; Vite requires ^20.19.0 or >=22.12.0." }
        Install-WingetPackage 'OpenJS.NodeJS.LTS' 'Node.js LTS'
        $node = Find-Command 'node.exe' @('%ProgramFiles%\nodejs\node.exe')
        $version = if ($node) { Get-NodeVersion $node } else { $null }
    }
    if (-not $version -or -not (Test-SupportedNode $version)) { Stop-Startup 'A supported Node.js version (^20.19.0 or >=22.12.0) is still unavailable. Restart Windows after installation, then rerun.' }
    if (-not (Test-NodeRuntime $node)) { Stop-Startup 'Node.js is present but cannot execute JavaScript. Repair or reinstall Node.js LTS, then rerun.' }
    $npm = Find-Command 'npm.cmd' @('%ProgramFiles%\nodejs\npm.cmd')
    if (-not $npm) { Stop-Startup 'npm was not found next to Node.js. Reinstall Node.js LTS.' }
    Write-Ok "Node.js $($version.Raw) / npm $(& $npm --version)"
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
    & $docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Stop-Startup 'Docker Compose v2 is unavailable. Repair or update Docker Desktop, then rerun.' }
    Write-Ok "$(& $docker --version)"
    return $docker
}

function Get-EnvValue([string]$Path, [string]$Key, [string]$Default) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $Default
}

function Get-ComposeProjectName {
    $bytes = [Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant())
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = -join ($sha.ComputeHash($bytes) | Select-Object -First 6 | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
    return "mentorplatform_$hash"
}

function Initialize-RuntimeConfig {
    $codeEnv = Join-Path $CodeRoot '.env'
    $paperEnv = Join-Path $PaperRoot '.env'
    $script:Config = @{
        DPort = [int](Get-EnvValue $codeEnv 'PORT' '3001')
        VitePort = [int](Get-EnvValue $codeEnv 'VITE_PORT' '5173')
        DbPort = [int](Get-EnvValue $paperEnv 'PAPER_CLAW_POSTGRES_PORT' '5432')
        DatabaseUrl = Get-EnvValue $paperEnv 'PAPER_CLAW_DATABASE_URL' 'postgresql+psycopg://paper_claw:paper_claw@localhost:5432/paper_claw'
        APort = 8000
        ComposeProject = Get-ComposeProjectName
    }
    $base = Get-EnvValue $codeEnv 'MENTOR_AGENT_BASE_URL' 'http://127.0.0.1:8000'
    try { $script:Config.APort = ([Uri]$base).Port } catch { Stop-Startup "MENTOR_AGENT_BASE_URL is invalid: $base" }
    if ($script:Config.DbPort -ne ([Uri]($script:Config.DatabaseUrl -replace '^postgresql\+psycopg:', 'postgresql:')).Port) {
        Stop-Startup 'PAPER_CLAW_POSTGRES_PORT and the port in PAPER_CLAW_DATABASE_URL must match. Update both values in paper-claw-master/.env.'
    }
    $script:Config.FrontendUrl = "http://127.0.0.1:$($script:Config.VitePort)"
    $script:Config.DHealthUrl = "http://127.0.0.1:$($script:Config.DPort)/api/health"
    $script:Config.AHealthUrl = "http://127.0.0.1:$($script:Config.APort)/api/health"
}

function Test-ProjectWritable {
    $probe = Join-Path $LogRoot ('.write-probe-' + [Guid]::NewGuid().ToString('N'))
    try { [IO.File]::WriteAllText($probe, 'ok'); Remove-Item -LiteralPath $probe -Force; return $true } catch { return $false }
}

function Test-RuntimeData([string]$Node) {
    $checker = Join-Path $PSScriptRoot 'verify-runtime-data.mjs'
    & $Node $checker (Join-Path $PaperRoot 'data\ustc_mentor_rag.json') (Join-Path $ProjectRoot 'cloud3d\cloud_data.json')
    if ($LASTEXITCODE -ne 0) { Stop-Startup 'RAG/cloud runtime-data verification failed. Rebuild cloud3d/cloud_data.json or restore a matching data release.' }
}

function Ensure-EnvFiles {
    $codeEnv = Join-Path $CodeRoot '.env'
    if (-not (Test-Path -LiteralPath $codeEnv)) {
        $example = Get-Content -LiteralPath (Join-Path $CodeRoot '.env.example') -Raw
        $bytes = New-Object byte[] 32; $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        [IO.File]::WriteAllText($codeEnv, ($example -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$secret"), (New-Object Text.UTF8Encoding($false)))
        Write-Ok 'Created Code/.env with a random JWT secret'
    }
    $paperEnv = Join-Path $PaperRoot '.env'
    if (-not (Test-Path -LiteralPath $paperEnv)) { Copy-Item -LiteralPath (Join-Path $PaperRoot '.env.example') -Destination $paperEnv; Write-Ok 'Created paper-claw-master/.env from .env.example' }
}

function Ensure-Dependencies([string]$Npm, [string]$Uv) {
    Write-Step 'Checking D-side Node dependencies'
    Push-Location $CodeRoot
    try { & $Npm ls --depth=0 *> $null; if ($LASTEXITCODE -ne 0) { Write-Step 'Installing D-side Node dependencies'; & $Npm install; if ($LASTEXITCODE -ne 0) { Stop-Startup 'npm install failed. Check network/proxy settings and available disk space.' } } } finally { Pop-Location }
    Write-Step 'Checking A-side Python environment and dependencies'
    & $Uv sync --project $BackendRoot --dev
    if ($LASTEXITCODE -ne 0) { Stop-Startup 'uv sync failed. Check network/proxy settings and available disk space.' }
}

function Test-DockerEngine([string]$Docker) { & $Docker info *> $null; return $LASTEXITCODE -eq 0 }
function Ensure-DockerEngine([string]$Docker) {
    if (Test-DockerEngine $Docker) { Write-Ok 'Docker engine is running'; return }
    $desktop = Find-Command 'Docker Desktop.exe' @('%ProgramFiles%\Docker\Docker\Docker Desktop.exe', '%LOCALAPPDATA%\Docker\Docker Desktop.exe')
    if (-not $desktop) { Stop-Startup 'Docker Desktop is installed but its application could not be located.' }
    Write-Step 'Starting Docker Desktop'; Write-Warn 'Docker Desktop may require its first-run agreement, WSL 2, virtualization, or a reboot.'
    Start-Process -FilePath $desktop | Out-Null
    $deadline = (Get-Date).AddMinutes(3)
    do { Start-Sleep -Seconds 3; if (Test-DockerEngine $Docker) { Write-Ok 'Docker engine is ready'; return } } while ((Get-Date) -lt $deadline)
    Stop-Startup 'Docker did not become ready within 3 minutes. Open Docker Desktop and complete its WSL/virtualization setup, then rerun.'
}

function Start-Postgres([string]$Docker) {
    Write-Step "Starting PostgreSQL (Compose project: $($Config.ComposeProject))"
    & $Docker compose --project-name $Config.ComposeProject -f (Join-Path $PaperRoot 'docker-compose.yml') up -d postgres
    if ($LASTEXITCODE -ne 0) { Stop-Startup "PostgreSQL failed to start. Check whether port $($Config.DbPort) is already in use and inspect Docker Desktop." }
    $containerId = (& $Docker compose --project-name $Config.ComposeProject -f (Join-Path $PaperRoot 'docker-compose.yml') ps -q postgres).Trim()
    if (-not $containerId) { Stop-Startup 'PostgreSQL container ID could not be resolved for this project.' }
    $deadline = (Get-Date).AddMinutes(2)
    do { $health = (& $Docker inspect --format '{{.State.Health.Status}}' $containerId 2>$null).Trim(); if ($health -eq 'healthy') { Write-Ok "PostgreSQL is healthy on port $($Config.DbPort)"; return }; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline)
    Stop-Startup 'PostgreSQL did not become healthy. Check Docker Desktop and the Compose logs.'
}

function Apply-Migrations([string]$Uv) {
    $migrationLog = Join-Path $LogRoot 'migration.log'
    Write-Step 'Applying database migrations (a first database can take up to 2 minutes)'
    Write-Host "  Detailed output: $migrationLog"
    Push-Location $PaperRoot
    try {
        # Dependencies are prepared by 检查启动环境.bat.  Do not let a daily
        # launch silently perform another sync/download before the migration.
        # Alembic writes normal INFO lines to stderr.  Running it through cmd
        # prevents PowerShell's strict native-error handling from mistaking
        # those lines for a failed migration.
        $command = "`"$Uv`" run --no-sync --project backend alembic -c backend/alembic.ini upgrade head 1>>`"$migrationLog`" 2>&1"
        & $env:ComSpec /d /c $command
        $migrationExitCode = $LASTEXITCODE
        Get-Content -LiteralPath $migrationLog -Tail 80
        if ($migrationExitCode -ne 0) { Stop-Startup "Database migration failed (exit code $migrationExitCode). See $migrationLog" }
    } finally { Pop-Location }
    Write-Ok 'Database migrations are current'
}

function Invoke-Json([string]$Url, [int]$TimeoutSeconds = 3) { try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSeconds).Content | ConvertFrom-Json } catch { return $null } }
function Test-AService { $payload = Invoke-Json $Config.AHealthUrl; return $null -ne $payload -and $payload.status -eq 'ok' }
function Test-DService { $payload = Invoke-Json $Config.DHealthUrl; return $null -ne $payload -and $payload.status -eq 'ok' -and $payload.rag.ready -eq $true -and [int]$payload.rag.count -gt 0 }
function Test-Frontend { try { $body = (Invoke-WebRequest -UseBasicParsing -Uri $Config.FrontendUrl -TimeoutSec 3).Content; return $body -match 'id="root"' -and $body -match 'src="/src/main\.tsx"' } catch { return $false } }
function Test-PortListening([int]$Port) { return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) }
function Wait-Check([string]$Name, [scriptblock]$Check, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) { if (& $Check) { Write-Ok "$Name is verified"; return }; Start-Sleep -Seconds 2 }
    Stop-Startup "$Name did not become ready within $TimeoutSeconds seconds. See .startup-logs for the service log."
}

function Start-ServiceProcess([string]$Title, [string]$WorkingDirectory, [string]$Command, [string]$LogFile) {
    $full = "title $Title && cd /d `"$WorkingDirectory`" && $Command 1>>`"$LogFile`" 2>&1"
    return (Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d', '/c', $full) -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru).Id
}

function Assert-PreparedEnvironment {
    if (-not (Test-Path -LiteralPath (Join-Path $CodeRoot 'node_modules\.bin\tsx.cmd'))) { Stop-Startup 'D-side dependencies are missing. Run 检查启动环境.bat first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $BackendRoot '.venv\Scripts\python.exe'))) { Stop-Startup 'A-side Python environment is missing. Run 检查启动环境.bat first.' }
}

function Start-ApplicationServices([hashtable]$Tools) {
    $aLog = Join-Path $LogRoot 'a-backend.log'; $dLog = Join-Path $LogRoot 'd-backend.log'; $frontLog = Join-Path $LogRoot 'frontend.log'; $pids = @{}
    if (-not (Test-AService)) { if (Test-PortListening $Config.APort) { Stop-Startup "Port $($Config.APort) is occupied by a service that is not this A backend." }; Write-Step 'Starting A-side backend'; $pids.a_backend = Start-ServiceProcess 'Mentor Platform - A Backend' $PaperRoot "`"$($Tools.Uv)`" run --project backend uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port $($Config.APort)" $aLog }
    if (-not (Test-DService)) { if (Test-PortListening $Config.DPort) { Stop-Startup "Port $($Config.DPort) is occupied by a service that is not this D backend." }; Write-Step 'Starting D-side backend'; $pids.d_backend = Start-ServiceProcess 'Mentor Platform - D Backend' $CodeRoot "`"$($Tools.Npm)`" run dev:backend" $dLog }
    if (-not (Test-Frontend)) { if (Test-PortListening $Config.VitePort) { Stop-Startup "Port $($Config.VitePort) is occupied by a service that is not this frontend." }; Write-Step 'Starting frontend'; $pids.frontend = Start-ServiceProcess 'Mentor Platform - Frontend' $CodeRoot "`"$($Tools.Npm)`" run dev:frontend" $frontLog }
    if ($pids.Count) { $pids | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogRoot 'last-launch-pids.json') -Encoding UTF8 }
    Wait-Check 'A-side backend' { Test-AService } 120
    Wait-Check 'D-side backend with RAG' { Test-DService } 90
    Wait-Check 'Frontend' { Test-Frontend } 90
    # /api/cloud/graph is intentionally authenticated.  The launcher has no
    # user session, so verify the same underlying RAG state through D's public
    # health contract rather than treating its expected 401 as an outage.
    $dHealth = Invoke-Json $Config.DHealthUrl 8
    if (-not $dHealth -or -not $dHealth.rag.ready -or [int]$dHealth.rag.count -le 0) { Stop-Startup 'Business smoke check failed: D backend did not report a ready RAG with mentor data.' }
    Write-Ok "Business smoke check passed: D backend reports $([int]$dHealth.rag.count) RAG mentors"
}

try {
    Write-Host 'Mentor Platform portable launcher' -ForegroundColor White; Write-Host "Project: $ProjectRoot"
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    if (-not (Test-ProjectWritable)) { Stop-Startup 'The project directory is not writable. Extract the ZIP first and move the project to a writable local folder (not Program Files or a read-only share).' }
    foreach ($required in @($CodeRoot, $BackendRoot, (Join-Path $PaperRoot 'docker-compose.yml'), (Join-Path $PaperRoot 'data\ustc_mentor_rag.json'), (Join-Path $ProjectRoot 'cloud3d\cloud_data.json'))) { if (-not (Test-Path -LiteralPath $required)) { Stop-Startup "Required project path is missing: $required" } }
    Ensure-EnvFiles; Initialize-RuntimeConfig
    if ($LaunchOnly) {
        $tools = Ensure-Node; Test-RuntimeData $tools.Node; $tools.Uv = Ensure-Uv; $tools.Docker = Ensure-Docker; Assert-PreparedEnvironment
        Ensure-DockerEngine $tools.Docker; Start-Postgres $tools.Docker; Apply-Migrations $tools.Uv; Start-ApplicationServices $tools
        Write-Host "`nAll core services are verified:" -ForegroundColor Green; Write-Host "  Frontend:   $($Config.FrontendUrl)"; Write-Host "  D backend:  $($Config.DHealthUrl)"; Write-Host "  A backend:  $($Config.AHealthUrl)"; Write-Host "  Logs:       $LogRoot"
        if (-not $NoBrowser) { Start-Process $Config.FrontendUrl | Out-Null }
    } else {
        Write-Step 'Checking and preparing the complete environment'; $tools = Ensure-Node; Test-RuntimeData $tools.Node; $tools.Uv = Ensure-Uv; $tools.Docker = Ensure-Docker
        if ($CheckOnly) { Write-Ok 'Basic tool/config/data check completed. Use 检查启动环境.bat for dependency installation and migrations.'; exit 0 }
        Ensure-Dependencies $tools.Npm $tools.Uv; Ensure-DockerEngine $tools.Docker; Start-Postgres $tools.Docker; Apply-Migrations $tools.Uv
        Write-Host "`nEnvironment preparation completed. Use 启动项目.bat to start and verify the application." -ForegroundColor Green
    }
    exit 0
} catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red; Write-Host "Logs: $LogRoot" -ForegroundColor Yellow
    if ($PauseOnFailure) { Read-Host 'Startup failed. Press Enter to close this window' | Out-Null }
    exit 1
}
