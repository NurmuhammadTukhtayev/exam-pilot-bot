# Shared helpers for deploy.ps1 / backup.ps1 (Windows PowerShell 5.1+).
# Keep this file ASCII-only: PowerShell 5.1 reads BOM-less scripts in the ANSI code page.

$ErrorActionPreference = "Stop"

# The git clone these scripts live in = two folders up from deploy\windows
$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

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

# Value of KEY=value in a .env file ("" if missing).
function Get-EnvValue([string]$EnvFile, [string]$Key) {
    $line = Select-String -Path $EnvFile -Pattern "^$Key=" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $line) { return "" }
    return $line.Line.Substring($Key.Length + 1).Trim()
}

# The production .env lives in the deploy folder (never in git, never touched by robocopy).
function Assert-EnvFile([string]$DeployDir) {
    $envFile = Join-Path $DeployDir ".env"
    if (-not (Test-Path $envFile)) {
        New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
        Copy-Item (Join-Path $SourceDir ".env.example") $envFile
        throw "Created $envFile from the template. Fill in BOT_TOKEN, DATABASE_URL and WEBAPP_URL, then run again."
    }
    if (-not (Get-EnvValue $envFile "BOT_TOKEN")) { throw "BOT_TOKEN is empty in $envFile" }
    if ((Get-EnvValue $envFile "DATABASE_URL") -notmatch "^postgresql\+asyncpg://") {
        throw "DATABASE_URL in $envFile must be postgresql+asyncpg://user:password@host:5432/dbname"
    }
    if (Get-EnvValue $envFile "WEBAPP_DEV_USER_ID") {
        throw "WEBAPP_DEV_USER_ID is set in $envFile. Remove it: it is for local development only."
    }
}

function Stop-AppServices([string[]]$Names) {
    foreach ($name in $Names) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -ne "Stopped") {
            Write-Host "Stopping $name"
            Stop-Service -Name $name
        }
    }
}

# GET a URL; returns the response, or $null after $Seconds of failures.
function Wait-Http([string]$Url, [int]$Seconds = 30) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $response }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $null
}
