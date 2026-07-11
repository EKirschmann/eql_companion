# One-time safety net: full copy of the stock uifiles\default skin.
# This is the fallback if anything ever goes wrong. Run once, before editing.
. "$PSScriptRoot\_config.ps1"

$src = Join-Path $UiFiles "default"
if (-not (Test-Path $src)) { throw "Stock default skin not found at $src" }

if (Test-Path $BackupDir) {
    Write-Host "Backup already exists at $BackupDir - leaving it untouched." -ForegroundColor Yellow
    return
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -Path (Join-Path $src "*") -Destination $BackupDir -Recurse -Force
$count = (Get-ChildItem $BackupDir -Recurse -File | Measure-Object).Count
Write-Host "Backed up $count files to $BackupDir" -ForegroundColor Green
