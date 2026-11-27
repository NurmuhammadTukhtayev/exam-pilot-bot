# Shared helpers for install.ps1 / update.ps1 / backup.ps1 (Windows PowerShell 5.1+).
# Keep this file ASCII-only: PowerShell 5.1 reads BOM-less scripts in the ANSI code page.

$ErrorActionPreference = "Stop"

# Repository root = two folders up from deploy\windows
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script in an elevated PowerShell (Run as Administrator)."
    }
}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

# Run a native program and stop on a non-zero exit code.
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit code $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

function Assert-EnvFile {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $Root ".env.example") $envFile
        throw "Created $envFile from the template. Fill in BOT_TOKEN, DATABASE_URL and WEBAPP_URL, then run again."
    }
    $content = Get-Content $envFile -Raw
    if ($content -notmatch "(?m)^BOT_TOKEN=\S+") { throw "BOT_TOKEN is empty in $envFile" }
    if ($content -notmatch "(?m)^DATABASE_URL=postgresql\+asyncpg://") {
        throw "DATABASE_URL in $envFile must be postgresql+asyncpg://user:password@host:5432/dbname"
    }
    if ($content -match "(?m)^WEBAPP_DEV_USER_ID=\S+") {
        throw "WEBAPP_DEV_USER_ID is set in $envFile. Remove it: it is for local development only."
    }
}

function Install-Dependencies {
    Write-Step "Installing Python packages"
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", (Join-Path $Root "requirements.txt"), "--quiet")
}

function Update-Database {
    Write-Step "Applying database migrations"
    Push-Location $Root
    try { Invoke-Checked $VenvPython @("-m", "alembic", "upgrade", "head") } finally { Pop-Location }
}

function Import-Questions {
    Write-Step "Importing questions from docs\*.docx"
    Push-Location $Root
    try { Invoke-Checked $VenvPython @("import_docs.py") } finally { Pop-Location }
}

function Stop-AppServices([string[]]$Names) {
    foreach ($name in $Names) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -ne "Stopped") {
            Write-Host "Stopping $name"
            Stop-Service -Name $name
            $svc.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
        }
    }
}

function Start-AppServices([string[]]$Names) {
    foreach ($name in $Names) {
        Write-Host "Starting $name"
        Start-Service -Name $name
    }
}

# Wait for the Mini App health endpoint and check the bot service stays up.
function Test-Deployment([int]$Port, [string]$BotService) {
    Write-Step "Checking the deployment"
    $url = "http://127.0.0.1:$Port/healthz"
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { $healthy = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if ($healthy) { Write-Host "Mini App: OK ($url)" -ForegroundColor Green }
    else { Write-Host "Mini App: NOT responding on $url. See logs\webapp.log" -ForegroundColor Red }

    Start-Sleep -Seconds 5
    $bot = Get-Service -Name $BotService
    if ($bot.Status -eq "Running") { Write-Host "Bot: running" -ForegroundColor Green }
    else { Write-Host "Bot: $($bot.Status). See logs\bot.log" -ForegroundColor Red }

    $botLog = Join-Path $LogDir "bot.log"
    if (Test-Path $botLog) {
        Write-Host ""
        Write-Host "Last lines of logs\bot.log:"
        Get-Content $botLog -Tail 8
    }
    if (-not $healthy -or $bot.Status -ne "Running") { throw "Deployment check failed." }
}
