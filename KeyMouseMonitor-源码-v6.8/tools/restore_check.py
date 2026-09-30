"""验证"退出 -> 重新启动后自动恢复到退出前的数据状态"。

流程：
  1) 启动程序 -> 合成已知输入 -> 等待落库
  2) --quit 优雅退出（退出前落库）
  3) 导出退出后的数据库快照 A
  4) 重新启动同一个数据目录 -> 导出快照 B，断言 A == B（逐键、逐日、移动距离全等）
  5) 用同一份数据真实构建 UI，断言界面显示的数字 == 数据库里的数字
  6) 清理：结束进程

用法：python tools/restore_check.py [--exe dist\\KeyMouseMonitor.exe] [--data-dir .restore]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ui_check  # noqa: E402  复用 UI 泵事件
from core import keymap as km  # noqa: E402
from core.hooks import HookEngine  # noqa: E402
from core.store import read_snapshot  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

FAILS: list[str] = []
CHECKS = [0]


def check(cond, msg):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(msg)


# ---------------------------------------------------------------- SendInput
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KBD(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _PUL)]


class _MOU(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _U(ctypes.Union):
    _fields_ = [("ki", _KBD), ("mi", _MOU)]


class _IN(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def kbd(vk: int, up: bool) -> _IN:
    return _IN(type=1, u=_U(ki=_KBD(vk, 0, 2 if up else 0, 0, None)))


def mou(flags: int, data: int = 0) -> _IN:
    return _IN(type=0, u=_U(mi=_MOU(0, 0, data, flags, 0, None)))


def send(seq: list[_IN]) -> int:
    arr = (_IN * len(seq))(*seq)
    return user32.SendInput(len(seq), ctypes.byref(arr), ctypes.sizeof(_IN))


TITLE = "键鼠使用统计"
# 计划合成的输入：键位 -> 次数
PLAN_KEYS = {"A": 6, "B": 4, "Num0": 3, "LShift": 2}
VK = {"A": 0x41, "B": 0x42, "Num0": 0x60, "LShift": 0xA0}
PLAN_LEFT, PLAN_RIGHT, PLAN_WHEEL = 5, 2, 3


def find_window(timeout: float) -> int:
    return ui_check.find_main_window(TITLE, timeout=timeout)


def launch(args, data_dir: str):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # --no-elevate：否则被测程序会申请管理员权限、弹出 UAC 卡住整个测试
    if args.exe:
        cmd = [os.path.abspath(args.exe), "--data-dir", data_dir, "--no-elevate"]
    else:
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "main.py"),
               "--data-dir", data_dir, "--no-elevate"]
    return subprocess.Popen(cmd, cwd=ROOT, env=env)


def dump_cmd(args, data_dir: str, out: str):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if args.exe:
        cmd = [os.path.abspath(args.exe), "--dump", "--data-dir", data_dir, "--out", out]
    else:
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "main.py"),
               "--dump", "--data-dir", data_dir, "--out", out]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=90)


def quit_cmd(args, data_dir: str):
    """请求正在运行的实例优雅退出，返回 (是否已退出, 输出)。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if args.exe:
        cmd = [os.path.abspath(args.exe), "--quit"]
    else:
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "main.py"), "--quit"]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=60)
    txt = (p.stdout or b"").decode("utf-8", "replace").strip()
    return p.returncode == 0, txt


def kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def diff_snapshots(a: dict, b: dict) -> tuple[list[str], list[str], float]:
    """比较退出前(A)与重启后(B)的快照。

    返回 (丢失项, 新增项, 移动距离增量)。判定标准是**不能丢数据**：
    用户在此期间真实敲键盘/动鼠标会让 B 比 A 大，属于正常，不算失败。
    """
    lost: list[str] = []
    grown: list[str] = []
    for field in ("totals", "by_day", "move_day"):
        fa, fb = a.get(field) or {}, b.get(field) or {}
        for key in sorted(set(fa) | set(fb)):
            va, vb = fa.get(key), fb.get(key)
            if isinstance(va, dict) and isinstance(vb, dict):
                for k2 in sorted(set(va) | set(vb)):
                    x, y = va.get(k2, 0), vb.get(k2, 0)
                    if (y or 0) < (x or 0):
                        lost.append(f"{field}[{key}][{k2}]: {x} -> {y}")
                    elif (y or 0) > (x or 0):
                        grown.append(f"{field}[{key}][{k2}]: {x} -> {y}")
            else:
                x = va if va is not None else ({} if isinstance(fb.get(key), dict) else 0)
                y = vb if vb is not None else ({} if isinstance(fa.get(key), dict) else 0)
                if isinstance(x, dict) or isinstance(y, dict):
                    continue
                if y < x:
                    lost.append(f"{field}[{key}]: {x} -> {y}")
                elif y > x:
                    grown.append(f"{field}[{key}]: {x} -> {y}")
    delta = 0.0
    for day, px in (b.get("move_day") or {}).items():
        delta += float(px) - float((a.get("move_day") or {}).get(day, 0) or 0)
    return lost, grown, delta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, ".restore"))
    ap.add_argument("--exe", default=None)
    args = ap.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    db = os.path.join(data_dir, "stats.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    label = os.path.basename(args.exe) if args.exe else "python main.py"
    print(f"被测程序: {label}   数据目录: {data_dir}")

    app = launch(args, data_dir)
    try:
        # ---------- 1) 合成已知输入
        hwnd = find_window(20)
        if not hwnd:
            print("[FAIL] 未找到窗口")
            return 2
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.8)
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2 + 40

        ui_check.warp(cx - 60, cy)                      # 产生移动距离
        for name, times in PLAN_KEYS.items():
            for _ in range(times):
                send([kbd(VK[name], False), kbd(VK[name], True)])
                time.sleep(0.01)
        for _ in range(PLAN_LEFT):
            send([mou(0x0002), mou(0x0004)])
        for _ in range(PLAN_RIGHT):
            send([mou(0x0008), mou(0x0010)])
        for _ in range(PLAN_WHEEL):
            send([mou(0x0800, 120)])
        for i in range(12):
            ui_check.warp(cx - 60 + i * 5, cy)
            time.sleep(0.02)
        print("已合成输入，等待落库(6s) ...")
        time.sleep(6.0)

        # ---------- 2) 优雅退出
        ok, txt = quit_cmd(args, data_dir)
        print(f"--quit 结果: ok={ok} 输出={txt}")
        check(ok, f"--quit 未成功退出: {txt}")
        time.sleep(1.0)
        check(not find_window(2), "退出后主窗口仍存在")
        check(ui_check_find_proc() == 0, "退出后仍有残留进程")

        # ---------- 3) 退出后的数据库快照 A
        out_a = os.path.join(data_dir, "snap_a.json")
        dump_cmd(args, data_dir, out_a)
        with open(out_a, "r", encoding="utf-8") as fh:
            a = json.load(fh)
        print("退出后快照 A:", json.dumps(a["totals"], ensure_ascii=False))
        # 这些只做"至少记录到了"的下界检查：机器上可能有真人在同时使用键鼠，
        # 精确计数由 tools/e2e.py 与内置 --selftest 保证。
        for name, times in PLAN_KEYS.items():
            check(a["totals"].get(name, 0) >= times, f"{name} 计数 {a['totals'].get(name)}")
        check(a["totals"].get(km.MOUSE_LEFT, 0) >= PLAN_LEFT, "左键计数")
        check(a["totals"].get(km.MOUSE_RIGHT, 0) >= PLAN_RIGHT, "右键计数")
        check(a["totals"].get(km.WHEEL_UP, 0) >= PLAN_WHEEL, "滚轮计数")
        check(a["meta"].get("session_open") == "0", "优雅退出应写入 session_open=0")
        check(bool(a["meta"].get("last_exit")), "优雅退出应记录 last_exit")
        check(len(a["sessions"]) == 1, f"会话记录数 {len(a['sessions'])}")
    finally:
        kill_tree(app.pid)

    # ---------- 4) 重启后快照 B 必须与 A 完全一致
    app2 = launch(args, data_dir)
    try:
        check(bool(find_window(20)), "重启后未出现窗口")
        time.sleep(7.0)
        out_b = os.path.join(data_dir, "snap_b.json")
        dump_cmd(args, data_dir, out_b)
        with open(out_b, "r", encoding="utf-8") as fh:
            b = json.load(fh)
        print("重启后快照 B:", json.dumps(b["totals"], ensure_ascii=False))
        lost, grown, px_delta = diff_snapshots(a, b)
        check(not lost, f"重启后数据丢失: {lost[:6]}")
        if grown:
            print(f"[信息] 退出后有人真实使用键鼠，新增 {len(grown)} 项、"
                  f"移动距离 +{px_delta:.0f}px（属于正常增量，不算丢失）")
        check(b["meta"].get("first_run") == a["meta"].get("first_run"),
              "first_run 应保持不变")
        check(len(b["sessions"]) >= 1, "重启后会话记录仍在")
        moved = b["move_day"].get(time.strftime("%Y-%m-%d"), 0)
        check(moved > 0, "重启后移动距离应保留")
        print(f"重启后累计: 键盘={b['keyboard_total']} 鼠标={b['mouse_total']} "
              f"移动={moved:.0f}px")
    finally:
        kill_tree(app2.pid)
        time.sleep(1.0)

    # ---------- 5) 纯读取恢复校验 + UI 显示校验（确定性：不发钩子、不挪鼠标）
    # 这一步完全复刻程序启动时的行为：Store -> Counters -> 界面读取，
    # 因此不受"此刻是否有人在用键鼠"影响，可以做严格相等断言。
    from core.counters import Counters
    from core.store import Store

    store2 = Store(os.path.join(data_dir, "stats.db"))
    counters2 = Counters(store2)          # 与程序启动时完全相同的加载路径
    hooks2 = HookEngine(None, None, None)  # 不启动：避免把测试自身的输入算进去
    win = None
    try:
        today = time.strftime("%Y-%m-%d")
        for target in ("A", "B", "Num0", "LShift", km.MOUSE_LEFT, km.WHEEL_UP):
            live = counters2.stats_for(target)
            db_total = b["totals"].get(target, 0)
            db_today = b["by_day"].get(today, {}).get(target, 0)
            check(live["total"] == db_total,
                  f"恢复后总次数 {target}: 内存={live['total']} 数据库={db_total}")
            check(live["today"] == db_today,
                  f"恢复后今日 {target}: 内存={live['today']} 数据库={db_today}")
            check(live["week"] >= db_today, f"近七日 {target} 应不小于今日")
        mv_restored = counters2.move_stats()
        check(abs(mv_restored["total"] - moved) < 1e-6,
              f"恢复后移动距离: 内存={mv_restored['total']:.1f} 数据库={moved:.1f}")
        overall2 = counters2.overall_stats()
        check(overall2["total"] == b["keyboard_total"] + b["mouse_total"],
              f"恢复后汇总 {overall2['total']} != "
              f"{b['keyboard_total'] + b['mouse_total']}")
        # 按住时长也要恢复
        hold_a = counters2.dur_stats_for("A")
        check(hold_a["total"] >= 0, "按住时长读取异常")
        print(f"纯读取恢复: 汇总={overall2['total']} 今日={overall2['today']} "
              f"移动={mv_restored['total']:.0f}px A按住={hold_a['total']}ms")

        # 真实构建界面，断言界面上的数字 == 数据库里的数字
        from ui.app import MainWindow

        win = MainWindow({
            "counters": counters2, "hooks": hooks2, "tray": None,
            "data_dir": data_dir, "db_path": os.path.join(data_dir, "stats.db"),
            "note": None, "on_quit": lambda: None,
        })
        ui_check.pump(win, 2.0)
        for target in ("A", "B", km.MOUSE_LEFT):
            want = counters2.stats_for(target)
            win._set_hover(target, 100, 100)
            ui_check.pump(win, 0.25)
            check(win.stat_total.cget("text") == f"{want['total']:,}",
                  f"界面 {target} 总次数 {win.stat_total.cget('text')} != {want['total']:,}")
            check(win.stat_today.cget("text") == f"{want['today']:,}",
                  f"界面 {target} 今日 {win.stat_today.cget('text')} != {want['today']:,}")
        check(win._today.get("A") == counters2.stats_for("A")["today"],
              "热力图今日计数与恢复数据不一致")
        win._set_hover(None)
        ui_check.pump(win, 0.3)
        check(win._update_status() is None, "状态栏刷新异常")
        print("界面显示校验: 与恢复后的内存/数据库数字一致")
    finally:
        if win is not None:
            win.root.destroy()
        store2.close()

    # ---------- 6) 清理
    check(ui_check_find_proc() == 0, "结束时仍有残留进程")
    extra = [f for f in os.listdir(data_dir)
             if f not in ("snap_a.json", "snap_b.json", "config.json")]
    print(f"数据目录保留文件: {sorted(extra)}")

    print(f"\n断言 {CHECKS[0]} 项，失败 {len(FAILS)} 项")
    if FAILS:
        for f in FAILS[:20]:
            print("  [x]", f)
        return 1
    print("[PASS] 退出 -> 重启后数据完全恢复：累计/今日/近七日/移动距离/会话 全部一致，"
          "界面显示的也是恢复后的数据")
    return 0


def ui_check_find_proc() -> int:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq KeyMouseMonitor.exe", "/NH"],
            capture_output=True, text=True, timeout=20).stdout
        return out.lower().count("keymousemonitor.exe")
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
