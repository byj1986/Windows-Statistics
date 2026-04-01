import json
import re
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import pystray
from PIL import Image

from data_manager import DataManager


class TrayIcon:
    def __init__(self, config: dict, config_path: Path, icon_path: Path, on_exit, dm: DataManager):
        self.config = config
        self.config_path = config_path
        self.icon_path = icon_path
        self.on_exit = on_exit
        self.dm = dm
        self.icon: pystray.Icon | None = None

    def run(self) -> None:
        image = Image.open(self.icon_path)

        menu = pystray.Menu(
            pystray.MenuItem("今天", self._open_daily),
            pystray.MenuItem("过去7天", self._open_weekly),
            pystray.MenuItem(
                "选项",
                pystray.Menu(
                    pystray.MenuItem(
                        "当日用户首次登陆",
                        self._set_startup("userFirstLogin"),
                        checked=lambda item: self.config.get("startup") == "userFirstLogin",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "当日开机",
                        self._set_startup("powerOn"),
                        checked=lambda item: self.config.get("startup") == "powerOn",
                        radio=True,
                    ),
                ),
            ),
            pystray.MenuItem("退出", self._exit),
        )

        self.icon = pystray.Icon("WindowsStatistics", image, "Windows Statistics", menu)
        self.icon.run()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()

    def _open_daily(self) -> None:
        today = datetime.now()
        if self._is_workday(today) and self.icon:
            start = self._get_start_time(today)
            if start:
                end = start + timedelta(hours=9)
                work_end = start.replace(hour=18, minute=0, second=0, microsecond=0)
                if end < work_end:
                    end = work_end
                now = datetime.now()
                secs = int((end - now).total_seconds())
                if secs <= 0:
                    remaining_hm = "0:00"
                else:
                    remaining_hm = f"{secs // 3600}:{(secs % 3600) // 60:02d}"
                msg = (f"今日开始时间：{start.strftime('%H:%M')}\n"
                       f"今日下班时间：{end.strftime('%H:%M')}\n"
                       f"剩余时间：{remaining_hm}")
                self.icon.notify(msg, "Windows Statistics")
        webbrowser.open("http://localhost:8000/daily.html")

    @staticmethod
    def _is_workday(date: datetime) -> bool:
        return date.weekday() < 5

    def _get_start_time(self, date: datetime) -> datetime | None:
        lines = self.dm.read_log(date)
        startup = self.config.get("startup", "userFirstLogin")
        if startup == "userFirstLogin":
            primary = {"用户登录", "用户解锁"}
            secondary = {"应用启动"}
        else:
            primary = {"应用启动", "系统唤醒"}
            secondary = set()
        first_primary = first_secondary = None
        for line in lines:
            m = re.match(r"\[(.+?)\]\s+(.+)", line.strip())
            if not m:
                continue
            ts, event = m.groups()
            try:
                t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                try:
                    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
            if event in primary and first_primary is None:
                first_primary = t
                break
            if event in secondary and first_secondary is None:
                first_secondary = t
        return first_primary or first_secondary

    def _open_weekly(self) -> None:
        webbrowser.open("http://localhost:8000/weekly.html")

    def _set_startup(self, value: str):
        def callback(icon, item):
            self.config["startup"] = value
            self._save_config()
        return callback

    def _save_config(self) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def _exit(self) -> None:
        if self.icon:
            self.icon.stop()
        self.on_exit()
