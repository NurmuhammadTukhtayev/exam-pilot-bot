<#
.SYNOPSIS
  One-click deploy launcher. Copy this file anywhere (e.g. the Desktop), set the paths below once,
  then run it in an elevated PowerShell (Run as Administrator).

  It pulls the latest code into the git clone and runs the clone's own deploy\windows\deploy.ps1,
  so this launcher never goes out of date when the deploy script changes.
#>

# ---- your server's paths (edit once) -------------------------------------------------------------
$Clone           = "C:\MyWebApps\exam-pilot-bot"     # git clone
$DeployDir       = "C:\inetpub\exam-pilot-bot"       # IIS site folder the app runs from
$Python          = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
$Nssm            = "C:\tools\nssm-2.24\win64\nssm.exe"
$PostgresService = "postgresql-x64-17"               # Get-Service *postgres*  ("" to skip)
# ---------------------------------------------------------------------------------------------------

$ErrorActionPreference = "Stop"
$exitCode = 1
try {
    Set-Location $Clone
    Write-Host "==> git pull ($Clone)" -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed (local changes in the clone, or no access to GitHub?)" }

    $deployArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", (Join-Path $Clone "deploy\windows\deploy.ps1"),
                    "-DeployDir", $DeployDir, "-Python", $Python, "-Nssm", $Nssm)
    if ($PostgresService) { $deployArgs += @("-PostgresService", $PostgresService) }
    & powershell.exe @deployArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Deployment failed (see the messages above)." }
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
} finally {
    Write-Host ""
    Read-Host "Press Enter to close"
}
exit $exitCode
