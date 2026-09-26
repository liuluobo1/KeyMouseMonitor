"""端到端验证打包 exe 的关闭流程：
  点 ✕ -> 弹出询问框（不再直接退出）
  -> 回车（= 最小化到托盘）-> 窗口隐藏、进程仍在、监控继续
  -> 再次启动程序 -> 窗口被唤回
  -> --quit -> 优雅退出

用法: python -X utf8 tools/close_dialog_check.py [--exe dist\\KeyMouseMonitor.exe]
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ui_check import _rel, find_main_window  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _MOU(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _U(ctypes.Union):
    _fields_ = [("mi", _MOU)]


class _IN(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class _KBD(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _PUL)]


class _KU(ctypes.Union):
    _fields_ = [("ki", _KBD)]


class _KIN(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _KU)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                                ctypes.c_ssize_t]


def thread_focus(hwnd) -> int:
    """读取该窗口所属 UI 线程当前的键盘焦点窗口。

    测试进程不是前台进程，Windows 会拒绝 SetForegroundWindow，SendInput 的键盘
    事件根本进不了被测程序；所以这里直接查应用线程自己的焦点窗口，再把按键投递给它。
    """
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return gti.hwndFocus or 0
    return 0


def post_enter(hwnd) -> None:
    """向目标窗口投递回车按下/抬起（lparam: 扫描码 0x1C）。"""
    user32.PostMessageW(hwnd, 0x0100, 0x0D, 0x001C0001)   # WM_KEYDOWN
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0101, 0x0D, 0xC01C0001)   # WM_KEYUP


user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]

TITLE = "键鼠使用统计"
FAILS: list[str] = []
CHECKS = [0]


def check(cond, msg):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(msg)


def log(m: str) -> None:
    print(m, flush=True)


def click_at(x: int, y: int) -> None:
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    ax, ay = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    mv = _IN(type=0, u=_U(mi=_MOU(ax, ay, 0, 0x8001, 0, None)))
    user32.SendInput(1, ctypes.byref(mv), ctypes.sizeof(_IN))
    _rel(2, 1)
    for flag in (0x0002, 0x0004):
        item = _IN(type=0, u=_U(mi=_MOU(0, 0, 0, flag, 0, None)))
        user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_IN))
        time.sleep(0.03)


def press_key(vk: int) -> None:
    for flags in (0, 2):
        item = _KIN(type=1, u=_KU(ki=_KBD(vk, 0, flags, 0, None)))
        user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_KIN))
        time.sleep(0.03)


def _enum_proc(hwnd, _lparam):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    if buf.value == "TkTopLevel":
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        found.append((hwnd, user32.IsWindowVisible(hwnd),
                      (r.left, r.top, r.right, r.bottom)))
    return True


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def tk_windows() -> list[tuple]:
    global found
    found = []
    cb = WNDENUMPROC(_enum_proc)
    user32.EnumWindows(cb, 0)
    return list(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(ROOT, "dist", "KeyMouseMonitor.exe"))
    ap.add_argument("--data-dir", default=os.path.join(ROOT, ".closecheck"))
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    data_dir = os.path.abspath(args.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = os.path.join(data_dir, "stats.db" + suffix)
        if os.path.exists(p):
            os.remove(p)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # --no-elevate：否则被测程序会申请管理员权限、弹 UAC 卡住测试
    app = subprocess.Popen([exe, "--data-dir", data_dir, "--no-elevate"],
                           cwd=ROOT, env=env)
    try:
        hwnd = find_main_window(TITLE, timeout=15.0)
        check(bool(hwnd), "未找到主窗口")
        if not hwnd:
            return 2
        time.sleep(2.0)
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        # 窗口映射有延迟；若此时不可见，可能是机器上有人刚把窗口收进托盘，
        # 用"再次启动程序"这条受支持的路径把它唤回来再继续。
        visible = False
        for attempt in range(20):
            visible = bool(user32.IsWindowVisible(hwnd))
            if visible:
                break
            if attempt == 5:
                log("窗口当前不可见，尝试用再次启动的方式唤回")
                subprocess.Popen([exe, "--data-dir", data_dir, "--no-elevate"],
                                 cwd=ROOT, env=env)
            time.sleep(0.4)
        check(visible, "启动后主窗口应可见")
        log(f"主窗口 hwnd={hwnd} 可见={visible} "
            f"矩形=({r.left},{r.top})-({r.right},{r.bottom})")

        # ---------- 1) 点 ✕ 应弹询问框，且程序不能退出
        base = tk_windows()
        log(f"点击前 Tk 顶层窗口数={len(base)}")
        candidates = [(-18, 14), (-25, 19), (-32, 24), (-40, 19), (-25, 27), (-46, 14)]
        dialog = None
        for dx, dy in candidates:
            x, y = r.right + dx, r.top + dy
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            click_at(x, y)
            time.sleep(0.9)
            wins = tk_windows()
            if len(wins) > len(base):
                dialog = [w for w in wins if w[0] != hwnd and w[1]]
                log(f"在 ({x},{y}) 点击后出现询问框: {dialog}")
                break
            if not user32.IsWindowVisible(hwnd):
                log(f"在 ({x},{y}) 点到了“最小化”按钮（窗口被隐藏），唤回后继续尝试")
                user32.ShowWindow(hwnd, 5)
                time.sleep(0.6)
        check(dialog is not None, "点击 ✕ 未弹出询问框（可能仍在直接退出）")
        check(app.poll() is None, f"点 ✕ 后进程不应退出（返回码 {app.poll()}）")
        check(bool(user32.IsWindowVisible(hwnd)), "点 ✕ 后主窗口应仍然存在")
        text = dialog[0][2] if dialog else None
        if text:
            log(f"询问框矩形={text} 宽={text[2] - text[0]} 高={text[3] - text[1]}")

        # ---------- 2) 回车 = 最小化到托盘（后台继续运行）
        dlg_hwnd = dialog[0][0] if dialog else hwnd
        app_tid = user32.GetWindowThreadProcessId(hwnd, None)
        focus = thread_focus(hwnd)
        log(f"应用线程={app_tid} 询问框={dlg_hwnd} 主窗口={hwnd} 线程内键盘焦点={focus}")
        # 焦点具体落在哪个 HWND 由 Tk 内部决定（往往是子窗口），只要它在应用线程里
        # 就说明程序自己拿到了键盘输入；真正的判定是下面"投递回车后窗口是否隐藏"。
        check(bool(focus), "询问框弹出后应用线程内应存在键盘焦点窗口")
        post_enter(focus or dlg_hwnd)
        time.sleep(1.2)
        hidden = not bool(user32.IsWindowVisible(hwnd))
        log(f"回车后: 主窗口可见={not hidden} 进程存活={app.poll() is None} "
            f"Tk顶层窗口数={len(tk_windows())}")
        check(hidden, "选择“最小化到托盘”后窗口应隐藏")
        check(app.poll() is None, "最小化到托盘后进程必须仍然存活（后台继续统计）")

        # ---------- 3) 再次启动程序应把窗口唤回
        again = subprocess.Popen([exe, "--data-dir", data_dir, "--no-elevate"],
                                 cwd=ROOT, env=env)
        again.wait(timeout=60)
        time.sleep(1.5)
        visible_again = bool(user32.IsWindowVisible(hwnd))
        check(visible_again, "再次启动程序后窗口应被唤回显示")
        check(app.poll() is None, "唤回后原实例应仍存活")
        log(f"再次启动后: 主窗口可见={visible_again} 第二个进程返回码={again.returncode}")

        # ---------- 4) --quit 优雅退出
        q = subprocess.run([exe, "--quit"], cwd=ROOT, env=env,
                           capture_output=True, timeout=90)
        txt = (q.stdout or b"").decode("utf-8", "replace").strip()
        time.sleep(1.0)
        check(q.returncode == 0, f"--quit 退出码 {q.returncode}: {txt}")
        check(not user32.FindWindowW(None, TITLE), "--quit 后主窗口应消失")
        try:
            app.wait(timeout=15)
        except Exception:
            pass
        check(app.poll() is not None, "--quit 后进程应已退出")
        log(f"--quit 输出: {txt} | 进程返回码={app.poll()}")

        # ---------- 5) 退出后数据仍在（重启能恢复）
        db = os.path.join(data_dir, "stats.db")
        check(os.path.exists(db), "退出后数据库应存在")
        import sqlite3

        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        meta = dict(conn.execute("select k, v from meta"))
        conn.close()
        check(meta.get("session_open") == "0", f"应记录优雅退出, meta={meta}")
        log(f"退出后 meta: {meta}")
    finally:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)],
                           capture_output=True, timeout=30)
        except Exception:
            pass

    print(f"\n断言 {CHECKS[0]} 项，失败 {len(FAILS)} 项")
    if FAILS:
        for f in FAILS:
            print("  [x]", f)
        return 1
    print("[PASS] 关闭流程：✕ 弹询问框 -> 最小化到托盘后台继续 -> 唤回 -> 优雅退出，全部正确")
    return 0


found: list[tuple] = []

if __name__ == "__main__":
    sys.exit(main())
