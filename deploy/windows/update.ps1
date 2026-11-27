<#
.SYNOPSIS
  Deploy a new version after "git pull": stops the services, installs packages, applies database
  migrations, optionally re-imports the question documents, starts the services and checks them.

.EXAMPLE
  # in the repository folder, in an elevated PowerShell:
  git pull
  powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
  # after adding or changing .docx files in docs\:
  powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -ImportDocs
#>
param(
    [switch]$ImportDocs,
    [int]$Port = 8000,
    [string]$BotService = "TestBot-Bot",
    [string]$WebService = "TestBot-WebApp"
)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Assert-EnvFile

if (-not (Test-Path $VenvPython)) { throw "No .venv found. Run deploy\windows\install.ps1 first." }

$commit = "(git not found)"
try { $commit = (& git -C $Root log -1 --format="%h %s") } catch { }
Write-Host "Deploying commit: $commit"

# Stop first: Windows locks files that running services use, so pip could not replace them.
Write-Step "Stopping services"
Stop-AppServices @($BotService, $WebService)

try {
    Install-Dependencies
    Update-Database
    if ($ImportDocs) { Import-Questions }
} catch {
    Write-Host ""
    Write-Host "Update failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Services are left stopped. Fix the problem (or 'git checkout' the previous version) and run again."
    throw
}

Write-Step "Starting services"
Start-AppServices @($WebService, $BotService)
Test-Deployment -Port $Port -BotService $BotService
Write-Host ""
Write-Host "Update complete." -ForegroundColor Green
