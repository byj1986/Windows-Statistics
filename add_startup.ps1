# 将 Windows-Statistics 添加到 Windows 启动目录（开机自启）
# 使用 pythonw 静默运行 main.py，不弹出控制台窗口

$shortcutName = "WindowsStatistics.lnk"
$startupDir = [System.Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir $shortcutName

# 防重复：快捷方式已存在则提示并退出
if (Test-Path $shortcutPath) {
    Write-Host "快捷方式已存在，无需重复添加：$shortcutPath" -ForegroundColor Yellow
    exit 0
}

# 定位 pythonw.exe
$pythonw = $null
try {
    $pythonw = (Get-Command pythonw -ErrorAction Stop).Source
} catch {
    # 尝试同目录下的 python.exe 推导 pythonw.exe
    try {
        $python = (Get-Command python -ErrorAction Stop).Source
        $candidate = Join-Path (Split-Path $python) "pythonw.exe"
        if (Test-Path $candidate) {
            $pythonw = $candidate
        }
    } catch {}
}

if (-not $pythonw) {
    Write-Host "错误：未找到 pythonw.exe，请确认已安装 Python 且已加入 PATH。" -ForegroundColor Red
    exit 1
}

# 脚本所在目录即为项目根目录
$projectDir = $PSScriptRoot
$mainPy = Join-Path $projectDir "main.py"
$iconPath = Join-Path $projectDir "statistics.ico"

if (-not (Test-Path $mainPy)) {
    Write-Host "错误：未找到 main.py（$mainPy），请在项目目录下运行此脚本。" -ForegroundColor Red
    exit 1
}

# 创建快捷方式
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath     = $pythonw
$shortcut.Arguments      = "`"$mainPy`""
$shortcut.WorkingDirectory = $projectDir
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.WindowStyle    = 7   # 7 = 最小化启动，不显示窗口
$shortcut.Description    = "Windows Statistics Monitor"
$shortcut.Save()

Write-Host "开机自启快捷方式已添加：$shortcutPath" -ForegroundColor Green
Write-Host "目标：$pythonw `"$mainPy`""
