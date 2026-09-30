"""Windows 低级键鼠钩子（WH_KEYBOARD_LL / WH_MOUSE_LL），纯 ctypes 实现。

设计要点：
- 钩子安装在自己线程并自带消息泵（低级钩子要求安装线程泵消息）。
- 回调里只做最轻量的解析与计数，绝不阻塞，否则系统会静默摘掉钩子。
- 看门狗线程定期让钩子线程重装钩子（只有新钩子成功才替换旧的），
  避免长时间运行后钩子因超时被系统移除而"静默失效"。
- 钩子始终 CallNextHookEx 透传，不改写任何输入。
"""

from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from ctypes import wintypes

from . import keymap as km

# 设置环境变量 KMM_HOOK_LOG 可把钩子生命周期/异常写入日志文件（排查用）
_DEBUG_LOG = os.environ.get("KMM_HOOK_LOG")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

# 单次按住时长的上限：超过就认为漏掉了抬键事件，不参与统计（避免算出几小时）
MAX_HOLD_SECONDS = 1800.0

# 核对"是否真的还按着"的间隔（秒）
SWEEP_INTERVAL = 0.5

_BTN_DOWN = {
    WM_LBUTTONDOWN: km.MOUSE_LEFT,
    WM_RBUTTONDOWN: km.MOUSE_RIGHT,
    WM_MBUTTONDOWN: km.MOUSE_MIDDLE,
}
_BTN_UP = {
    WM_LBUTTONUP: km.MOUSE_LEFT,
    WM_RBUTTONUP: km.MOUSE_RIGHT,
    WM_MBUTTONUP: km.MOUSE_MIDDLE,
}

# 鼠标按键对应的虚拟键（用 GetAsyncKeyState 核对"物理上是否还按着"）
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
VK_XBUTTON1, VK_XBUTTON2 = 0x05, 0x06
_BTN_VK = {
    WM_LBUTTONDOWN: VK_LBUTTON,
    WM_RBUTTONDOWN: VK_RBUTTON,
    WM_MBUTTONDOWN: VK_MBUTTON,
}

WM_APP = 0x8000
WM_REINSTALL = WM_APP + 1
WM_STOP = WM_APP + 2

