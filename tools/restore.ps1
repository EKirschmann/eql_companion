# Remove the deployed custom skin from the game. Does NOT touch uifiles\default.
# Switch back in-game first with /loadskin default, then run this.
. "$PSScriptRoot\_config.ps1"

if (Test-Path $DeployDest) {
    Remove-Item $DeployDest -Recurse -Force
    Write-Host "Removed $DeployDest" -ForegroundColor Green
} else {
    Write-Host "Nothing to remove - $DeployDest does not exist." -ForegroundColor Yellow
}
Write-Host "If you are in-game, run: /loadskin default" -ForegroundColor Cyan
