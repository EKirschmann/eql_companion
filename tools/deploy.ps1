# Deploy the authored skin into the game so it can be loaded with /loadskin modern_overhaul.
# A custom skin only needs the files it changes; anything missing falls back to uifiles\default.
. "$PSScriptRoot\_config.ps1"

if (-not (Test-Path $SkinSource)) { throw "Skin source not found at $SkinSource" }

New-Item -ItemType Directory -Force -Path $DeployDest | Out-Null

# Mirror skin\ -> uifiles\modern_overhaul\ (copy changed/new, prune removed).
$files = Get-ChildItem $SkinSource -Recurse -File
foreach ($f in $files) {
    $rel  = $f.FullName.Substring($SkinSource.Length).TrimStart('\')
    $dest = Join-Path $DeployDest $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item $f.FullName $dest -Force
}

# Prune files in the deployed skin that no longer exist in source.
Get-ChildItem $DeployDest -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($DeployDest.Length).TrimStart('\')
    if (-not (Test-Path (Join-Path $SkinSource $rel))) { Remove-Item $_.FullName -Force }
}

$count = ($files | Measure-Object).Count
Write-Host "Deployed $count files to $DeployDest" -ForegroundColor Green
Write-Host "In-game: /loadskin $SkinName   (or relog and pick it on the character-select skin menu)" -ForegroundColor Cyan
