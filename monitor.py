import ctypes
import ctypes.wintypes as wintypes
import queue
import re
import subprocess
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import psutil

from data_manager import DataManager

# ---- Win32 Constants ----
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000

WM_QUIT = 0x0012
WM_TIMER = 0x0113
WM_ENDSESSION = 0x0016
WM_QUERYENDSESSION = 0x0011

IDLE_THRESHOLD_SEC = 60
TIMER_INTERVAL_MS = 1000
TIMER_ID = 1
IDLE_CHECK_TICKS = 5
HEARTBEAT_TICKS = 60
EVTLOG_POLL_INTERVAL_SEC = 10

# ---- Event Log Mapping ----
_SYSTEM_EVENTS: dict[tuple[str, int], str] = {
    ("Microsoft-Windows-Kernel-Power", 42): "系统休眠",
    ("Microsoft-Windows-Power-Troubleshooter", 1): "系统唤醒",
    ("Microsoft-Windows-Winlogon", 7001): "用户登录",
    ("Microsoft-Windows-Winlogon", 7002): "用户登出",
    ("User32", 1074): "系统关机",
    ("EventLog", 6005): "系统开机",
    ("EventLog", 6006): "系统关机",
}

_SECURITY_EVENTS: dict[int, str] = {
    4800: "用户锁屏",
    4801: "用户解锁",
}

_SUSPEND_MESSAGES = frozenset({"系统休眠", "用户登出", "用户锁屏", "系统关机"})
_RESUME_MESSAGES = frozenset({"系统开机", "系统唤醒", "用户登录", "用户解锁"})

_SYSTEM_XPATH_BASE = (
    "*[System[("
    "(Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=42) or "
    "(Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1) or "
    "(Provider[@Name='Microsoft-Windows-Winlogon'] and (EventID=7001 or EventID=7002)) or "
    "(Provider[@Name='User32'] and EventID=1074) or "
    "(Provider[@Name='EventLog'] and (EventID=6005 or EventID=6006))"
    ")"
)

_SECURITY_XPATH_BASE = "*[System[(EventID=4800 or EventID=4801)"

_WINLOGON_OP_CHANNEL = "Microsoft-Windows-Winlogon/Operational"
_WINLOGON_OP_NOTIFY: dict[int, str] = {
    4: "用户锁屏",
    5: "用户解锁",
}
_WINLOGON_OP_XPATH_BASE = "*[System[EventID=811"

_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"

# ---- DLL handles ----
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---- ctypes type aliases ----
LRESULT = ctypes.c_ssize_t
UINT_PTR = ctypes.c_size_t

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)
WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD,
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


