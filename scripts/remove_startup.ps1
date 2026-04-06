# 从 Windows 启动目录移除 Windows-Statistics 自启快捷方式

$shortcutName = "WindowsStatistics.lnk"
$startupDir = [System.Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir $shortcutName

if (-not (Test-Path $shortcutPath)) {
    Write-Host "快捷方式不存在，无需删除：$shortcutPath" -ForegroundColor Yellow
    exit 0
}

Remove-Item $shortcutPath -Force
Write-Host "已移除开机自启快捷方式：$shortcutPath" -ForegroundColor Green
