import ctypes
import ctypes.wintypes as wintypes
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

import psutil

from data_manager import DataManager

# ---- Win32 Constants ----
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000

WM_QUIT = 0x0012
WM_TIMER = 0x0113
WM_ENDSESSION = 0x0016
WM_QUERYENDSESSION = 0x0011
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007

WTS_SESSION_LOGON = 5
WTS_SESSION_LOGOFF = 6
WTS_SESSION_LOCK = 7
WTS_SESSION_UNLOCK = 8

NOTIFY_FOR_THIS_SESSION = 0
IDLE_THRESHOLD_SEC = 60
TIMER_INTERVAL_MS = 5000
TIMER_ID = 1

# ---- DLL handles ----
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
wtsapi32 = ctypes.windll.wtsapi32

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

wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetTickCount.restype = wintypes.DWORD


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class Monitor:
    def __init__(self, data_manager: DataManager, config: dict,
                 on_day_change: Callable[[datetime], None] | None = None,
                 on_heartbeat: Callable[[], None] | None = None):
        self.dm = data_manager
        self.config = config
        self._on_day_change = on_day_change
        self._on_heartbeat = on_heartbeat
        self._heartbeat_ticks = 0

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

    # ---- Public API ----

    def start(self) -> None:
        self._today = datetime.now()
        self.app_data = self.dm.read_app_data(self._today)
        self.idle_data = self.dm.read_idle_data(self._today)
        self._thread = threading.Thread(target=self._run, daemon=True, name="monitor")
        self._thread.start()
        self._ready.wait(timeout=10)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)
        self._flush_state()

    # ---- Message loop ----

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._create_hidden_window()
        wtsapi32.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION)

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
        if msg == WM_POWERBROADCAST:
            self._on_power(wparam)
            return 1
        if msg == WM_WTSSESSION_CHANGE:
            self._on_session(wparam)
            return 0
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
            wtsapi32.WTSUnRegisterSessionNotification(self._hwnd)
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    # ---- Foreground window tracking ----

    def _on_foreground_event(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if event == EVENT_SYSTEM_FOREGROUND:
            self._capture_foreground()

    def _capture_foreground(self, initial: bool = False) -> None:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return

        try:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        else:
            title = ""

        if not process_name:
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

    # ---- Power events ----

    def _on_power(self, wparam) -> None:
        now = datetime.now()
        ts = _now_str()
        if wparam == PBT_APMSUSPEND:
            self.dm.write_log("系统休眠", now)
            self._end_current_entry(ts)
            self.dm.write_app_data(self._today, self.app_data)
            if self.is_idle:
                self._end_idle(ts)
            self.current_process = None
            self.current_title = None
        elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
            self._check_day_change()
            self.dm.write_log("系统唤醒")
            self._capture_foreground(initial=True)

    # ---- Session events ----

    def _on_session(self, wparam) -> None:
        now = datetime.now()
        ts = _now_str()
        if wparam == WTS_SESSION_LOGON:
            self.dm.write_log("用户登录", now)
            self._capture_foreground(initial=True)
        elif wparam == WTS_SESSION_LOGOFF:
            self.dm.write_log("用户登出", now)
            self._end_current_entry(ts)
            self.dm.write_app_data(self._today, self.app_data)
            if self.is_idle:
                self._end_idle(ts)
            self.current_process = None
            self.current_title = None
        elif wparam == WTS_SESSION_LOCK:
            self.dm.write_log("用户锁屏", now)
            self._end_current_entry(ts)
            self.dm.write_app_data(self._today, self.app_data)
            if self.is_idle:
                self._end_idle(ts)
            self.current_process = None
            self.current_title = None
        elif wparam == WTS_SESSION_UNLOCK:
            self._check_day_change()
            self.dm.write_log("用户解锁", now)
            self._capture_foreground(initial=True)

    # ---- Idle detection ----

    def _on_timer(self) -> None:
        self._heartbeat_ticks += 1
        if self._heartbeat_ticks >= 12:  # 每 60 秒心跳一次（12 × 5s）
            self._heartbeat_ticks = 0
            if self._on_heartbeat:
                self._on_heartbeat()

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