# ---- Function prototypes ----
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
    WinEventProcType, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.SetTimer.argtypes = [wintypes.HWND, UINT_PTR, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = UINT_PTR
user32.KillTimer.argtypes = [wintypes.HWND, UINT_PTR]
user32.KillTimer.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetTickCount.restype = wintypes.DWORD


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ---- Event Log helpers ----

def _parse_utc_time(s: str) -> datetime:
    """Parse UTC timestamp from Windows Event Log XML (7-digit fractional + Z)."""
    s = s.rstrip("Z")
    if "." in s:
        base, frac = s.split(".", 1)
        s = f"{base}.{frac[:6]}"
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _build_xpath(base: str, timediff_ms: int) -> str:
    """Append a TimeCreated filter to the open XPath base and close brackets."""
    return f"{base} and TimeCreated[timediff(@SystemTime) <= {timediff_ms}]]]"


def _run_wevtutil(channel: str, xpath_base: str, timediff_ms: int) -> list[dict]:
    """Run wevtutil qe and parse XML output into event dicts."""
    xpath = _build_xpath(xpath_base, timediff_ms)
    cmd = ["wevtutil", "qe", channel, f"/q:{xpath}", "/f:xml", "/rd:false"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        root = ET.fromstring(f"<E>{result.stdout}</E>")
    except ET.ParseError:
        return []

    events: list[dict] = []
    for event_el in root.findall(f"{_EVT_NS}Event"):
        system_el = event_el.find(f"{_EVT_NS}System")
        if system_el is None:
            continue

        provider_el = system_el.find(f"{_EVT_NS}Provider")
        provider = provider_el.get("Name", "") if provider_el is not None else ""

        eid_el = system_el.find(f"{_EVT_NS}EventID")
        event_id = int(eid_el.text) if eid_el is not None and eid_el.text else 0

        time_el = system_el.find(f"{_EVT_NS}TimeCreated")
        time_str = time_el.get("SystemTime", "") if time_el is not None else ""
        if not time_str:
            continue

        rec_el = system_el.find(f"{_EVT_NS}EventRecordID")
        record_id = rec_el.text if rec_el is not None and rec_el.text else ""
        if not record_id:
            continue

        if channel == "Security":
            message = _SECURITY_EVENTS.get(event_id)
        elif channel == _WINLOGON_OP_CHANNEL:
            data_el = event_el.find(f"{_EVT_NS}EventData")
            notify_type = None
            if data_el is not None:
                for d in data_el:
                    if d.get("Name") == "Event" and d.text:
                        try:
                            notify_type = int(d.text)
                        except ValueError:
                            pass
                        break
            message = _WINLOGON_OP_NOTIFY.get(notify_type) if notify_type is not None else None
        else:
            message = _SYSTEM_EVENTS.get((provider, event_id))
        if not message:
            continue

        try:
            time_utc = _parse_utc_time(time_str)
            time_local = time_utc.astimezone().replace(tzinfo=None)
        except (ValueError, OSError):
            continue

        events.append({
            "record_id": f"{channel}:{record_id}",
            "time_utc": time_str,
            "time_local": time_local,
            "message": message,
        })

    return events


def _fetch_events(timediff_ms: int) -> list[dict]:
    """Fetch events from System, Security, and Winlogon Operational logs."""
    events = _run_wevtutil("System", _SYSTEM_XPATH_BASE, timediff_ms)
    try:
        events.extend(_run_wevtutil("Security", _SECURITY_XPATH_BASE, timediff_ms))
    except Exception:
        pass
    try:
        events.extend(_run_wevtutil(_WINLOGON_OP_CHANNEL, _WINLOGON_OP_XPATH_BASE, timediff_ms))
    except Exception:
        pass
    events.sort(key=lambda e: e["time_utc"])

    # Deduplicate events with same message within 10 seconds (e.g. multiple shutdown sources)
    result: list[dict] = []
    seen: dict[str, datetime] = {}
    for evt in events:
        msg = evt["message"]
        ts = evt["time_local"]
        if msg in seen and abs((ts - seen[msg]).total_seconds()) < 10:
            continue
        seen[msg] = ts
        result.append(evt)
    return result


def sync_today_events(dm: DataManager, today: datetime) -> set[str]:
    """Sync today's events from Windows Event Log on startup.

    Queries the System and Security event logs for today's power/session events,
    deduplicates against existing log entries, writes missing events, and returns
    the set of processed EventRecordIDs for the poll thread to skip.
    """
    today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    timediff_ms = int((datetime.now() - today_start).total_seconds() * 1000) + 60_000

    events = _fetch_events(timediff_ms)
    today_date = today.date()
    events = [e for e in events if e["time_local"].date() == today_date]

    existing: set[tuple[str, str]] = set()
    for line in dm.read_log(today):
        m = re.match(r"\[(.+?)\]\s+(.+)", line.strip())
        if m:
            existing.add((m.group(1)[:19], m.group(2)))

    processed_ids: set[str] = set()
    for evt in events:
        processed_ids.add(evt["record_id"])
        ts_sec = evt["time_local"].strftime("%Y-%m-%d %H:%M:%S")
        if (ts_sec, evt["message"]) not in existing:
            dm.write_log(evt["message"], date=evt["time_local"], timestamp=evt["time_local"])

    return processed_ids


class Monitor:
    def __init__(self, data_manager: DataManager, config: dict,
                 on_day_change: Callable[[datetime], None] | None = None,
                 on_heartbeat: Callable[[], None] | None = None,
                 initial_processed_ids: set[str] | None = None):
        self.dm = data_manager
        self.config = config
        self._on_day_change = on_day_change
        self._on_heartbeat = on_heartbeat
        self._heartbeat_ticks = 0
        self._idle_ticks = 0

        self.current_process: str | None = None
        self.current_title: str | None = None
        self.app_data: dict = {}
        self.idle_data: list = []
        self.is_idle: bool = False

        self._today: datetime = datetime.now()
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._hwnd: wintypes.HWND | None = None
        self._hook: wintypes.HANDLE | None = None
        self._ready = threading.Event()

        self._wnd_proc_ptr: WNDPROC | None = None
        self._win_event_ptr: WinEventProcType | None = None

        self._event_queue: queue.Queue = queue.Queue()
        self._processed_ids: set[str] = initial_processed_ids.copy() if initial_processed_ids else set()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

    # ---- Public API ----

    def start(self) -> None:
        self._today = datetime.now()
        self.app_data = self.dm.read_app_data(self._today)
        self.idle_data = self.dm.read_idle_data(self._today)

        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="evtlog-poll",
        )
        self._poll_thread.start()

        self._thread = threading.Thread(target=self._run, daemon=True, name="monitor")
        self._thread.start()
        self._ready.wait(timeout=10)

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)
        self._flush_state()

    # ---- Message loop ----

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._create_hidden_window()

        self._win_event_ptr = WinEventProcType(self._on_foreground_event)
        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
            None, self._win_event_ptr, 0, 0, WINEVENT_OUTOFCONTEXT,
        )

        user32.SetTimer(self._hwnd, TIMER_ID, TIMER_INTERVAL_MS, None)
        self._capture_foreground(initial=True)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._cleanup()

    def _create_hidden_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "StatisticsMonitorHidden"

        self._wnd_proc_ptr = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wnd_proc_ptr
        wc.hInstance = hinstance
        wc.lpszClassName = class_name
        user32.RegisterClassExW(ctypes.byref(wc))

        self._hwnd = user32.CreateWindowExW(
            0, class_name, "StatisticsMonitor", 0,
            0, 0, 0, 0, None, None, hinstance, None,
        )

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER and wparam == TIMER_ID:
            self._on_timer()
            return 0
        if msg == WM_QUERYENDSESSION:
            return 1
        if msg == WM_ENDSESSION:
            if wparam:
                self._on_shutdown()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _cleanup(self) -> None:
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        if self._hwnd:
            user32.KillTimer(self._hwnd, TIMER_ID)
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    # ---- Foreground window tracking ----

    def _on_foreground_event(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if event == EVENT_SYSTEM_FOREGROUND:
            self._capture_foreground()

    def _clear_foreground(self) -> None:
        """Close the current foreground entry when the active window is unidentifiable."""
        if self.current_process is None:
            return
        now = _now_str()
        self._end_current_entry(now)
        self.dm.write_app_data(self._today, self.app_data)
        self.current_process = None
        self.current_title = None

    def _capture_foreground(self, initial: bool = False) -> None:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            self._clear_foreground()
            return

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            self._clear_foreground()
            return

        try:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            self._clear_foreground()
            return

        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        else:
            title = ""

        if not process_name:
            self._clear_foreground()
            return
        if process_name == self.current_process and title == self.current_title:
            return

        now = _now_str()

        if not initial and self.current_process:
            self._end_current_entry(now)

        self.current_process = process_name
        self.current_title = title

        if process_name not in self.app_data:
            self.app_data[process_name] = {"titles": {}}
        titles = self.app_data[process_name]["titles"]
        if title not in titles:
            titles[title] = []
        titles[title].append({"started": now})

        self.dm.write_app_data(self._today, self.app_data)

        if self.is_idle:
            self._end_idle(now)

    def _end_current_entry(self, now: str) -> None:
        if not self.current_process or self.current_title is None:
            return
        proc_data = self.app_data.get(self.current_process)
        if not proc_data:
            return
        entries = proc_data.get("titles", {}).get(self.current_title)
        if entries and "ended" not in entries[-1]:
            entries[-1]["ended"] = now

    # ---- Event Log Polling ----

    def _poll_loop(self) -> None:
        """Poll thread: query event log every second, push new events to queue."""
        last_poll = datetime.now()
        while not self._stop_event.wait(EVTLOG_POLL_INTERVAL_SEC):
            try:
                now = datetime.now()
                gap_ms = int((now - last_poll).total_seconds() * 1000) + 2000
                gap_ms = max(gap_ms, 5000)
                events = _fetch_events(timediff_ms=gap_ms)
                for evt in events:
                    if evt["record_id"] not in self._processed_ids:
                        self._processed_ids.add(evt["record_id"])
                        self._event_queue.put(evt)
                last_poll = now
            except Exception:
                pass

    def _drain_event_queue(self) -> None:
        """Process all queued events (called from timer in message loop thread)."""
        while True:
            try:
                evt = self._event_queue.get_nowait()
            except queue.Empty:
                break
            self._process_event(evt)

    def _process_event(self, evt: dict) -> None:
        """Process a polled event: write log and trigger side effects."""
        message = evt["message"]
        ts = evt["time_local"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        self.dm.write_log(message, date=evt["time_local"], timestamp=evt["time_local"])

        if message in _SUSPEND_MESSAGES:
            self._end_current_entry(ts)
            self.dm.write_app_data(self._today, self.app_data)
            if self.is_idle:
                self._end_idle(ts)
            self.is_idle = True
            self.idle_data.append({"start": ts})
            self.dm.write_idle_data(self._today, self.idle_data)
            self.current_process = None
            self.current_title = None
        elif message in _RESUME_MESSAGES:
            if self.is_idle:
                self._end_idle(ts)
            self._check_day_change()
            self._capture_foreground(initial=True)

    # ---- Timer ----

    def _on_timer(self) -> None:
        self._drain_event_queue()
        self._check_day_change()

        self._heartbeat_ticks += 1
        if self._heartbeat_ticks >= HEARTBEAT_TICKS:
            self._heartbeat_ticks = 0
            if self._on_heartbeat:
                self._on_heartbeat()

        self._idle_ticks += 1
        if self._idle_ticks >= IDLE_CHECK_TICKS:
            self._idle_ticks = 0
            self._check_idle()

    def _check_idle(self) -> None:
        if self.current_process is None:
            return

        exempt = self.config.get("idleExempt", [])
        if self.current_process in exempt:
            if self.is_idle:
                self._end_idle(_now_str())
            return

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return

        tick = kernel32.GetTickCount()
        idle_ms = (tick - lii.dwTime) & 0xFFFFFFFF
        idle_sec = idle_ms / 1000.0

        if idle_sec >= IDLE_THRESHOLD_SEC and not self.is_idle:
            self.is_idle = True
            real_start = datetime.now() - timedelta(seconds=idle_sec)
            self.idle_data.append({"start": real_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]})
            self.dm.write_idle_data(self._today, self.idle_data)
        elif idle_sec < IDLE_THRESHOLD_SEC and self.is_idle:
            self._end_idle(_now_str())

    def _end_idle(self, now: str) -> None:
        if self.idle_data and "end" not in self.idle_data[-1]:
            self.idle_data[-1]["end"] = now
            self.dm.write_idle_data(self._today, self.idle_data)
        self.is_idle = False

    # ---- Shutdown ----

    def _on_shutdown(self) -> None:
        now = datetime.now()
        ts = _now_str()
        self.dm.write_log("系统关机", now)
        self._end_current_entry(ts)
        self.dm.write_app_data(self._today, self.app_data)
        if self.is_idle:
            self._end_idle(ts)

    # ---- Cross-day ----

    def _check_day_change(self) -> None:
        now = datetime.now()
        if now.date() == self._today.date():
            return

        old_ts = self._today.strftime("%Y-%m-%d") + " 23:59:59.999"
        was_idle = self.is_idle
        self._end_current_entry(old_ts)
        if self.is_idle:
            self._end_idle(old_ts)
        self.dm.write_app_data(self._today, self.app_data)
        self.dm.generate_report(self._today)

        self._today = now
        self.dm.ensure_day_files(now)
        self.app_data = {}
        self.idle_data = []
        self.current_process = None
        self.current_title = None
        self._processed_ids.clear()

        if was_idle:
            self.is_idle = True
            new_ts = now.strftime("%Y-%m-%d") + " 00:00:00.000"
            self.idle_data.append({"start": new_ts})
            self.dm.write_idle_data(self._today, self.idle_data)
        else:
            self.is_idle = False

        if self._on_day_change:
            self._on_day_change(self._today)

    # ---- Flush on exit ----

    def _flush_state(self) -> None:
        ts = _now_str()
        self._end_current_entry(ts)
        if self.is_idle:
            self._end_idle(ts)
        self.dm.write_app_data(self._today, self.app_data)
