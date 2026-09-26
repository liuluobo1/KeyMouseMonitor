"""检查正在运行的程序：主窗口 / 托盘隐藏窗口是否存在，并截图存证。

用法: python tools/inspect_running.py [--shot shots/exe_window.png]
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR,
                                 wintypes.LPCWSTR]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]

TITLE = "键鼠使用统计"
TRAY_CLASS = "KeyMouseMonitorTrayWnd"


def class_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def text_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_TK_WINS: list[tuple] = []


def _all_tk_toplevels() -> list[tuple]:
    """列出所有 Tk 顶层窗口 (hwnd, 是否可见, 矩形)。"""
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]

    def cb(hwnd, _lparam):
        if class_of(hwnd) == "TkTopLevel":
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            _TK_WINS.append((hwnd, bool(user32.IsWindowVisible(hwnd)),
                             (r.left, r.top, r.right, r.bottom)))
        return True

    _TK_WINS.clear()
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return list(_TK_WINS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default=os.path.join(ROOT, "shots", "exe_window.png"))
    ap.add_argument("--no-shot", action="store_true")
    args = ap.parse_args()

    fails = []
    main_hwnd = 0
    # 只按标题找会被"同名标题的托盘隐藏窗口"骗到，这里同时校验窗口类名
    for hwnd, visible, rect in _all_tk_toplevels():
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == TITLE and visible:
            main_hwnd = hwnd
            break
    if not main_hwnd:
        h = user32.FindWindowW(None, TITLE)
        if h and class_of(h) == "TkTopLevel":
            main_hwnd = h
    print(f"主窗口: hwnd={main_hwnd} class={class_of(main_hwnd) if main_hwnd else '-'} "
          f"visible={bool(user32.IsWindowVisible(main_hwnd)) if main_hwnd else False}")
    if not main_hwnd:
        fails.append("未找到主窗口")

    tray_hwnd = user32.FindWindowW(TRAY_CLASS, None)
    print(f"托盘隐藏窗口: hwnd={tray_hwnd} class={class_of(tray_hwnd) if tray_hwnd else '-'}")
    if not tray_hwnd:
        fails.append("未找到托盘隐藏窗口（托盘未初始化）")

    if main_hwnd and not args.no_shot:
        from PIL import ImageGrab

        r = wintypes.RECT()
        user32.GetWindowRect(main_hwnd, ctypes.byref(r))
        print(f"窗口矩形: ({r.left},{r.top})-({r.right},{r.bottom}) "
              f"{r.right - r.left}x{r.bottom - r.top}")
        os.makedirs(os.path.dirname(args.shot), exist_ok=True)
        img = ImageGrab.grab(bbox=(max(0, r.left - 10), max(0, r.top - 10),
                                   r.right + 10, r.bottom + 10), all_screens=True)
        img.save(args.shot)
        print("截图:", args.shot, img.size)

    if fails:
        for f in fails:
            print("  [x]", f)
        return 1
    print("[PASS] 主窗口与托盘均正常存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
