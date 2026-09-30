"""最小化定位：单独验证"点 ✕ 弹询问框"这条路径，每步都打印进度。

用法: python -X utf8 tools/close_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ui_check  # noqa: E402
from ui_check import build_ui, dlg_texts, pump  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    data_dir = os.path.join(tempfile.mkdtemp(prefix="kmm_close_"), "d")
    os.makedirs(data_dir, exist_ok=True)
    log(f"[1] 构建 UI, 数据目录={data_dir}")
    win, counters, hooks, store = build_ui(data_dir)
    pump(win, 1.5)
    log(f"[2] UI 就绪 viewable={win.root.winfo_viewable()} tray={win.tray}")

    quit_calls: list[str] = []
    win.on_quit = lambda: quit_calls.append("quit")

    log("[3] 调用 on_close_click (托盘不可用)")
    win.on_close_click()
    pump(win, 0.5)
    log(f"[4] 询问框存在={win._close_dlg is not None} 文案={dlg_texts(win)[:120]}")

    log("[5] 选择 cancel")
    win._close_choice("cancel")
    pump(win, 0.4)
    log(f"[6] 询问框={win._close_dlg} quit_calls={quit_calls} viewable={win.root.winfo_viewable()}")

    log("[7] 假装托盘可用, 再次点 ✕")
    win.tray = types.SimpleNamespace(ok=True, error=None, notify=lambda *a, **k: None)
    win.on_close_click()
    pump(win, 0.5)
    log(f"[8] 文案={dlg_texts(win)[:160]}")

    log("[9] 选择 tray")
    win._close_choice("tray")
    pump(win, 0.6)
    log(f"[10] quit_calls={quit_calls} viewable={win.root.winfo_viewable()}")

    log("[11] 重新显示窗口")
    win.toggle_visible(True)
    pump(win, 0.6)
    log(f"[12] viewable={win.root.winfo_viewable()}")

    log("[13] 记住 quit 后再点 ✕")
    win.cfg["close_action"] = "quit"
    win.on_close_click()
    pump(win, 0.4)
    log(f"[14] quit_calls={quit_calls} 询问框={win._close_dlg}")

    log("[15] 恢复询问 + 销毁")
    win.cfg.pop("close_action", None)
    try:
        win.ask_close_again()
    except Exception:
        import traceback

        log("ask_close_again 异常:\n" + traceback.format_exc())
    for name, fn in (("root.destroy", win.root.destroy), ("hooks.stop", hooks.stop),
                     ("counters.stop", counters.stop), ("store.close", store.close)):
        try:
            fn()
        except Exception:
            import traceback

            log(f"{name} 异常:\n" + traceback.format_exc())
    log("[16] 完成 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
