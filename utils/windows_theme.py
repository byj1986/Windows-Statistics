"""Windows 个性化设置（浅色/深色）查询。"""

import winreg


def is_windows_app_light_theme() -> bool:
    """当前用户「Windows 模式」为浅色时返回 True；读失败时默认 True。"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(value) != 0
    except OSError:
        return True
