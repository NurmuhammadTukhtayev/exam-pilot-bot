<#
.SYNOPSIS
  Deploy (or first-time install) on Windows Server, from a git clone into the IIS deploy folder.

  Run it from the git clone, in an elevated PowerShell:
      cd C:\MyWebApps\exam-pilot-bot
      git pull
      powershell -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1

  Steps (same order every time, safe to repeat):
    1. stop the services (Windows locks files that running programs use)
    2. robocopy /MIR the clone into the deploy folder (server-only files are excluded, see below)
    3. copy the IIS proxy config (deploy\windows\web.config) to the deploy folder root
    4. create the virtual environment if missing, install packages
    5. apply database migrations, import the question documents (docs\*.docx)
    6. create/update the two Windows services via NSSM, start them
    7. smoke test: local health check, public URL (WEBAPP_URL), bot service running

  Server-only files in the deploy folder that robocopy must never delete or overwrite:
    .env (secrets), .venv, logs, backups, data, .well-known (win-acme certificate checks)
#>
param(
    # IIS site folder = where the app runs from
    [string]$DeployDir = "C:\inetpub\exam-pilot-bot",
    # Python 3.12+ used only to create the virtual environment (first run)
    [string]$Python = "python",
    # nssm.exe (full path, or "nssm" if it is on PATH)
    [string]$Nssm = "nssm",
    # Name of the PostgreSQL Windows service (optional): our services start after it
    [string]$PostgresService = "",
    [int]$Port = 8000,
    [string]$BotService = "ExamPilot-Bot",
    [string]$WebService = "ExamPilot-WebApp",
    # Skip re-importing docs\*.docx (the import is idempotent, so it normally runs every time)
    [switch]$SkipImport
)

