"""诊断：为什么"把真实光标移到某个键上"有时收不到 Tk 的 <Motion>。

用法: python -X utf8 tools/hover_probe.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ui_check  # noqa: E402
from ui_check import build_ui, pump, warp  # noqa: E402

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


def rel(dx: int, dy: int) -> int:
    """相对移动：Windows 只在光标位置真正变化时才发 WM_MOUSEMOVE。"""
    item = _IN(type=0, u=_U(mi=_MOU(dx, dy, 0, 0x0001, 0, None)))
    return user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_IN))


def log(m: str) -> None:
    print(m, flush=True)


def main() -> int:
    data_dir = os.path.join(tempfile.mkdtemp(prefix="kmm_hover_"), "d")
    os.makedirs(data_dir, exist_ok=True)
    win, counters, hooks, store = build_ui(data_dir)
    pump(win, 1.5)

    target = "G"
    box = next(b for b in win._key_boxes if b[4] == target)
    crx, cry = win.canvas.winfo_rootx(), win.canvas.winfo_rooty()
    rx = crx + int((box[0] + box[2]) / 2)
    ry = cry + int((box[1] + box[3]) / 2)
    log(f"窗口={win.root.winfo_geometry()} viewable={win.root.winfo_viewable()} "
        f"topmost={win.root.attributes('-topmost')}")
    log(f"画布 root=({crx},{cry}) 尺寸={win.canvas.winfo_width()}x{win.canvas.winfo_height()}")
    log(f"{target} 方块={tuple(round(v) for v in box[:4])} 目标屏幕坐标=({rx},{ry})")
    log(f"该点 Tk 判定窗口={win.root.winfo_containing(rx, ry)}")

    hits: list[tuple[int, int, str | None]] = []
    win.canvas.bind("<Motion>", lambda e: hits.append((e.x, e.y, win._hit(e.x, e.y))), add="+")
    win.canvas.bind("<Enter>", lambda e: log("   [Enter] canvas"), add="+")
    win.canvas.bind("<Leave>", lambda e: log("   [Leave] canvas"), add="+")

    for i in range(4):
        warp(win.root.winfo_screenwidth() - 3, win.root.winfo_screenheight() - 3)
        pump(win, 0.4)
        log(f"--- 第{i + 1}轮: 光标先停到屏幕角落, hover={win.hover_key}")
        n0 = len(hits)
        warp(rx, ry)
        pump(win, 0.6)
        log(f"    绝对移动到目标: hover={win.hover_key} 光标={win.root.winfo_pointerxy()} "
            f"新Motion={len(hits) - n0} 命中={[h[2] for h in hits[n0:]][:4]}")
        n1 = len(hits)
        rel(3, 2)
        pump(win, 0.4)
        log(f"    再相对抖动(3,2): hover={win.hover_key} 光标={win.root.winfo_pointerxy()} "
            f"新Motion={len(hits) - n1} 命中={[h[2] for h in hits[n1:]][:4]}")
        win._set_hover(None)
        pump(win, 0.2)

    log(f"共收到 {len(hits)} 个 Motion 事件")
    win.root.destroy()
    hooks.stop()
    counters.stop()
    store.close()
    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
