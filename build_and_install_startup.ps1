$ErrorActionPreference = "Stop"

function Assert-PathExists([string]$PathToCheck, [string]$Hint) {
  if (-not (Test-Path -LiteralPath $PathToCheck)) {
    throw "Path not found: $PathToCheck`n$Hint"
  }
}

function New-OrUpdate-Shortcut(
  [Parameter(Mandatory=$true)][string]$ShortcutPath,
  [Parameter(Mandatory=$true)][string]$TargetPath,
  [string]$WorkingDirectory,
  [string]$IconLocation,
  [string]$Arguments = ""
) {
  $shell = New-Object -ComObject WScript.Shell
  $sc = $shell.CreateShortcut($ShortcutPath)
  $sc.TargetPath = $TargetPath
  if ($WorkingDirectory) { $sc.WorkingDirectory = $WorkingDirectory }
  if ($IconLocation) { $sc.IconLocation = $IconLocation }
  if ($Arguments) { $sc.Arguments = $Arguments }
  $sc.Save()
}

$repoRoot = $PSScriptRoot
Set-Location -LiteralPath $repoRoot

Assert-PathExists (Join-Path $repoRoot "main.py") "Run this script from the repo root (where main.py is)."

Write-Host "Running PyInstaller build..." -ForegroundColor Cyan

$pyinstallerArgs = @(
  "--noconfirm"
  "--clean"
  "--onedir"
  "--windowed"
  "--name", "WindowsStatistics"
  "--add-data", "daily.html;."
  "--add-data", "weekly.html;."
  "--add-data", "mock-header-choices.html;."
  "--add-data", "echarts.min.js;."
  "--add-data", "statistics.configuration.json;."
  "--add-data", "statistics_light.ico;."
  "--add-data", "statistics_dark.ico;."
  "main.py"
)

& pyinstaller @pyinstallerArgs

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed. Exit code: $LASTEXITCODE"
}

$exePath = Join-Path $repoRoot "dist\WindowsStatistics\WindowsStatistics.exe"
Assert-PathExists $exePath "Expected output: dist\\WindowsStatistics\\WindowsStatistics.exe"

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
Assert-PathExists $startupDir "Startup folder not found: $startupDir"

$shortcutPath = Join-Path $startupDir "WindowsStatistics.lnk"

$iconPath = Join-Path $repoRoot "statistics_light.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
  $iconPath = $null
}

Write-Host "Creating/updating Startup shortcut..." -ForegroundColor Cyan
New-OrUpdate-Shortcut `
  -ShortcutPath $shortcutPath `
  -TargetPath $exePath `
  -WorkingDirectory (Split-Path -Parent $exePath) `
  -IconLocation $iconPath

Write-Host "Done." -ForegroundColor Green
Write-Host ("Startup shortcut: " + $shortcutPath)
