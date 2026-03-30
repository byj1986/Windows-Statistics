import json
import os
import signal
import threading
import traceback
from datetime import datetime
from pathlib import Path

from data_manager import DataManager
from monitor import Monitor, sync_today_events
from server import start_server
from tray import TrayIcon

_SENTINEL = Path(__file__).parent / ".sentinel.json"


def _check_crash(dm: DataManager) -> None:
    """若哨兵文件残留，说明上次进程未正常退出（崩溃/被杀/强制关机），补写日志后删除哨兵。
    休眠/关机等系统事件由 Event Log 同步处理，此处仅记录进程终止。"""
    if not _SENTINEL.exists():
        return
    try:
        data = json.loads(_SENTINEL.read_text(encoding="utf-8"))
        date_str = data.get("date", "")
        date = datetime.strptime(date_str, "%Y%m%d")
        dm.write_log("进程终止", date=date)
    except Exception:
        pass
    _SENTINEL.unlink(missing_ok=True)


def _write_sentinel(date: datetime) -> None:
    _SENTINEL.write_text(
        json.dumps({
            "date": date.strftime("%Y%m%d"),
            "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    base_dir = Path(__file__).parent

    config_path = base_dir / "statistics.configuration.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {"startup": "userFirstLogin", "workingApps": [], "idleExempt": []}

    dm = DataManager(base_dir)
    now = datetime.now()
    dm.ensure_day_files(now)
    _check_crash(dm)
    processed_ids = sync_today_events(dm, now)
    dm.write_log("应用启动")
    _write_sentinel(now)

    _exit_logged = False

    def log_exit(exc: BaseException | None = None) -> None:
        nonlocal _exit_logged
        if _exit_logged:
            return
        _exit_logged = True
        extra: str | None = None
        if exc is not None:
            extra = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        dm.write_log("应用退出", extra=extra)
        _SENTINEL.unlink(missing_ok=True)

    start_server(dm, base_dir, port=8000)

    monitor = Monitor(
        dm, config,
        on_day_change=_write_sentinel,
        on_heartbeat=lambda: _write_sentinel(datetime.now()),
        initial_processed_ids=processed_ids,
    )
    monitor.start()

    icon_path = base_dir / "statistics.ico"

    def on_exit() -> None:
        monitor.stop()
        log_exit()
        os._exit(0)

    def signal_handler(signum, frame) -> None:
        monitor.stop()
        log_exit()
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        log_exit(args.exc_value)

    threading.excepthook = thread_excepthook

    try:
        tray = TrayIcon(config, config_path, icon_path, on_exit, dm)
        tray.run()
    except BaseException as exc:
        if not isinstance(exc, SystemExit):
            log_exit(exc)
        raise


if __name__ == "__main__":
    main()