LLMHF_INJECTED = 0x01


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
)
TIMERPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, wintypes.DWORD
)

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t,
]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetAsyncKeyState.restype = ctypes.c_ushort
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      ctypes.c_size_t, ctypes.c_ssize_t]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class HookEngine:
    """安装全局键鼠钩子，把事件回调给 on_key / on_click / on_move / on_hold。

    - on_key(key_id)            键盘按下（含长按重复）
    - on_click(key_id)          鼠标按键按下 / 滚轮一格
    - on_move(distance_px)      鼠标移动的像素距离（欧氏）
    - on_hold(key_id, ms)       一次"按住不放"的时长（键盘按键、鼠标左右中侧键；
                                滚轮没有按住语义，不产生）。自动重复的 KEYDOWN
                                不会重算起点，只有真正的第一次按下才开始计时。
    """

    def __init__(self, on_key, on_click, on_move, on_error=None,
                 heal_seconds: float = 15.0, on_hold=None):
        self._on_key = on_key
        self._on_click = on_click
        self._on_move = on_move
        self._on_hold = on_hold
        self._on_error = on_error
        self._heal_seconds = heal_seconds

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._running = False

        self._kbd_hook: int | None = None
        self._mouse_hook: int | None = None
        self._last_pt: tuple[int, int] | None = None
        # key_id -> 本次按住的起始时刻（time.monotonic()），抬键时结算
        self._held: dict[str, float] = {}
        # key_id -> 虚拟键号，用来核对"物理上是否还按着"（抬键事件丢失时兜底）
        self._held_vk: dict[str, int] = {}

        self.error: str | None = None
        self.reinstalls = 0
        self.key_events = 0
        self.mouse_events = 0
        self.move_events = 0
        self.hold_events = 0
        self.paused = False

        # 保持引用，防止回调被 GC
        self._kbd_proc = HOOKPROC(self._keyboard_proc)
        self._mouse_proc = HOOKPROC(self._mouse_proc)
        self._hmod = kernel32.GetModuleHandleW(None)

    def _dbg(self, msg: str) -> None:
        if not _DEBUG_LOG:
            return
        try:
            with open(_DEBUG_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{time.time():.3f} [{threading.current_thread().name}] {msg}\n")
        except Exception:
            pass

    # ------------------------------------------------------------ 生命周期
    @property
    def installed(self) -> bool:
        return bool(self._kbd_hook and self._mouse_hook)

    def start(self, timeout: float = 5.0) -> bool:
        if self._running:
            return True
        self._stopped.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="km-hooks", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout)
        if not self.installed and self.error is None:
            self.error = "钩子安装超时"
        threading.Thread(target=self._watchdog, name="km-hooks-watchdog",
                         daemon=True).start()
        return self.installed

    def stop(self, timeout: float = 3.0) -> None:
        self._stopped.set()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_STOP, 0, 0)
        if self._thread:
            self._thread.join(timeout)
        self._running = False
        self._held.clear()
        self._held_vk.clear()

    # ------------------------------------------------------------ 钩子线程
    def _thread_main(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._running = True
        self._install()
        self._ready.set()

        msg = wintypes.MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            if msg.message == WM_REINSTALL:
                self._install()
                continue
            if msg.message == WM_STOP:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._uninstall()
        self._running = False

    def _install(self) -> None:
        kbd = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kbd_proc, self._hmod, 0)
        mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, self._hmod, 0)
        if not kbd or not mouse:
            err = ctypes.get_last_error()
            self.error = f"SetWindowsHookEx 失败 (WinError {err})"
            if self._on_error:
                self._on_error(self.error)
            if kbd:
                user32.UnhookWindowsHookEx(kbd)
            if mouse:
                user32.UnhookWindowsHookEx(mouse)
            return
        if self._kbd_hook:
            user32.UnhookWindowsHookEx(self._kbd_hook)
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
        self._kbd_hook, self._mouse_hook = kbd, mouse
        self.error = None
        self._last_pt = None
        self.reinstalls += 1
        self._dbg(f"install ok kbd={kbd} mouse={mouse} tid={self._thread_id}")

    def _uninstall(self) -> None:
        for h in (self._kbd_hook, self._mouse_hook):
            if h:
                user32.UnhookWindowsHookEx(h)
        self._kbd_hook = self._mouse_hook = None

    def _watchdog(self) -> None:
        last_heal = time.time()
        last_beat = time.time()
        while not self._stopped.wait(SWEEP_INTERVAL):
            # 每 0.5s 核对一次"还按着的键是不是真的还按着"（抬键事件丢失时兜底）
            self._sweep_held()
            if time.time() - last_beat >= 3.0:
                last_beat = time.time()
                self._dbg(
                    f"heartbeat key={self.key_events} mouse={self.mouse_events} "
                    f"move={self.move_events} installed={self.installed} "
                    f"paused={self.paused} running={self._running}"
                )
            if time.time() - last_heal < self._heal_seconds:
                continue
            last_heal = time.time()
            if not self._thread_id:
                return
            if not user32.PostThreadMessageW(self._thread_id, WM_REINSTALL, 0, 0):
                return

    def _sweep_held(self) -> None:
        """把"其实早就不按了、但没收到抬键"的键结算掉。

        抬键事件丢失的原因很实际：切窗口、全屏游戏抢焦点、钩子重装的一瞬间。
        如果不兜底，这个键会永远留在 _held 里 —— 于是它**之后再也不会计数**
        （每次按下都被当成自动重复），按住时长也永远结算不了。
        """
        if not self._held_vk:
            return
        for key_id, vk in list(self._held_vk.items()):
            try:
                if not (user32.GetAsyncKeyState(vk) & 0x8000):
                    self._hold_end(key_id)
            except Exception:
                pass

    # ------------------------------------------------------------ 回调
    def _keyboard_proc(self, code, wparam, lparam):
        if code == HC_ACTION:
            try:
                down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                up = wparam in (WM_KEYUP, WM_SYSKEYUP)
                if down or up:
                    st = ctypes.cast(
                        ctypes.c_void_p(lparam), ctypes.POINTER(KBDLLHOOKSTRUCT)
                    ).contents
                    key_id = km.resolve_key(st.vkCode, st.scanCode, st.flags)
                    if down:
                        # 关键：只有"真正的一次按下"才计数。
                        # 按住不放时 Windows 会以约 30 次/秒合成重复 KEYDOWN
                        # （按键重复），低级钩子照样收得到；如果每个都算一次，
                        # 按住 10 秒就会变成 286 次。重复流只用来维持计时。
                        fresh = self._hold_begin(key_id, st.vkCode)
                        if fresh and not self.paused:
                            self.key_events += 1
                            if _DEBUG_LOG and self.key_events <= 10:
                                self._dbg(f"key vk={st.vkCode:#x} scan={st.scanCode:#x} "
                                          f"flags={st.flags:#x}")
                            self._on_key(key_id)
                    else:
                        # 抬键即使处于暂停也要处理，否则 _held 会留下永不结算的条目
                        self._hold_end(key_id)
            except Exception as exc:
                self._dbg(f"key callback error: {exc!r}")
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _mouse_proc(self, code, wparam, lparam):
        if code == HC_ACTION and not self.paused:
            try:
                st = None
                if wparam == WM_MOUSEMOVE:
                    st = ctypes.cast(
                        ctypes.c_void_p(lparam), ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    pt = (st.pt.x, st.pt.y)
                    last = self._last_pt
                    self._last_pt = pt
                    if last is not None:
                        dx = pt[0] - last[0]
                        dy = pt[1] - last[1]
                        if dx or dy:
                            self.move_events += 1
                            self._on_move(math.hypot(dx, dy))
                elif wparam in _BTN_DOWN:
                    kid = _BTN_DOWN[wparam]
                    self._click(kid)
                    self._hold_begin(kid, _BTN_VK[wparam])
                elif wparam in _BTN_UP:
                    self._hold_end(_BTN_UP[wparam])
                elif wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                    st = ctypes.cast(
                        ctypes.c_void_p(lparam), ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    hi = (st.mouseData >> 16) & 0xFFFF
                    kid = km.MOUSE_X1 if hi == 1 else km.MOUSE_X2
                    if wparam == WM_XBUTTONDOWN:
                        self._click(kid)
                        self._hold_begin(kid, VK_XBUTTON1 if hi == 1 else VK_XBUTTON2)
                    else:
                        self._hold_end(kid)
                elif wparam == WM_MOUSEWHEEL:
                    st = ctypes.cast(
                        ctypes.c_void_p(lparam), ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    delta = ctypes.c_short((st.mouseData >> 16) & 0xFFFF).value
                    steps = max(1, abs(delta) // 120)
                    for _ in range(steps):
                        self._click(km.WHEEL_UP if delta > 0 else km.WHEEL_DOWN)
                elif wparam == WM_MOUSEHWHEEL:
                    st = ctypes.cast(
                        ctypes.c_void_p(lparam), ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    delta = ctypes.c_short((st.mouseData >> 16) & 0xFFFF).value
                    steps = max(1, abs(delta) // 120)
                    for _ in range(steps):
                        self._click(km.WHEEL_RIGHT if delta > 0 else km.WHEEL_LEFT)
            except Exception as exc:
                self._dbg(f"mouse callback error: {exc!r}")
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _click(self, key_id: str) -> None:
        self.mouse_events += 1
        self._on_click(key_id)

    # ------------------------------------------------------------ 按住时长
    def _hold_begin(self, key_id: str, vk: int) -> bool:
        """记录按住起点；返回 True 表示这是"真正的一次按下"（不是自动重复）。

        长按自动重复会反复发 KEYDOWN，只有第一下算新的一次按下。
        """
        now = time.monotonic()
        prev = self._held.get(key_id)
        # 旧起点若已超过上限，说明抬键事件丢了：重新起算，别把一次卡住的按键
        # 记成几小时（也让它能重新计数）。
        if prev is not None and now - prev <= MAX_HOLD_SECONDS:
            return False
        self._held[key_id] = now
        self._held_vk[key_id] = int(vk)
        return True

    def _hold_end(self, key_id: str) -> None:
        started = self._held.pop(key_id, None)
        self._held_vk.pop(key_id, None)
        if started is None or self._on_hold is None or self.paused:
            return
        ms = int((time.monotonic() - started) * 1000.0)
        if 0 < ms <= MAX_HOLD_SECONDS * 1000.0:
            self.hold_events += 1
            self._on_hold(key_id, ms)


def send_input_demo(keys=("A",), clicks=1, moves=1) -> bool:
    """仅供自测：用 SendInput 合成输入。真实输入同样会触发低级钩子。"""
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", PUL)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

    KEYEVENTF_KEYUP = 0x0002
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004

    seq = []
    for name in keys:
        vk = ord(name) if len(name) == 1 and not name.isdigit() else int(name)
        seq.append(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, None))))
        seq.append(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None))))
    for _ in range(clicks):
        seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))))
        seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))))
    for i in range(moves):
        seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(3 + i % 3, 2, 0, MOUSEEVENTF_MOVE, 0, None))))

    n = len(seq)
    arr = (INPUT * n)(*seq)
    sent = user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
    return sent == n


def foreground_hint() -> None:
    """自测时把前台窗口切到指定标题（避免合成输入打到用户其他窗口）。"""
    hwnd = user32.FindWindowW(None, "键鼠使用统计")
    if hwnd:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
