"""端到端验证：启动真实程序 -> 合成键鼠输入 -> 核对数据库落库结果。

用法：
  python tools/e2e.py [--data-dir .e2e] [--keep]

前提：本机会短暂弹出程序窗口（合成输入只会打在该窗口内，不会影响其他程序）。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]

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


INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

TITLE = "键鼠使用统计"


def send(seq: list[INPUT]) -> int:
    n = len(seq)
    arr = (INPUT * n)(*seq)
    return user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))


def key(vk: int, up: bool = False, extended: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return INPUT(type=INPUT_KEYBOARD,
                 u=INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, None)))


def mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE,
                 u=INPUTUNION(mi=MOUSEINPUT(dx, dy, data, flags, 0, None)))


def abs_xy(x: int, y: int) -> tuple[int, int]:
    """屏幕坐标 -> SendInput 绝对坐标（0..65535）。"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))


def find_window(title: str = TITLE, timeout: float = 15.0) -> int:
    """按 "类名=TkTopLevel + 标题" 查找主窗口（托盘隐藏窗口可能同名）。"""
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ui_check

    return ui_check.find_main_window(title, timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, ".e2e"))
    ap.add_argument("--exe", default=None, help="改为测试打包后的 exe")
    ap.add_argument("--keep", action="store_true", help="测试后保留进程与数据")
    args = ap.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    db = os.path.join(data_dir, "stats.db")
    if os.path.exists(db):
        os.remove(db)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if args.exe:
        exe = os.path.abspath(args.exe)
        if not os.path.exists(exe):
            print(f"[FAIL] 找不到 exe: {exe}")
            return 2
        launch = [exe, "--data-dir", data_dir, "--no-tray", "--no-elevate"]
        dump_cmd = [exe, "--dump", "--data-dir", data_dir, "--out"]
    else:
        launch = [sys.executable, "-X", "utf8", os.path.join(ROOT, "main.py"),
                  "--data-dir", data_dir, "--no-tray", "--no-elevate"]
        dump_cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "main.py"),
                    "--dump", "--data-dir", data_dir, "--out"]
    app = subprocess.Popen(launch, cwd=ROOT, env=env)
    fails: list[str] = []
    try:
        hwnd = find_window()
        if not hwnd:
            print("[FAIL] 未找到程序窗口")
            return 2
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        print(f"窗口句柄={hwnd} 位置=({rect.left},{rect.top})-({rect.right},{rect.bottom})")

        user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)

        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2

        # ---- 鼠标移动（窗口内折线，产生确定的距离）
        moves = [(cx - 120 + i * 12, cy - 60 + i * 7) for i in range(20)]
        for x, y in moves:
            ax, ay = abs_xy(x, y)
            send([mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)])

        # ---- 左键 7 次 / 右键 3 次（都落在窗口内部）
        clicks_left, clicks_right, wheel = 7, 3, 2
        for i in range(clicks_left):
            x, y = cx - 100 + i * 5, cy + 40
            ax, ay = abs_xy(x, y)
            send([mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay),
                  mouse(MOUSEEVENTF_LEFTDOWN), mouse(MOUSEEVENTF_LEFTUP)])
        for i in range(clicks_right):
            x, y = cx + 100 + i * 5, cy + 40
            ax, ay = abs_xy(x, y)
            send([mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay),
                  mouse(MOUSEEVENTF_RIGHTDOWN), mouse(MOUSEEVENTF_RIGHTUP)])
        for _ in range(wheel):
            send([mouse(MOUSEEVENTF_WHEEL, 0, 0, 120)])

        # ---- 键盘：A x 9, B x 5, 左 Shift x 2, 小键盘 0 x 4
        expect_keys = {"A": 9, "B": 5, "LShift": 2, "Num0": 4}
        for name, times in expect_keys.items():
            vk = {"A": 0x41, "B": 0x42, "LShift": 0xA0, "Num0": 0x60}[name]
            ext = name == "Num0"
            for _ in range(times):
                send([key(vk, False, ext), key(vk, True, ext)])
                time.sleep(0.01)

        # ---- 长按自动重复：连续发 KEYDOWN 不抬键，只应计 1 次
        # （真实按住不放时 Windows 会以约 30 次/秒合成重复 KEYDOWN，
        #   低级钩子收得到；之前每个都计数会让"按住 10 秒 = 286 次"）
        repeat_vk = 0x43          # C
        send([key(repeat_vk, False, False)])
        for _ in range(6):
            time.sleep(0.05)
            send([key(repeat_vk, False, False)])
        time.sleep(0.3)
        send([key(repeat_vk, True, False)])

        print("已合成输入，等待落库 ...")
        time.sleep(7.0)

        # ---- 用程序自带的只读导出核对
        out = os.path.join(data_dir, "dump.json")
        subprocess.run(dump_cmd + [out], cwd=ROOT, env=env,
                       capture_output=True, timeout=90)
        with open(out, "r", encoding="utf-8") as fh:
            snap = json.load(fh)

        totals = snap["totals"]
        print("数据库累计:", json.dumps(
            {k: v for k, v in sorted(totals.items(), key=lambda kv: -kv[1])},
            ensure_ascii=False))

        for name, times in expect_keys.items():
            got = totals.get(name, 0)
            if got != times:
                fails.append(f"键盘 {name}: 期望 {times} 实际 {got}")
        for name, times in (("MouseLeft", clicks_left), ("MouseRight", clicks_right),
                            ("WheelUp", wheel)):
            got = totals.get(name, 0)
            if got != times:
                fails.append(f"鼠标 {name}: 期望 {times} 实际 {got}")

        # 7 次 KEYDOWN（模拟自动重复）只应算 1 次按下，按住时长应约 0.6 秒
        got_c = totals.get("C", 0)
        if got_c != 1:
            fails.append(f"长按重复流 C: 期望 1 实际 {got_c}（重复没有被合并）")
        held_ms = snap.get("dur_totals_ms", {}).get("C", 0)
        if not (300 <= held_ms <= 1500):
            fails.append(f"长按重复流 C 的按住时长异常: {held_ms}ms（期望约 600ms）")

        moved = snap["move_day"].get(time.strftime("%Y-%m-%d"), 0)
        if moved < 100:
            fails.append(f"鼠标移动距离过小: {moved}")

        if not snap["sessions"]:
            fails.append("没有写入会话记录")

        if fails:
            print("\n[FAIL]")
            for f in fails:
                print("  -", f)
            return 1
        print("\n[PASS] 端到端验证通过：键位/鼠标/滚轮/移动距离 全部正确落库")
        return 0
    finally:
        if not args.keep:
            # PyInstaller 单文件会派生真正的子进程，terminate 父进程杀不干净，
            # 必须整棵进程树一起结束（否则会留下孤儿实例占着单实例锁）
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)],
                               capture_output=True, timeout=30)
            except Exception:
                pass
            app.terminate()
            try:
                app.wait(timeout=10)
            except Exception:
                app.kill()


if __name__ == "__main__":
    sys.exit(main())
