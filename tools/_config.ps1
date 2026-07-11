# Shared config for EQ Legends UI mod tooling.
# Dot-source this from other scripts:  . "$PSScriptRoot\_config.ps1"

$GameRoot   = "G:\Daybreak Game Company\Installed Games\EverQuest Legends"
$UiFiles    = Join-Path $GameRoot "uifiles"
$SkinName   = "StoneGlass"                    # loaded in-game via: /loadskin StoneGlass
$RepoRoot   = Split-Path $PSScriptRoot -Parent
$SkinSource = Join-Path $RepoRoot "skin"      # the custom skin we author
$DeployDest = Join-Path $UiFiles $SkinName    # where it lives in the game
$BackupDir  = Join-Path $RepoRoot "backup\default-full"  # full stock backup (git-ignored)
