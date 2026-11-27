<#
.SYNOPSIS
  TEMPORARY HTTPS for the Mini App until the real domain works: runs a Cloudflare quick tunnel as a
  Windows service (ExamPilot-Tunnel). No open ports, DNS or certificate needed.

  The tunnel URL (https://<random>.trycloudflare.com) changes whenever the tunnel restarts; the
  service then writes the new URL into the deploy folder's .env (WEBAPP_URL) and restarts the bot,
  so the bot's Mini App button always points at the live tunnel. Quick tunnels are meant for
  testing and have no uptime guarantee: switch to the real domain as soon as it works.

.EXAMPLE
  # install / update (elevated PowerShell, from the git clone):
  powershell -ExecutionPolicy Bypass -File deploy\windows\temp-tunnel.ps1 `
      -Nssm "C:\tools\nssm-2.24\win64\nssm.exe" -Cloudflared "C:\tools\cloudflared\cloudflared.exe"

  # remove it once the domain works (then set WEBAPP_URL=https://<domain>/ and run the deploy):
  powershell -ExecutionPolicy Bypass -File deploy\windows\temp-tunnel.ps1 -Nssm "..." -Remove
#>
param(
    [string]$DeployDir = "C:\inetpub\exam-pilot-bot",
    [string]$Nssm = "nssm",
    [string]$Cloudflared = "C:\tools\cloudflared\cloudflared.exe",
    [int]$Port = 8000,
    [string]$BotService = "ExamPilot-Bot",

    [string]$TunnelService = "ExamPilot-Tunnel",
    [switch]$Remove
)

if (-not $PSScriptRoot -or -not (Test-Path (Join-Path $PSScriptRoot "common.ps1"))) {
    throw "Run temp-tunnel.ps1 where it lives, inside the git clone: <clone>\deploy\windows\temp-tunnel.ps1"
}
. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
if (-not (Get-Command $Nssm -ErrorAction SilentlyContinue)) { throw "nssm.exe not found ('$Nssm'). Pass -Nssm <path>." }

$envFile = Join-Path $DeployDir ".env"

if ($Remove) {
    if (Get-Service -Name $TunnelService -ErrorAction SilentlyContinue) {
        Stop-AppServices @($TunnelService)
        Invoke-Checked $Nssm @("remove", $TunnelService, "confirm")
        Write-Host "Removed $TunnelService." -ForegroundColor Green
    } else {
        Write-Host "$TunnelService is not installed."
    }
    Write-Host "Next: set WEBAPP_URL=https://<your-domain>/ in $envFile and run the deploy again."
    return
}

if (-not (Test-Path $Cloudflared)) {
    throw "cloudflared.exe not found at '$Cloudflared'. Download it from " +
          "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe " +
          "and pass -Cloudflared <path>."
}
$venvPython = Join-Path $DeployDir ".venv\Scripts\python.exe"
$script = Join-Path $DeployDir "dev_tunnel.py"
if (-not (Test-Path $venvPython) -or -not (Test-Path $script)) {
    throw "Deploy the app first (deploy.ps1): $venvPython or $script is missing."
}
if (-not (Get-Service -Name $BotService -ErrorAction SilentlyContinue)) { throw "Service $BotService not found. Deploy first." }
# The service runs the deploy folder's copy of dev_tunnel.py: it must be the clone's current version.
if ((Get-FileHash $script).Hash -ne (Get-FileHash (Join-Path $SourceDir "dev_tunnel.py")).Hash) {
    throw "The deploy folder has an older dev_tunnel.py than the git clone. Run the deploy first " +
          "(Desktop launcher or deploy.ps1), then run this script again."
}
$webApp = Wait-Http "http://127.0.0.1:$Port/healthz" 10
if (-not $webApp) { throw "The Mini App doesn't answer on http://127.0.0.1:$Port. Check the ExamPilot-WebApp service." }

Write-Step "Configuring $TunnelService"
if (-not (Get-Service -Name $TunnelService -ErrorAction SilentlyContinue)) {
    Invoke-Checked $Nssm @("install", $TunnelService, $venvPython)
}
$arguments = "dev_tunnel.py --port $Port --env-file `"$envFile`" --cloudflared `"$Cloudflared`" " +
             "--restart-service $BotService"
$log = Join-Path $DeployDir "logs\tunnel.log"
$settings = @(
    @("Application", $venvPython),
    @("AppParameters", $arguments),
    @("AppDirectory", $DeployDir),
    @("DisplayName", $TunnelService),
    @("Description", "TEMPORARY Cloudflare quick tunnel for the Exam Pilot Mini App (until the domain works)"),
    @("Start", "SERVICE_AUTO_START"),
    @("AppStdout", $log),
    @("AppStderr", $log),
    @("AppRotateFiles", "1"),
    @("AppRotateOnline", "1"),
    @("AppRotateBytes", "10485760"),
    @("AppExit", "Default", "Restart"),
    @("AppRestartDelay", "10000"),
    # No DependOnService on the Mini App: deploy.ps1 must be able to stop the Mini App service while the
    # tunnel keeps running (same URL). At boot the tunnel just retries until the Mini App answers.
    @("AppEnvironmentExtra", "PYTHONUTF8=1", "PYTHONUNBUFFERED=1")
)
foreach ($setting in $settings) { Invoke-Checked $Nssm (@("set", $TunnelService) + $setting) | Out-Null }

Write-Step "Starting $TunnelService"
$before = Get-EnvValue $envFile "WEBAPP_URL"
Stop-AppServices @($TunnelService)
Start-Service -Name $TunnelService

# Wait for the service to publish a new tunnel URL and restart the bot.
$url = ""
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 1
    $current = Get-EnvValue $envFile "WEBAPP_URL"
    if ($current -match "trycloudflare\.com" -and $current -ne $before) { $url = $current; break }
}
if (-not $url) {
    # Don't leave a broken service restarting every few seconds.
    Stop-AppServices @($TunnelService)
    Write-Host ""
    Write-Host "Last lines of $log :" -ForegroundColor Yellow
    if (Test-Path $log) { Get-Content $log -Tail 25 }
    throw "No tunnel URL after 2 minutes; $TunnelService was stopped. See the log lines above."
}
Write-Host "Tunnel URL: $url" -ForegroundColor Green

$page = Wait-Http $url 60
if ($page -and $page.Content -match "app\.js") { Write-Host "Mini App via tunnel: OK" -ForegroundColor Green }
else { Write-Host "Mini App not reachable through the tunnel yet. Check $log in a minute." -ForegroundColor Yellow }
Start-Sleep -Seconds 5
Write-Host "Bot service: $((Get-Service -Name $BotService).Status)"
Write-Host ""
Write-Host "Open the bot in Telegram (close and reopen the chat): the Mini App button uses the tunnel now."
