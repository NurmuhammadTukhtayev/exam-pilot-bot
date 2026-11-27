<#
.SYNOPSIS
  Back up the PostgreSQL database with pg_dump (custom format) and delete backups older than N days.
  Reads the connection from DATABASE_URL in .env. Schedule it daily with Task Scheduler.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1 `
      -PgDump "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -Destination "D:\backups\testbot"

  Restore:  pg_restore -U <user> -d <dbname> --clean <file>.dump
#>
param(
    [string]$PgDump = "pg_dump",
    [string]$Destination = "",
    [int]$KeepDays = 14
)

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $Destination) { $Destination = Join-Path $Root "backups" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$line = Select-String -Path (Join-Path $Root ".env") -Pattern "^DATABASE_URL=" | Select-Object -First 1
if (-not $line) { throw "DATABASE_URL not found in .env" }
$url = $line.Line.Substring("DATABASE_URL=".Length).Trim()
if ($url -notmatch "^postgresql\+asyncpg://([^:]+):([^@]*)@([^:/]+)(?::(\d+))?/(.+)$") {
    throw "DATABASE_URL is not a postgresql+asyncpg:// URL"
}
$user, $password, $dbHost, $port, $db = $Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5]
if (-not $port) { $port = "5432" }

$file = Join-Path $Destination ("testbot_{0}.dump" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))
$env:PGPASSWORD = [Uri]::UnescapeDataString($password)
try {
    Invoke-Checked $PgDump @("-h", $dbHost, "-p", $port, "-U", $user, "-Fc", "-f", $file, $db)
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host "Backup written: $file"

Get-ChildItem $Destination -Filter "testbot_*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    ForEach-Object { Write-Host "Removing old backup $($_.Name)"; Remove-Item $_.FullName }
