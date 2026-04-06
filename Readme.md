# Windows Statistics

在 Windows 上记录应用使用与空闲时间，托盘图标打开本地网页报表（`daily.html` / `weekly.html`），数据与配置默认写在程序所在目录。

## 环境

- Windows 10/11
- Python 3（建议 3.10+）

安装依赖：

```bash
pip install -r requirements.txt
```

开发时如需打包，另需安装 [PyInstaller](https://pyinstaller.org/)：

```bash
pip install pyinstaller
```

## 从源码运行

在项目根目录执行：

```bash
python main.py
```

浏览器访问 `http://localhost:8000/daily.html` 或 `weekly.html`（由程序内嵌服务提供）。

## 打包为 exe

以下命令的**当前工作目录须为仓库根目录**（与 `main.py`、`daily.html`、各 `.ico` 等同级），否则 PyInstaller 找不到 `--add-data` 与入口脚本。

在项目根执行：

```bash
pyinstaller --noconfirm --clean --onedir --windowed --name "WindowsStatistics" --add-data "daily.html;." --add-data "weekly.html;." --add-data "mock-header-choices.html;." --add-data "echarts.min.js;." --add-data "statistics.configuration.json;." --add-data "statistics_light.ico;." --add-data "statistics_dark.ico;." main.py
```

产物目录：`dist\WindowsStatistics\`，主程序为 `WindowsStatistics.exe`。

**`installer/pyinstaller命令.txt`**：文中先 `cd ..` 表示假定你当前在 `installer` 目录，回到上一级才是仓库根；若你已在根目录，请勿再执行 `cd ..`。

**`installer/WindowsStatistics.spec`**：spec 内路径相对**运行 pyinstaller 时的当前目录**，不是相对 spec 文件位置。请在仓库根执行，例如：

```bash
pyinstaller installer\WindowsStatistics.spec
```

不要在 `installer` 目录内单独运行 `pyinstaller WindowsStatistics.spec`，否则会找不到根目录下的 `main.py` 与资源文件。

## 一键打包并加入当前用户启动项

`installer/build_and_install_startup.ps1` 会根据脚本所在位置自动切换到仓库根再打包；通常通过 **`installer/run_build.cmd`** 调用即可。

1. 在仓库根目录执行与上文相同的 PyInstaller 参数打包；
2. 若成功，在**当前用户**的「启动」文件夹创建或更新快捷方式 `WindowsStatistics.lnk`，指向 `dist\WindowsStatistics\WindowsStatistics.exe`。

在仓库根目录双击运行：

```bat
.\installer\run_build.cmd
```

也可在任意位置执行：`powershell -NoProfile -ExecutionPolicy Bypass -File "<仓库>\installer\build_and_install_startup.ps1"`（将 `<仓库>` 换为你的项目路径）。

启动文件夹路径一般为：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`。

## 其他脚本（源码自启）

- `scripts/add_startup.ps1`：为**源码**方式添加启动快捷方式（使用 `pythonw` 运行 `main.py`），与 exe 打包路径无关。
- `scripts/remove_startup.ps1`：删除启动目录中的 `WindowsStatistics.lnk`。

若已用 `installer/run_build.cmd` 指向 exe，一般无需再用 `scripts/add_startup.ps1`，除非你想改回源码启动。

## 配置

首次运行会在程序目录使用或生成 `statistics.configuration.json`（可在托盘「选项」中调整部分行为）。
