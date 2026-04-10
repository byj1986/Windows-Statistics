@echo off
cd /d "%~dp0.."
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_and_install_startup.ps1"
if errorlevel 1 exit /b 1
echo Done.
