import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path

def get_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA not found")
    return (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def get_pythonw_path() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    which = shutil.which("pythonw.exe")
    if which:
        return Path(which)
    raise RuntimeError("pythonw.exe not found")


def create_shortcut(link_path: Path, target_path: Path, arguments: str, working_dir: Path, icon_path: Path | None = None) -> None:
    if link_path.exists():
        link_path.unlink()
    vbs = []
    vbs.append('Set oWS = CreateObject("WScript.Shell")')
    vbs.append(f'sLink = "{str(link_path)}"')
    vbs.append('Set oLnk = oWS.CreateShortcut(sLink)')
    vbs.append(f'oLnk.TargetPath = "{str(target_path)}"')
    vbs.append(f'oLnk.Arguments = {arguments}')
    vbs.append(f'oLnk.WorkingDirectory = "{str(working_dir)}"')
    if icon_path and icon_path.exists():
        vbs.append(f'oLnk.IconLocation = "{str(icon_path)}, 0"')
    vbs.append('oLnk.WindowStyle = 0')
    vbs.append('oLnk.Save')
    vbs_content = "\n".join(vbs)
    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False) as tf:
        tf.write(vbs_content)
        temp_vbs = tf.name
    try:
        subprocess.run(["wscript.exe", temp_vbs], check=True)
    finally:
        try:
            os.remove(temp_vbs)
        except Exception:
            pass
