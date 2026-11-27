<#
.SYNOPSIS
  Back up the PostgreSQL database with pg_dump (custom format) and delete backups older than N days.
  Reads the connection from DATABASE_URL in the deploy folder's .env. Schedule it daily with
  Task Scheduler.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File C:\MyWebApps\exam-pilot-bot\deploy\windows\backup.ps1 `
      -PgDump "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -Destination "D:\backups\exam-pilot-bot"

  Restore:  pg_restore -U <user> -d <dbname> --clean <file>.dump
#>
param(
    [string]$DeployDir = "C:\inetpub\exam-pilot-bot",
    [string]$PgDump = "pg_dump",
    [string]$Destination = "",
    [int]$KeepDays = 14
)

if (-not $PSScriptRoot -or -not (Test-Path (Join-Path $PSScriptRoot "common.ps1"))) {
    throw "Run backup.ps1 where it lives, inside the git clone: <clone>\deploy\windows\backup.ps1"
}
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $Destination) { $Destination = Join-Path $DeployDir "backups" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$url = Get-EnvValue (Join-Path $DeployDir ".env") "DATABASE_URL"
if ($url -notmatch "^postgresql\+asyncpg://([^:]+):([^@]*)@([^:/]+)(?::(\d+))?/(.+)$") {
    throw "DATABASE_URL in $DeployDir\.env is not a postgresql+asyncpg:// URL"
}
$user, $password, $dbHost, $port, $db = $Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5]
if (-not $port) { $port = "5432" }

$file = Join-Path $Destination ("exam-pilot-bot_{0}.dump" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))
$env:PGPASSWORD = [Uri]::UnescapeDataString($password)
try {
    Invoke-Checked $PgDump @("-h", $dbHost, "-p", $port, "-U", $user, "-Fc", "-f", $file, $db)
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host "Backup written: $file"

Get-ChildItem $Destination -Filter "exam-pilot-bot_*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    ForEach-Object { Write-Host "Removing old backup $($_.Name)"; Remove-Item $_.FullName }
