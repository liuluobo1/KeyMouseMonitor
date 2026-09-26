"""键鼠使用统计 —— 程序入口。

用法：
  python main.py                 正常启动（UI + 托盘 + 全局键鼠钩子）
  python main.py --no-ui         无界面后台运行（调试用，Ctrl+C 退出）
  python main.py --dump [--out]  只读导出统计数据（JSON），不启动监控
  python main.py --selftest      运行内置自检（键位映射/存储/统计口径）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 控制台可能是 GBK；打包成窗口程序后 stdout 也可能是 None，两种情况都要容错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def safe_print(*a, **kw) -> None:
    try:
        print(*a, **kw)
    except Exception:
        pass


from core import keymap as km  # noqa: E402
from core import sysutil  # noqa: E402
from core.counters import Counters  # noqa: E402
from core.hooks import HookEngine  # noqa: E402
from core.store import Store, read_snapshot, today_str  # noqa: E402

DEFAULT_DATA_DIR = r"F:\KeyMouseMonitor"


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="KeyMouseMonitor", add_help=True)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--no-ui", action="store_true", help="无界面运行")
    p.add_argument("--no-tray", action="store_true", help="禁用托盘图标")
    p.add_argument("--dump", action="store_true", help="导出统计 JSON 后退出")
    p.add_argument("--out", default=None, help="把导出结果写入文件")
    p.add_argument("--selftest", action="store_true", help="运行自检")
    p.add_argument("--autostart", choices=["on", "off", "status"], default=None,
                   help="开机自启动开关（注册表 HKCU\\...\\Run）")
    p.add_argument("--quit", action="store_true",
                   help="让正在运行的实例优雅退出（先落库再关闭）")
    p.add_argument("--no-elevate", action="store_true",
                   help="启动时不要自动申请管理员权限（默认会提权）")
    p.add_argument("--elevated", action="store_true",
                   help=argparse.SUPPRESS)   # 内部标记：已经尝试过提权，别再申请一次
    return p.parse_args(argv)


# ------------------------------------------------------------------ 自检
def selftest() -> int:
    import tempfile

    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # 1) 键位映射
    check(km.resolve_key(0x41, 0x1E, 0) == "A", "vk A")
    check(km.resolve_key(0x10, 0x36, 0) == "RShift", "右 Shift 识别")
    check(km.resolve_key(0x10, 0x2A, 0) == "LShift", "左 Shift 识别")
    check(km.resolve_key(0x11, 0x1D, 0x01) == "RCtrl", "右 Ctrl 识别")
    check(km.resolve_key(0x11, 0x1D, 0x00) == "LCtrl", "左 Ctrl 识别")
    check(km.resolve_key(0x12, 0x38, 0x01) == "RAlt", "右 Alt 识别")
    check(km.resolve_key(0x0D, 0x1C, 0x01) == "NumEnter", "小键盘回车识别")
    check(km.resolve_key(0x0D, 0x1C, 0x00) == "Enter", "主回车识别")
    check(km.resolve_key(0x70, 0x3B, 0) == "F1", "F1 识别")
    check(km.resolve_key(0x60, 0x52, 0) == "Num0", "小键盘 0 识别")
    check(km.resolve_key(0xA0, 0x2A, 0) == "LShift", "VK_LSHIFT 识别")
    check(km.resolve_key(0xA1, 0x36, 0) == "RShift", "VK_RSHIFT 识别")
    check(km.resolve_key(0xA3, 0x1D, 1) == "RCtrl", "VK_RCONTROL 识别")

    # 2) 布局完整性
    ids = [e[0] for e in km.LAYOUT]
    check(len(ids) == len(set(ids)), "布局中存在重复键位")
    for needed in ("A", "Z", "0", "Space", "Enter", "Num0", "Up", "LCtrl", "RCtrl"):
        check(needed in ids, f"布局缺少 {needed}")
    for entry in km.LAYOUT:
        kid, row, x, w = entry[0], entry[1], entry[2], entry[3]
        h = entry[4] if len(entry) > 4 else 1
        check(0 <= row <= 5, f"{kid} 行号越界")
        check(x >= 0 and x + w <= km.TOTAL_UNITS + 1e-6, f"{kid} 横向越界 {x}+{w}")
        check(w > 0 and h > 0, f"{kid} 尺寸非法")

    # 3) 存储 + 计数
    tmp = tempfile.mkdtemp(prefix="kmm_selftest_")
    db = os.path.join(tmp, "t.db")
    store = Store(db)
    day = today_str()
    store.flush({day: {"A": 3, "MouseLeft": 2}}, {day: 120.0}, 120.0,
                {"started": "x", "ended": "y", "keys": 3, "clicks": 2, "px": 120.0},
                {day: {"A": 1500, "MouseLeft": 250}})
    snap = read_snapshot(db)
    check(snap["totals"].get("A") == 3, "落库累计 A")
    check(snap["totals"].get("MouseLeft") == 2, "落库累计 MouseLeft")
    check(abs(snap["move_day"].get(day, 0) - 120.0) < 1e-6, "落库移动距离")
    check(snap["meta"].get("move_total_px") == "120.0", "落库移动总计")
    check(len(snap["sessions"]) == 1, "会话记录")
    check(snap["dur_totals"].get("A") == 1500, "落库按住时长 A")
    check(snap["dur_totals"].get("MouseLeft") == 250, "落库按住时长 左键")
    check(snap["dur_by_day"].get(day, {}).get("A") == 1500, "落库按住时长按天 A")

    cnt = Counters(store, flush_interval=0.2)
    cnt.on_key("A")
    cnt.on_key("A")
    cnt.on_click(km.MOUSE_LEFT)
    cnt.on_move(100.0)
    cnt.on_hold("A", 500)
    cnt.on_hold(km.MOUSE_LEFT, 125)
    st = cnt.stats_for("A")
    check(st["total"] == 5 and st["today"] == 5 and st["week"] == 5,
          f"实时口径 A: {st}")
    st2 = cnt.stats_for(km.MOUSE_LEFT)
    check(st2["today"] == 3, f"实时口径 MouseLeft: {st2}")
    check(cnt.overall_stats()["total"] == 8, "汇总口径")
    hold = cnt.dur_stats_for("A")
    check(hold == {"total": 2000, "week": 2000, "today": 2000},
          f"实时按住时长 A: {hold}")
    hold2 = cnt.dur_stats_for(km.MOUSE_LEFT)
    check(hold2["today"] == 375, f"实时按住时长 MouseLeft: {hold2}")
    check(cnt.dur_overall_stats()["total"] == 2375,
          f"按住时长汇总: {cnt.dur_overall_stats()}")
    cnt.flush_now()
    snap2 = read_snapshot(db)
    check(snap2["totals"].get("A") == 5, "flush 后 A 累计")
    check(abs(snap2["move_day"].get(day, 0) - 220.0) < 1e-6, "flush 后移动距离")
    check(snap2["dur_totals"].get("A") == 2000, "flush 后按住时长 A")
    check(snap2["dur_by_day"].get(day, {}).get("A") == 2000, "flush 后按天按住时长 A")

    # 4) 数据目录 / 自启动命令
    d, note = sysutil.resolve_data_dir(os.path.join(tmp, "sub"))
    check(os.path.isdir(d), "数据目录可创建")
    check(note is None, "首选目录可用时无回退说明")
    check(sysutil.autostart_command().strip().startswith('"'), "自启动命令带引号")

    # 5) 权限 / 开机自启（计划任务）
    check(isinstance(sysutil.is_admin(), bool), "管理员权限检测可用")
    kind = sysutil.autostart_kind()
    check(kind in ("task", "run", "off"), f"开机自启类型: {kind}")
    if kind == "task":
        check(sysutil.autostart_enabled(), "计划任务应被识别为已启用")
    check(callable(sysutil.relaunch_as_admin), "提权重启接口存在")

    # 6) 单实例顺序：instance_running() 必须"只查询不创建"，否则同一进程里紧随
    #    其后的 acquire_single_instance() 会读到 ERROR_ALREADY_EXISTS，把自己
    #    误判成"已有实例"直接退出（表现为双击后静默不启动）
    if not sysutil.instance_running():
        check(sysutil.acquire_single_instance(),
              "instance_running() 之后仍能抢到单实例锁")

    store.close()

    if fails:
        safe_print("自检失败：")
        for f in fails:
            safe_print("  [x]", f)
        return 1
    safe_print("自检全部通过  (键位映射 / 布局 / 存储 / 统计口径 / 按住时长 / 目录)")
    return 0


# ------------------------------------------------------------------ 导出
def dump(data_dir: str, out: str | None) -> int:
    db = os.path.join(data_dir, "stats.db")
    if not os.path.exists(db):
        safe_print(f"数据库不存在: {db}")
        return 1
    snap = read_snapshot(db)
    mouse = set(km.MOUSE_KEYS)

    def stats_of(key: str) -> dict:
        return {
            "total": snap["totals"].get(key, 0),
            "today": snap["by_day"].get(today_str(), {}).get(key, 0),
        }

    dur_totals = snap.get("dur_totals", {})
    dur_by_day = snap.get("dur_by_day", {})

    def hold_of(key: str) -> dict:
        return {
            "total_ms": dur_totals.get(key, 0),
            "today_ms": dur_by_day.get(today_str(), {}).get(key, 0),
        }

    payload = {
        "db": db,
        "totals": snap["totals"],
        "by_day": snap["by_day"],
        "move_day": snap["move_day"],
        "dur_totals_ms": dur_totals,
        "dur_by_day_ms": dur_by_day,
        "meta": snap["meta"],
        "sessions": snap["sessions"],
        "focus": {k: stats_of(k) for k in ("A", "B", "MouseLeft", "WheelUp")},
        "focus_hold": {k: hold_of(k) for k in ("A", "B", "MouseLeft")},
        "keyboard_total": sum(n for k, n in snap["totals"].items() if k not in mouse),
        "mouse_total": sum(n for k, n in snap["totals"].items() if k in mouse),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out:
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            safe_print(f"写入失败: {exc}")
            return 1
    safe_print(text)
    return 0


# ------------------------------------------------------------------ 主流程
def run_app(args) -> int:
    data_dir, note = sysutil.resolve_data_dir(args.data_dir)
    db_path = os.path.join(data_dir, "stats.db")

    # 旧版把自启写在 HKCU\Run，开机只有普通权限（收不到"以管理员运行的窗口"的
    # 输入）。这里自动升级成"最高权限计划任务"：开机即管理员且不弹 UAC。
    try:
        migrated = sysutil.migrate_autostart_to_task()
    except Exception:
        migrated = None
    if migrated and not args.no_ui:
        safe_print(migrated)

    store = Store(db_path)
    counters = Counters(store)
    hooks = HookEngine(counters.on_key, counters.on_click, counters.on_move,
                       on_hold=counters.on_hold)
    installed = hooks.start()
    if not installed:
        safe_print(f"[警告] 键鼠钩子安装失败: {hooks.error}")
    counters.start()

    if args.no_ui:
        safe_print(f"后台监控中... 数据: {db_path}  (Ctrl+C 退出)")
        try:
            while True:
                time.sleep(5)
                sess = counters.session_stats()
                safe_print(f"本次运行 键盘 {sess['keys']} 点击 {sess['clicks']} "
                           f"移动 {sess['px']:.0f}px  {sess['per_min']:.0f} 次/分")
        except KeyboardInterrupt:
            pass
        hooks.stop()
        counters.stop()
        store.close()
        return 0

    from ui.app import CMD_QUIT, CMD_WAKE, MainWindow

    TrayIcon = None
    if not args.no_tray:
        from core.tray import TrayIcon  # noqa: F811

    holder: dict = {}
    tray_ref: dict = {"tray": None}

    def on_command(cmd: int) -> None:
        win = holder.get("win")
        if win is not None:
            win.actions.put(cmd)

    def on_quit() -> None:
        hooks.stop()
        counters.stop()          # 退出前把最后的增量写盘
        if tray_ref["tray"] is not None:
            tray_ref["tray"].stop()
        if holder.get("wake") is not None:
            holder["wake"].stop()
        store.close()            # 记录 last_exit / 合并 WAL
        win = holder.get("win")
        if win is not None:
            try:
                win.root.destroy()
            except Exception:
                pass
        os._exit(0)

    def on_session_end(ending: bool) -> None:
        """系统注销/关机：抢在进程被结束前把数据落库。"""
        try:
            counters.flush_now()
        except Exception:
            pass
        if ending:
            hooks.stop()
            try:
                counters.stop()
            except Exception:
                pass
            store.close()
            os._exit(0)

    win = MainWindow({
        "counters": counters,
        "hooks": hooks,
        "tray": None,
        "data_dir": data_dir,
        "db_path": db_path,
        "note": note,
        "on_quit": on_quit,
    })
    holder["win"] = win

    if TrayIcon is not None:
        tray = TrayIcon(sysutil.APP_TITLE, on_command, win.tray_state,
                        icon_path=sysutil.resource_path("app.ico"),
                        on_session_end=on_session_end)
        tray.start()
        win.tray = tray
        tray_ref["tray"] = tray
        if migrated:
            try:
                tray.notify("开机自启", migrated)
            except Exception:
                pass

    # 重复启动 -> 强制显示窗口；--quit -> 优雅退出（先落库）
    wake = sysutil.InstanceSignals(
        lambda: win.actions.put(CMD_WAKE),
        lambda: win.actions.put(CMD_QUIT),
    )
    wake.start()
    holder["wake"] = wake

    try:
        win.run()
    finally:
        hooks.stop()
        counters.stop()
        if tray_ref["tray"] is not None:
            tray_ref["tray"].stop()
        wake.stop()
        store.close()
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.selftest:
        return selftest()
    if args.autostart:
        if args.autostart == "status":
            kind = sysutil.autostart_kind()
            desc = {
                "task": "已启用（管理员计划任务，登录静默启动、不弹 UAC）",
                "run": "已启用（旧版 Run 键：开机只有普通权限，会收不到管理员游戏的输入）",
                "off": "未启用",
            }[kind]
            safe_print(f"开机自启: {desc}")
            safe_print(f"程序路径: {sysutil.autostart_command()}")
            safe_print(f"当前权限: {'管理员' if sysutil.is_admin() else '普通'}")
            if kind == "run":
                run = sysutil.get_autostart()
                if run:
                    safe_print(f"Run 键命令: {run}")
                    safe_print("建议：以管理员身份运行本程序后，重新点一次「开机自启」即可升级为计划任务")
            return 0
        enabled = args.autostart == "on"
        try:
            sysutil.set_autostart(enabled)
        except Exception as exc:
            safe_print(f"设置开机自启失败: {exc}")
            if enabled and not sysutil.is_admin():
                safe_print("提示：创建「最高权限」计划任务需要管理员权限，请以管理员身份运行后再试")
            return 1
        safe_print(f"已{'启用' if enabled else '关闭'}开机自启 -> {sysutil.autostart_command()}")
        return 0
    if args.quit:
        if not sysutil.instance_running():
            safe_print("没有正在运行的实例")
            return 0
        sysutil.signal_existing_instance_quit()
        # 等它把内存增量写盘并关闭（最多等 8 秒）
        import ctypes as _ct
        from ctypes import wintypes as _wt

        u32 = _ct.WinDLL("user32")
        u32.FindWindowW.restype = _wt.HWND
        u32.FindWindowW.argtypes = [_wt.LPCWSTR, _wt.LPCWSTR]
        for _ in range(27):
            time.sleep(0.3)
            if not u32.FindWindowW(None, sysutil.APP_TITLE):
                safe_print("正在运行的实例已优雅退出（数据已落库）")
                return 0
        safe_print("已发送退出请求，但窗口仍在（可能正在写盘）")
        return 1
    if args.dump:
        data_dir, _ = sysutil.resolve_data_dir(args.data_dir)
        return dump(data_dir, args.out)

    sysutil.enable_dpi_awareness()

    if not args.no_ui:
        # 顺序很重要：
        # 1) 已有实例 -> 只要唤起它（不要先提权，否则白弹一次 UAC）
        if sysutil.instance_running():
            sysutil.signal_existing_instance()
            return 0
        # 2) 还没提权 -> 先以管理员身份重启自己，再退出。
        #    必须发生在抢单实例锁之前：否则新实例会被本进程还没释放的锁挡住。
        #    --elevated 是保险丝：万一提权后 IsUserAnAdmin() 仍判为 False，
        #    也不会无限自我重启。
        if not args.no_elevate and not args.elevated and not sysutil.is_admin():
            if sysutil.relaunch_as_admin():
                return 0
        # 3) 抢单实例锁
        if not sysutil.acquire_single_instance():
            sysutil.signal_existing_instance()
            return 0

    return run_app(args)


if __name__ == "__main__":
    sys.exit(main())
