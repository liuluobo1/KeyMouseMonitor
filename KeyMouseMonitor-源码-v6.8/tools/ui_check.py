"""UI 渲染与交互自检（不依赖肉眼）：真实创建窗口，逐项断言布局/热力/悬停/气泡/图表。

用法：python tools/ui_check.py [--demo-dir .uidemo] [--shot shots/ui.png]
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import keymap as km  # noqa: E402
from core import sysutil  # noqa: E402
from core.counters import Counters  # noqa: E402
from core.hooks import HookEngine  # noqa: E402
from core.store import Store, today_str  # noqa: E402
from ui import theme as th  # noqa: E402

FAILS: list[str] = []
CHECKS = [0]

# ---- SendInput 绝对移动（比 SetCursorPos 可靠，会真实产生 WM_MOUSEMOVE）
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _rel(dx: int, dy: int) -> None:
    """相对移动：绝对定位只产生 Enter，不产生 <Motion>，需要一次微小位移来触发。"""
    u = ctypes.WinDLL("user32")
    item = _INPUT(type=0, u=_INPUTUNION(mi=_MOUSEINPUT(dx, dy, 0, 0x0001, 0, None)))
    u.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))


def warp(x: int, y: int, jiggle: bool = True) -> None:
    """把光标移到屏幕坐标 (x, y)；jiggle=True 时再抖一下以确保产生 <Motion>。"""
    u = ctypes.WinDLL("user32")
    u.GetSystemMetrics.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    ax, ay = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    item = _INPUT(type=0, u=_INPUTUNION(mi=_MOUSEINPUT(ax, ay, 0, 0x8001, 0, None)))
    u.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))
    if jiggle:
        _rel(3, 2)


def check(cond, msg):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(msg)


def seed(db_path: str) -> dict:
    """写入有层次的演示数据，方便检验热力图/趋势图/汇总。"""
    if os.path.exists(db_path):
        os.remove(db_path)
    store = Store(db_path)
    hot = {"A": 260, "S": 180, "D": 150, "F": 120, "G": 90, "H": 60, "J": 40,
           "K": 25, "L": 18, "Space": 300, "Enter": 140, "Backspace": 95,
           "LShift": 80, "LCtrl": 55, "E": 210, "R": 130, "T": 110, "W": 200,
           "Q": 70, "MouseLeft": 420, "MouseRight": 65, "MouseMiddle": 12,
           "WheelUp": 180, "WheelDown": 175, "MouseX1": 8, "Up": 33, "F5": 21,
           "1": 44, "2": 66, "Tab": 39, "Esc": 17, "Num0": 26, "Num5": 14}
    for i in range(7):
        day = today_str(-i)
        scale = 1.0 - i * 0.11
        key_rows = {k: max(1, int(v * scale)) for k, v in hot.items() if v * scale >= 1}
        # 按住时长：按"平均每次按住 130ms"造数据，同样逐日递减
        dur_rows = {k: v * 130 for k, v in key_rows.items()}
        px = 4200.0 * scale
        store.flush({day: key_rows}, {day: px}, 0.0, None, {day: dur_rows})
        # move_total 单独累计
        snap = store.load()
        store.set_meta("move_total_px", repr(snap["move_total"] + px))
        store.flush({}, {}, snap["move_total"] + px, None)
    store.close()
    return hot


def build_ui(data_dir: str):
    from ui.app import MainWindow

    db_path = os.path.join(data_dir, "stats.db")
    store = Store(db_path)
    counters = Counters(store)
    hooks = HookEngine(counters.on_key, counters.on_click, counters.on_move,
                       on_hold=counters.on_hold)
    hooks.start()
    counters.start()
    win = MainWindow({
        "counters": counters, "hooks": hooks, "tray": None,
        "data_dir": data_dir, "db_path": db_path, "note": None,
        "on_quit": lambda: None,
    })
    return win, counters, hooks, store


def pump(win, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        win.root.update()
        time.sleep(0.02)


def window_class(hwnd) -> str:
    u = ctypes.WinDLL("user32")
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    buf = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, buf, 64)
    return buf.value


_MAIN_WIN: list[int] = []
_MAIN_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_main_window(title: str = "键鼠使用统计", timeout: float = 0.0) -> int:
    """按 "类名=TkTopLevel + 标题" 查找主窗口。

    只按标题找不安全：托盘隐藏窗口曾经也用同一个标题，FindWindow 可能返回那个
    永远不可见的窗口。这里同时校验类名，并且只认 Tk 的顶层窗口。
    """
    u = ctypes.WinDLL("user32")
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.EnumWindows.argtypes = [_MAIN_PROC, wintypes.LPARAM]

    def cb(hwnd, _lparam):
        if window_class(hwnd) != "TkTopLevel":
            return True
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            _MAIN_WIN.append(hwnd)
            return False
        return True

    end = time.time() + timeout
    while True:
        _MAIN_WIN.clear()
        u.EnumWindows(_MAIN_PROC(cb), 0)
        if _MAIN_WIN:
            return _MAIN_WIN[0]
        if time.time() >= end:
            return 0
        time.sleep(0.3)


def dlg_texts(win) -> str:
    """收集关闭询问框里所有控件的文案，用于断言按钮是否齐全。"""
    out: list[str] = []

    def walk(w):
        for ch in w.winfo_children():
            try:
                t = ch.cget("text")
                if t:
                    out.append(str(t))
            except Exception:
                pass
            walk(ch)

    if win._close_dlg is not None:
        walk(win._close_dlg)
    return " | ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-dir", default=os.path.join(ROOT, ".uidemo"))
    ap.add_argument("--shot", default=os.path.join(ROOT, "shots", "ui_hover.png"))
    args = ap.parse_args()

    sysutil.enable_dpi_awareness()
    data_dir = os.path.abspath(args.demo_dir)
    os.makedirs(data_dir, exist_ok=True)
    hot = seed(os.path.join(data_dir, "stats.db"))

    win, counters, hooks, store = build_ui(data_dir)
    pump(win, 2.0)

    # ---------- 0. 关闭询问框（✕ 不再直接退出）
    quit_calls: list[str] = []
    win.on_quit = lambda: quit_calls.append("quit")

    win.on_close_click()          # 本用例未经 main 装配，托盘不可用
    pump(win, 0.4)
    check(win._close_dlg is not None and win._close_dlg.winfo_exists(),
          "点 ✕ 未弹出询问框")
    joined = dlg_texts(win)
    check("直接退出程序" in joined, f"询问框缺少“直接退出”：{joined}")
    check("取消" in joined, "询问框缺少“取消”")
    check("不再询问" in joined, "询问框缺少“记住选择”")
    check("最小化到托盘" not in joined, "托盘不可用时不应提供最小化到托盘")

    win._close_choice("cancel")
    pump(win, 0.3)
    check(win._close_dlg is None, "取消后询问框应关闭")
    check(not quit_calls and win.root.winfo_viewable(), "取消后不应退出、窗口仍在")
    check("close_action" not in win.cfg, "取消不应记住选择")

    # 记住"直接退出"后，再次点 ✕ 不再询问，直接退出
    win.cfg["close_action"] = "quit"
    win.on_close_click()
    pump(win, 0.3)
    check(win._close_dlg is None, "已记住选择时不应再弹询问框")
    check(quit_calls == ["quit"], f"记住“直接退出”后应立即退出，实际 {quit_calls}")
    win.cfg.pop("close_action", None)
    quit_calls.clear()
    win.ask_close_again()
    pump(win, 0.2)
    check("close_action" not in win.cfg, "恢复询问应清除已记住的选择")

    # 托盘可用时：提供"最小化到托盘"，选择它只隐藏窗口、不退出
    import types

    win.tray = types.SimpleNamespace(ok=True, error=None, notify=lambda *a, **k: None)
    win.on_close_click()
    pump(win, 0.4)
    joined2 = dlg_texts(win)
    check("最小化到托盘" in joined2, f"托盘可用时应提供最小化到托盘：{joined2}")
    check(bool(win.root.bind_all("<Return>")), "询问框显示期间应注册回车快捷键")
    check(bool(win.root.bind_all("<Escape>")), "询问框显示期间应注册 ESC 快捷键")
    win._close_choice("tray")
    pump(win, 0.5)
    check(not quit_calls, "选择最小化到托盘不应退出程序")
    check(not win.root.winfo_viewable(), "选择最小化到托盘后窗口应隐藏")
    check(not win.root.bind_all("<Return>"), "关闭询问框后应解除回车快捷键")
    win.toggle_visible(True)
    pump(win, 0.5)
    check(win.root.winfo_viewable(), "窗口应能重新显示")

    # 键盘路径：回车 = 最小化到托盘（打包 exe 的实测发现过回车无效的问题）
    win.on_close_click()
    pump(win, 0.4)
    check(win._close_dlg is not None, "回车测试前应弹出询问框")
    win._close_default()
    pump(win, 0.5)
    check(not quit_calls, "回车不应退出程序")
    check(not win.root.winfo_viewable(), "回车应最小化到托盘（隐藏窗口）")
    win.toggle_visible(True)
    pump(win, 0.5)
    win.tray = None

    c = win.canvas
    cw, ch = c.winfo_width(), c.winfo_height()
    print(f"窗口 {win.root.winfo_width()}x{win.root.winfo_height()}  画布 {cw}x{ch}")

    # ---------- 1. 键位数量与边界
    expected_tiles = len(km.LAYOUT) + len(km.MOUSE_TILES)
    check(len(win._key_boxes) == expected_tiles,
          f"绘制方块数 {len(win._key_boxes)} != 期望 {expected_tiles}")
    check(cw > 400 and ch > 200, f"画布尺寸异常 {cw}x{ch}")
    for x1, y1, x2, y2, kid in win._key_boxes:
        check(x1 >= 0 and y1 >= 0 and x2 <= cw + 0.5 and y2 <= ch + 0.5,
              f"{kid} 越界 ({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f}) 画布 {cw}x{ch}")
        check(x2 - x1 > 4 and y2 - y1 > 4, f"{kid} 尺寸过小")

    # ---------- 2. 无重叠
    boxes = win._key_boxes
    overlaps = 0
    for i in range(len(boxes)):
        ax1, ay1, ax2, ay2, ak = boxes[i]
        for j in range(i + 1, len(boxes)):
            bx1, by1, bx2, by2, bk = boxes[j]
            if ax1 < bx2 - 0.5 and bx1 < ax2 - 0.5 and ay1 < by2 - 0.5 and by1 < ay2 - 0.5:
                overlaps += 1
                if overlaps < 5:
                    FAILS.append(f"键位重叠: {ak} <-> {bk}")
    check(overlaps == 0, f"共有 {overlaps} 处键位重叠")
    CHECKS[0] += 1

    # ---------- 3. 命中测试
    bad_hit = []
    for x1, y1, x2, y2, kid in boxes:
        if win._hit((x1 + x2) / 2, (y1 + y2) / 2) != kid:
            bad_hit.append(kid)
    check(not bad_hit, f"命中测试失败的键位: {bad_hit[:8]}")
    check(win._hit(-5, -5) is None, "画布外坐标不应命中键位")

    # ---------- 4. 热力颜色：有数据的键应与 0 次键不同
    c_key = win._heat("A", False)
    c_zero = win._heat("Z", False)
    check(c_key != c_zero, f"热力色未区分: A={c_key} Z={c_zero}")
    check(win._today.get("A", 0) == hot["A"], f"今日 A 计数 {win._today.get('A')}")
    check(win._today.get("MouseLeft", 0) == hot["MouseLeft"], "鼠标左键今日计数")

    # ---------- 5. 悬停详情面板 + 浮动气泡
    # 先把真实光标移出窗口（用 SendInput，SetCursorPos 不保证产生 WM_MOUSEMOVE），
    # 避免真实鼠标事件抢占 hover 状态
    user32 = ctypes.WinDLL("user32")
    warp(win.root.winfo_screenwidth() - 3, win.root.winfo_screenheight() - 3)
    pump(win, 0.5)
    check(win.hover_key is None, "光标移出后 hover 应为空")
    for target in ("A", "Space", "MouseLeft", "WheelUp", "Num0"):
        win._set_hover(target, win.root.winfo_rootx() + 200,
                       win.root.winfo_rooty() + 200)
        pump(win, 0.35)
        st = counters.stats_for(target)
        cn, en = km.display_of(target)
        check(win.lbl_key_cn.cget("text") == cn, f"{target} 详情标题 {win.lbl_key_cn.cget('text')}")
        check(win.lbl_key_code.cget("text") == en, f"{target} 详情代号")
        check(win.stat_total.cget("text") == f"{st['total']:,}",
              f"{target} 总次数显示 {win.stat_total.cget('text')} != {st['total']:,}")
        check(win.stat_week.cget("text") == f"{st['week']:,}", f"{target} 近七日显示")
        check(win.stat_today.cget("text") == f"{st['today']:,}", f"{target} 今日显示")
        # 按住时长：总 / 近七日 / 今日 三个口径都要与 counters 一致
        hold = counters.dur_stats_for(target)
        for lbl, key, cap in ((win.dur_total, "total", "按住总时长"),
                              (win.dur_week, "week", "按住近七日"),
                              (win.dur_today, "today", "按住今日")):
            want = "按住 " + th.fmt_dur(hold[key])
            check(lbl.cget("text") == want,
                  f"{target} {cap}显示 {lbl.cget('text')!r} != {want!r}")
        check(win.hover_key == target, f"{target} hover_key 状态")
        check(win._tip is not None and win._tip.winfo_viewable(),
              f"{target} 浮动气泡未显示")
        if win._tip is not None:
            vals = [l.cget("text") for l in win.tip_rows]
            check(vals == [f"{st['total']:,}", f"{st['week']:,}", f"{st['today']:,}"],
                  f"{target} 气泡数字 {vals}")
            hvals = [l.cget("text") for l in win.tip_hold_rows]
            want_h = [th.fmt_dur(hold["total"]), th.fmt_dur(hold["week"]),
                      th.fmt_dur(hold["today"])]
            check(hvals == want_h, f"{target} 气泡按住时长 {hvals} != {want_h}")
            check(win.tip_title.cget("text").startswith(cn), f"{target} 气泡标题")
    # 移开后隐藏
    win._set_hover(None)
    pump(win, 0.3)
    check(win._tip is not None and not win._tip.winfo_viewable(), "移开后气泡应隐藏")
    check(win.lbl_key_cn.cget("text") == "全部键位汇总", "移开后应回到汇总")

    # ---------- 6. 趋势图 7 根柱子
    chart_items = win.chart.find_all()
    rects = [i for i in chart_items if win.chart.type(i) == "rectangle"]
    texts = [i for i in chart_items if win.chart.type(i) == "text"]
    check(len(rects) == 7, f"趋势图柱数 {len(rects)} != 7")
    check(len(texts) >= 7, f"趋势图缺少日期标签 ({len(texts)})")

    # ---------- 7. 状态栏（含托盘占位）不报错且有内容
    win._update_status()
    status = win.lbl_status.cget("text")
    check("钩子" in status and "落库" in status, f"状态栏内容异常: {status}")
    check(win.counters.flush_errors == 0, f"写盘错误 {win.counters.flush_errors}")

    # ---------- 7b. 架构标识（32/64 位两份包靠这个区分）
    check(sysutil.arch_tag() in status,
          f"状态栏应含架构标记 {sysutil.arch_tag()}: {status}")
    title_txt = win.lbl_title.cget("text")
    check(title_txt == sysutil.title_text(),
          f"标题应为 {sysutil.title_text()!r} 实际 {title_txt!r}")
    check(("32位" in title_txt) == (sysutil.arch_bits() == 32),
          f"标题位数标记与实际架构不符: {title_txt!r} / {sysutil.arch_bits()}位")
    if sysutil.arch_bits() == 32:
        check("Win7兼容版" in title_txt, f"32 位标题应标明 Win7 兼容版: {title_txt!r}")

    # ---------- 8. 缩放后重新布局仍然正确
    for w, h in ((760, 520), (1500, 700)):
        win.root.geometry(f"{w}x{h}")
        pump(win, 0.8)
        cw2 = win.canvas.winfo_width()
        bad = [k for x1, y1, x2, y2, k in win._key_boxes if x2 > cw2 + 0.5 or x1 < -0.5]
        check(not bad, f"{w}px 宽度下越界键位 {bad[:5]}")
        check(len(win._key_boxes) == expected_tiles, f"{w}px 下键位数异常")
        miss = [k for x1, y1, x2, y2, k in win._key_boxes
                if win._hit((x1 + x2) / 2, (y1 + y2) / 2) != k]
        check(not miss, f"{w}px 下命中测试失败 {miss[:5]}")

    # ---------- 9. 真实鼠标移动命中 + 截图（供人工确认）
    # 注意：这台机器上可能有人在同时使用鼠标，因此不能只断言"此刻 hover==G"，
    # 而是断言"真实 Motion 事件确实命中过 G"，并在没人抢鼠标时做到当前悬停也正确。
    win.root.geometry("1180x620+80+60")
    pump(win, 0.8)
    target = "G"
    box = next(b for b in win._key_boxes if b[4] == target)
    rx = win.canvas.winfo_rootx() + int((box[0] + box[2]) / 2)
    ry = win.canvas.winfo_rooty() + int((box[1] + box[3]) / 2)

    hits: list[tuple[int, int, str | None]] = []

    def on_motion(e):
        try:
            hits.append((e.x, e.y, win._hit(e.x, e.y)))
        except Exception:
            pass

    win.canvas.bind("<Motion>", on_motion, add="+")
    hover_ok = False
    for attempt in range(6):
        warp(rx, ry)
        pump(win, 0.7)
        if win.hover_key == target:
            hover_ok = True
            break
        time.sleep(0.2)
    real_hits = [h for h in hits if h[2] == target]
    print(f"[信息] 真实鼠标移动到 G 键中心 ({rx},{ry}): hover_key={win.hover_key} "
          f"光标={win.root.winfo_pointerxy()} 命中 G 的 Motion 事件={len(real_hits)} 次")
    check(hover_ok or bool(real_hits),
          f"真实鼠标移动到 {target} 键始终未命中（hover={win.hover_key}，"
          f"Motion 命中记录={len(real_hits)}）")
    if not hover_ok:
        print("[提示] 当前悬停不是 G（鼠标可能正被人使用），已按 Motion 命中记录判定通过")
    shot = capture(win, args.shot, rx, ry)
    print("截图:", shot)

    # ---------- 10. 暂停按钮
    before = win.btn_pause.cget("text")
    win.toggle_pause()
    pump(win, 0.5)
    check(win.counters.paused and win.hooks.paused, "暂停未生效")
    check(win.btn_pause.cget("text") != before, "暂停按钮文字未变化")
    check(win.dot.cget("fg") == "#ffb454", "暂停时状态点未变色")
    win.toggle_pause()
    pump(win, 0.5)
    check(not win.counters.paused, "恢复未生效")

    # ---------- 11. 托盘图标（真实创建 Shell_NotifyIcon 图标 + 隐藏窗口）
    from core.tray import TrayIcon

    got_cmds: list[int] = []
    tray = TrayIcon("键鼠使用统计", got_cmds.append,
                    lambda: {"visible": True, "paused": False, "autostart": False},
                    icon_path=sysutil.resource_path("app.ico"))
    check(tray.start(), f"托盘图标创建失败: {tray.error}")
    check(bool(tray.hwnd), "托盘隐藏窗口句柄为空")
    tray.notify("键鼠使用统计", "托盘通知测试")
    time.sleep(0.4)
    check(tray.ok, "托盘状态应为 ok")
    tray.stop()
    time.sleep(0.2)
    check(tray.hwnd is not None, "托盘句柄应保留")
    print(f"[信息] 托盘图标: ok={tray.ok} hwnd={tray.hwnd} error={tray.error}")

    win.root.destroy()
    hooks.stop()
    counters.stop()
    store.close()

    print(f"\n断言 {CHECKS[0]} 项，失败 {len(FAILS)} 项")
    if FAILS:
        for f in FAILS[:30]:
            print("  [x]", f)
        return 1
    print("[PASS] UI 布局/热力图/悬停气泡/详情面板/趋势图/缩放/暂停/托盘/关闭询问 全部通过")
    return 0


def capture(win, path: str, rx: int, ry: int) -> str:
    """截取窗口区域（含浮动气泡）供人工查看。"""
    try:
        from PIL import ImageGrab
    except Exception as exc:
        return f"未安装 Pillow，跳过截图 ({exc})"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    x = win.root.winfo_rootx() - 12
    y = win.root.winfo_rooty() - 12
    right = x + win.root.winfo_width() + 24
    bottom = y + win.root.winfo_height() + 24
    if win._tip is not None and win._tip.winfo_viewable():
        right = max(right, win._tip.winfo_rootx() + win._tip.winfo_width() + 12)
        bottom = max(bottom, win._tip.winfo_rooty() + win._tip.winfo_height() + 12)
        x = min(x, win._tip.winfo_rootx() - 8)
        y = min(y, win._tip.winfo_rooty() - 8)
    img = ImageGrab.grab(bbox=(max(0, x), max(0, y), right, bottom), all_screens=True)
    img.save(path)
    return f"{path} ({img.width}x{img.height})"


if __name__ == "__main__":
    sys.exit(main())