if (-not $PSScriptRoot -or -not (Test-Path (Join-Path $PSScriptRoot "common.ps1"))) {
    throw "Run deploy.ps1 where it lives, inside the git clone (it needs common.ps1 and the code around it): " +
          "<clone>\deploy\windows\deploy.ps1. Don't copy or paste it elsewhere. For a Desktop shortcut, " +
          "copy deploy\windows\desktop-deploy.example.ps1 instead."
}
. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Assert-EnvFile $DeployDir
if (-not (Get-Command $Nssm -ErrorAction SilentlyContinue)) {
    throw "nssm.exe not found ('$Nssm'). Download it from https://nssm.cc/download and pass -Nssm <path>."
}
if ($PostgresService -and -not (Get-Service -Name $PostgresService -ErrorAction SilentlyContinue)) {
    $found = @(Get-Service -Name "*postgres*" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $hint = "No PostgreSQL Windows service found on this server (database on another machine?)."
    if ($found.Count) { $hint = "PostgreSQL services on this server: $($found -join ', ')." }
    throw "PostgreSQL service '$PostgresService' doesn't exist. $hint " +
          "Pass the right name with -PostgresService, or leave it empty to skip the start-order dependency."
}
if ($SourceDir.TrimEnd("\") -ieq $DeployDir.TrimEnd("\")) {
    throw "Run this from the git clone, not from the deploy folder ($DeployDir)."
}

$VenvPython = Join-Path $DeployDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $DeployDir "logs"
$commit = "(unknown)"
try { $commit = (& git -C $SourceDir log -1 --format="%h %s") } catch { }
Write-Host "Deploying $commit"
Write-Host "  from $SourceDir"
Write-Host "  to   $DeployDir"

Write-Step "1/7 Stopping services"
Stop-AppServices @($BotService, $WebService)

Write-Step "2/7 Syncing code (robocopy /MIR)"
robocopy $SourceDir $DeployDir /MIR /R:2 /W:2 /NFL /NDL /NP /NJH `
    /XD .git .github .venv venv __pycache__ .pytest_cache .ruff_cache .vscode .idea `
        logs backups data .well-known tests `
    /XF .env web.config *.pyc
$rc = $LASTEXITCODE
if ($rc -ge 8) { throw "Robocopy failed with exit code $rc" }
Write-Host "Robocopy finished (exit code $rc = success)"

Write-Step "3/7 IIS proxy config"
Copy-Item (Join-Path $SourceDir "deploy\windows\web.config") (Join-Path $DeployDir "web.config") -Force
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Step "4/7 Python environment"
if (-not (Test-Path $VenvPython)) {
    Invoke-Checked $Python @("-m", "venv", (Join-Path $DeployDir ".venv"))
}
Invoke-Checked $VenvPython @("-c", "import sys; assert sys.version_info >= (3, 12), sys.version; print(sys.version)")
Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", (Join-Path $DeployDir "requirements.txt"), "--quiet")

Write-Step "5/7 Database"
Push-Location $DeployDir
try {
    # Clear message for a wrong DATABASE_URL (instead of a long traceback from the migration)
    & $VenvPython -m bot.dbcheck
    if ($LASTEXITCODE -ne 0) { throw "Fix DATABASE_URL in $DeployDir\.env and run the deploy again." }
    Invoke-Checked $VenvPython @("-m", "alembic", "upgrade", "head")
    if (-not $SkipImport) { Invoke-Checked $VenvPython @("import_docs.py") }
} finally { Pop-Location }

Write-Step "6/7 Services"
function Set-AppService([string]$Name, [string]$Arguments, [string]$LogFile, [string]$Description) {
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) {
        Invoke-Checked $Nssm @("install", $Name, $VenvPython)
    }
    $log = Join-Path $LogDir $LogFile
    $settings = @(
        @("Application", $VenvPython),
        @("AppParameters", $Arguments),
        @("AppDirectory", $DeployDir),
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
    foreach ($setting in $settings) { Invoke-Checked $Nssm (@("set", $Name) + $setting) | Out-Null }
    if ($PostgresService) { Invoke-Checked $Nssm @("set", $Name, "DependOnService", $PostgresService) | Out-Null }
    Write-Host "Configured $Name"
}
Set-AppService $WebService `
    "-m uvicorn webapp.main:app --host 127.0.0.1 --port $Port --proxy-headers --forwarded-allow-ips 127.0.0.1" `
    "webapp.log" "Exam Pilot Mini App (behind IIS)"
Set-AppService $BotService "-m bot" "bot.log" "Exam Pilot Telegram bot (long polling)"
Start-Service -Name $WebService
Start-Service -Name $BotService

Write-Step "7/7 Smoke test"
$failed = @()
if (Wait-Http "http://127.0.0.1:$Port/healthz") { Write-Host "Mini App (local): OK" -ForegroundColor Green }
else { $failed += "Mini App not responding on 127.0.0.1:$Port (see logs\webapp.log)" }

$publicUrl = Get-EnvValue (Join-Path $DeployDir ".env") "WEBAPP_URL"
if ($publicUrl) {
    $base = $publicUrl.TrimEnd("/")
    $page = Wait-Http "$base/" 15
    if ($page -and $page.Content -match "app\.js") { Write-Host "Mini App (public $base): OK" -ForegroundColor Green }
    else { $failed += "Public URL $base/ not serving the Mini App (IIS site, HTTPS binding, web.config, ARR?)" }
} else {
    Write-Host "WEBAPP_URL is empty: Mini App buttons are off, skipping the public check." -ForegroundColor Yellow
}

Start-Sleep -Seconds 5
$bot = Get-Service -Name $BotService
if ($bot.Status -eq "Running") { Write-Host "Bot service: running" -ForegroundColor Green }
else { $failed += "Bot service is $($bot.Status) (see logs\bot.log)" }
$botLog = Join-Path $LogDir "bot.log"
if (Test-Path $botLog) { Write-Host ""; Write-Host "Last lines of logs\bot.log:"; Get-Content $botLog -Tail 8 }

if ($failed.Count) {
    Write-Host ""
    $failed | ForEach-Object { Write-Host "FAILED: $_" -ForegroundColor Red }
    throw "Smoke test failed."
}
Write-Host ""
Write-Host "Deployed $commit" -ForegroundColor Green
