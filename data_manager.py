import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path


class DataManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._lock = threading.Lock()

    def _month_dir(self, date: datetime) -> Path:
        return self.base_dir / date.strftime("%Y%m")

    def _file_path(self, date: datetime, suffix: str) -> Path:
        return self._month_dir(date) / f"{date.strftime('%Y%m%d')}{suffix}"

    # ---- File / Folder management ----

    def ensure_day_files(self, date: datetime) -> None:
        month_dir = self._month_dir(date)
        month_dir.mkdir(exist_ok=True)
        ds = date.strftime("%Y%m%d")
        for name, default in (
            (f"{ds}.log", ""),
            (f"{ds}.app.json", "{}"),
            (f"{ds}.idle.json", "[]"),
            (f"{ds}.report.json", ""),
        ):
            p = month_dir / name
            if not p.exists():
                p.write_text(default, encoding="utf-8")

    # ---- Log ----

    def write_log(self, message: str, date: datetime | None = None, extra: str | None = None,
                  timestamp: datetime | None = None) -> None:
        if date is None:
            date = datetime.now()
        with self._lock:
            path = self._file_path(date, ".log")
            ts_dt = timestamp if timestamp is not None else datetime.now()
            ts = ts_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
                if extra:
                    f.write(extra if extra.endswith("\n") else extra + "\n")

    def read_log(self, date: datetime) -> list[str]:
        with self._lock:
            path = self._file_path(date, ".log")
            if not path.exists():
                return []
            return path.read_text(encoding="utf-8").splitlines()

    # ---- App Data ----

    def read_app_data(self, date: datetime) -> dict:
        with self._lock:
            return self._read_json(self._file_path(date, ".app.json"), {})

    def write_app_data(self, date: datetime, data: dict) -> None:
        with self._lock:
            self._write_json(self._file_path(date, ".app.json"), data)

    def patch_unclosed_entries(self, date: datetime, ended_ts: str) -> None:
        """Fill in `ended` for any app entries that are missing it (e.g. after crash)."""
        app_data = self.read_app_data(date)
        patched = False
        for info in app_data.values():
            for entries in info.get("titles", {}).values():
                for entry in entries:
                    if "started" in entry and "ended" not in entry:
                        entry["ended"] = ended_ts
                        patched = True
        if patched:
            self.write_app_data(date, app_data)

    # ---- Idle Data ----

    def read_idle_data(self, date: datetime) -> list:
        with self._lock:
            return self._read_json(self._file_path(date, ".idle.json"), [])

    def write_idle_data(self, date: datetime, data: list) -> None:
        with self._lock:
            self._write_json(self._file_path(date, ".idle.json"), data)

    # ---- Available Dates ----

    def get_available_dates(self) -> list[str]:
        dates: list[str] = []
        if not self.base_dir.exists():
            return dates
        for entry in self.base_dir.iterdir():
            if entry.is_dir() and re.match(r"^\d{6}$", entry.name):
                for f in entry.iterdir():
                    if f.name.endswith(".app.json"):
                        ds = f.stem.removesuffix(".app")
                        if re.match(r"^\d{8}$", ds):
                            dates.append(ds)
        dates.sort(reverse=True)
        return dates

    # ---- Report ----

    def generate_report(self, date: datetime) -> dict:
        app_data = self.read_app_data(date)
        idle_data = self.read_idle_data(date)

        apps_summary: dict = {}
        first_time: str | None = None
        last_time: str | None = None

        for process, info in app_data.items():
            titles_summary: dict[str, int] = {}
            process_total = 0.0
            for title, entries in info.get("titles", {}).items():
                title_total = 0.0
                for entry in entries:
                    started = entry.get("started")
                    ended = entry.get("ended")
                    if started and ended:
                        diff = self._time_diff(started, ended)
                        if diff > 0:
                            title_total += diff
                    if started:
                        if first_time is None or started < first_time:
                            first_time = started
                        if last_time is None or started > last_time:
                            last_time = started
                    if ended:
                        if last_time is None or ended > last_time:
                            last_time = ended
                titles_summary[title] = round(title_total)
                process_total += title_total
            if process_total > 0:
                apps_summary[process] = {
                    "total": round(process_total),
                    "titles": titles_summary,
                }

        sessions = self._parse_sessions(date)
        if not sessions and first_time and last_time:
            sessions = [[first_time, last_time]]

        clipped = self._idle_seconds_in_sessions(idle_data, sessions)
        if clipped is not None:
            idle_seconds = clipped
        else:
            idle_seconds = 0.0
            for entry in idle_data:
                s, e = entry.get("start"), entry.get("end")
                if s and e:
                    diff = self._time_diff(s, e)
                    if diff > 0:
                        idle_seconds += diff

        report = {
            "sessions": sessions,
            "idle_seconds": round(idle_seconds),
            "apps": apps_summary,
        }

        if date.date() != datetime.now().date():
            with self._lock:
                self._write_json(self._file_path(date, ".report.json"), report)

        return report

    def get_report(self, date_str: str) -> dict:
        empty: dict = {"sessions": [], "idle_seconds": 0, "apps": {}}
        try:
            date = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            return empty

        if date.date() == datetime.now().date():
            return self.generate_report(date)

        with self._lock:
            path = self._file_path(date, ".report.json")
            if path.exists():
                data = self._read_json(path, None)
                if data and isinstance(data, dict) and data.get("sessions") is not None:
                    return data

        if self._file_path(date, ".app.json").exists():
            return self.generate_report(date)

        return empty

    # ---- Internal helpers ----

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default if default is not None else {}
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return default if default is not None else {}
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return default if default is not None else {}

    def _write_json(self, path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))

    @staticmethod
    def _time_diff(start_str: str, end_str: str) -> float:
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        try:
            return (datetime.strptime(end_str, fmt) - datetime.strptime(start_str, fmt)).total_seconds()
        except ValueError:
            try:
                fmt2 = "%Y-%m-%d %H:%M:%S"
                return (datetime.strptime(end_str, fmt2) - datetime.strptime(start_str, fmt2)).total_seconds()
            except ValueError:
                return 0.0

    @staticmethod
    def _parse_dt_value(v: str | int | float) -> datetime | None:
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(v)
            except (OSError, ValueError, OverflowError):
                return None
        if not isinstance(v, str):
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(v.replace(" ", "T"))
        except ValueError:
            return None

    @staticmethod
    def _merge_dt_ranges(ranges: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
        valid = [(a, b) for a, b in ranges if b > a]
        if not valid:
            return []
        valid.sort(key=lambda x: x[0])
        out: list[tuple[datetime, datetime]] = [valid[0]]
        for a, b in valid[1:]:
            la, lb = out[-1]
            if a <= lb:
                out[-1] = (la, max(lb, b))
            else:
                out.append((a, b))
        return out

    @staticmethod
    def _overlap_ranges_seconds(
        a_list: list[tuple[datetime, datetime]],
        b_list: list[tuple[datetime, datetime]],
    ) -> float:
        total = 0.0
        for ia, ib in a_list:
            for sa, sb in b_list:
                start = max(ia, sa)
                end = min(ib, sb)
                if end > start:
                    total += (end - start).total_seconds()
        return total

    def _sessions_to_ranges(self, sessions: list) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        for pair in sessions:
            if not pair or len(pair) < 2:
                continue
            da = self._parse_dt_value(pair[0])
            db = self._parse_dt_value(pair[1])
            if da and db and db > da:
                ranges.append((da, db))
        return ranges

    def _idle_entries_to_ranges(self, idle_data: list) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        for entry in idle_data:
            s, e = entry.get("start"), entry.get("end")
            if not s or not e:
                continue
            ds = self._parse_dt_value(s)
            de = self._parse_dt_value(e)
            if ds and de and de > ds:
                ranges.append((ds, de))
        return ranges

    def _idle_seconds_in_sessions(self, idle_data: list, sessions: list) -> float | None:
        sess = self._merge_dt_ranges(self._sessions_to_ranges(sessions))
        if not sess:
            return None
        idle_merged = self._merge_dt_ranges(self._idle_entries_to_ranges(idle_data))
        if not idle_merged:
            return 0.0
        return self._overlap_ranges_seconds(idle_merged, sess)

    def _parse_sessions(self, date: datetime) -> list:
        log_lines = self.read_log(date)
        sessions: list[list[str]] = []
        current_start: str | None = None

        start_events = {"应用启动", "用户登录", "用户解锁", "系统开机", "系统唤醒"}
        end_events = {"应用退出", "进程终止", "用户登出", "用户锁屏", "系统休眠", "系统关机"}

        for line in log_lines:
            m = re.match(r"\[(.+?)\]\s+(.+)", line.strip())
            if not m:
                continue
            ts, event = m.groups()
            if event in start_events:
                if current_start is None:
                    current_start = ts
            elif event in end_events:
                if current_start is not None:
                    sessions.append([current_start, ts])
                    current_start = None

        if current_start is not None:
            now = datetime.now()
            if date.date() == now.date():
                sessions.append([current_start, now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]])
            else:
                sessions.append([current_start, date.strftime("%Y-%m-%d") + " 23:59:59.999"])

        return sessions
