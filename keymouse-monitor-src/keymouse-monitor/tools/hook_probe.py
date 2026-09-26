"""最小钩子验证：不启动 UI，只验证 WH_KEYBOARD_LL / WH_MOUSE_LL 是否收到合成输入。"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.hooks import HookEngine  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

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


def main() -> int:
    events: list[tuple[str, str]] = []

    def on_key(k):
        events.append(("key", k))

    def on_click(k):
        events.append(("click", k))

    def on_move(d):
        events.append(("move", f"{d:.1f}"))

    eng = HookEngine(on_key, on_click, on_move)
    ok = eng.start()
    print("hooks installed:", ok, "error:", eng.error)
    time.sleep(0.5)

    seq = []
    for vk in (0x41, 0x42):
        seq.append(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, None))))
        seq.append(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, 2, 0, None))))
    seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(5, 5, 0, 0x0001, 0, None))))
    seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(0, 0, 0, 0x0002, 0, None))))
    seq.append(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, None))))
    arr = (INPUT * len(seq))(*seq)
    sent = user32.SendInput(len(seq), ctypes.byref(arr), ctypes.sizeof(INPUT))
    print("SendInput:", sent, "of", len(seq), "last_error:", ctypes.get_last_error())

    time.sleep(1.5)
    eng.stop()
    print("hooks installed after:", eng.installed, "error:", eng.error)
    print("events:", len(events))
    print("key_events:", eng.key_events, "mouse_events:", eng.mouse_events,
          "move_events:", eng.move_events, "reinstalls:", eng.reinstalls)
    from collections import Counter

    print(Counter(events))
    return 0 if events else 1


if __name__ == "__main__":
    sys.exit(main())
