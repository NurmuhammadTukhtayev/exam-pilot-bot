<#
.SYNOPSIS
  One-time setup on Windows Server: Python virtual environment, packages, database schema,
  question import, and two auto-starting Windows services managed by NSSM:
    TestBot-Bot     python -m bot                         (Telegram bot, long polling)
    TestBot-WebApp  python -m uvicorn webapp.main:app     (Mini App on 127.0.0.1:8000, behind IIS)

  Safe to run again: existing services are reconfigured, data is kept.

.EXAMPLE
  # from the repository folder, in an elevated PowerShell:
  powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 `
      -Python "C:\Program Files\Python313\python.exe" -Nssm "C:\tools\nssm\nssm.exe" `
      -PostgresService "postgresql-x64-17"
#>
param(
    # Python 3.12+ used to create the virtual environment
    [string]$Python = "python",
    # Path to nssm.exe (or "nssm" if it is on PATH)
    [string]$Nssm = "nssm",
    # Port the Mini App listens on (localhost only; IIS proxies to it)
    [int]$Port = 8000,
    # Optional: name of the PostgreSQL Windows service, so our services start after it
    [string]$PostgresService = "",
    [string]$BotService = "TestBot-Bot",
    [string]$WebService = "TestBot-WebApp",
    # Skip the question import (e.g. when reinstalling services only)
    [switch]$SkipImport
)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Assert-EnvFile

if (-not (Get-Command $Nssm -ErrorAction SilentlyContinue)) {
    throw "nssm.exe not found ('$Nssm'). Download it from https://nssm.cc/download and pass -Nssm <path>."
}

Write-Step "Creating the virtual environment (.venv)"
if (-not (Test-Path $VenvPython)) {
    Invoke-Checked $Python @("-m", "venv", (Join-Path $Root ".venv"))
}
Invoke-Checked $VenvPython @("-c", "import sys; assert sys.version_info >= (3, 12), sys.version; print(sys.version)")

Stop-AppServices @($BotService, $WebService)
Install-Dependencies
Update-Database
if (-not $SkipImport) { Import-Questions }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Install-AppService([string]$Name, [string]$Arguments, [string]$LogFile, [string]$Description) {
    Write-Step "Configuring service $Name"
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) {
        Invoke-Checked $Nssm @("install", $Name, $VenvPython)
    }
    $log = Join-Path $LogDir $LogFile
    $settings = @(
        @("Application", $VenvPython),
        @("AppParameters", $Arguments),
        @("AppDirectory", $Root),
        @("DisplayName", $Name),
        @("Description", $Description),
        @("Start", "SERVICE_AUTO_START"),
        @("AppStdout", $log),
        @("AppStderr", $log),
        @("AppRotateFiles", "1"),
        @("AppRotateOnline", "1"),
        @("AppRotateBytes", "10485760"),
        @("AppExit", "Default", "Restart"),
        @("AppRestartDelay", "5000"),
        @("AppStopMethodConsole", "15000"),
        @("AppEnvironmentExtra", "PYTHONUTF8=1", "PYTHONUNBUFFERED=1")
    )
    foreach ($setting in $settings) { Invoke-Checked $Nssm (@("set", $Name) + $setting) }
    if ($PostgresService) { Invoke-Checked $Nssm @("set", $Name, "DependOnService", $PostgresService) }
}

Install-AppService $BotService "-m bot" "bot.log" "Exam test Telegram bot (long polling)"
Install-AppService $WebService `
    "-m uvicorn webapp.main:app --host 127.0.0.1 --port $Port --proxy-headers --forwarded-allow-ips 127.0.0.1" `
    "webapp.log" "Exam test Mini App (behind IIS)"

Write-Step "Starting services"
Start-AppServices @($WebService, $BotService)
Test-Deployment -Port $Port -BotService $BotService

Write-Host ""
Write-Host "Installed. After each 'git pull', run: deploy\windows\update.ps1" -ForegroundColor Green
