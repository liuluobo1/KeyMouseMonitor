"""tkinter 主界面：104 键热力图、悬停气泡、详情面板、鼠标面板、状态栏。"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import time
import tkinter as tk
from ctypes import wintypes
from datetime import date

from core import keymap as km
from core import sysutil

from . import theme as th

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# 显式声明原型：64 位下句柄必须按指针宽度传递，否则会被截断成 32 位
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, wintypes.UINT]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetWindowRgn.restype = ctypes.c_int
user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
# 32 位 Windows 的 user32 **不导出** SetWindowLongPtrW（这个名字只在 64 位的头
# 文件里是宏），只能回退用 SetWindowLongW。写死 Ptr 版本会让 32 位包一导入本模块
# 就 AttributeError（表现为"Failed to execute script main"）。
if hasattr(user32, "SetWindowLongPtrW"):
    _set_window_long = user32.SetWindowLongPtrW
    _set_window_long.restype = ctypes.c_void_p
    _set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
else:
    _set_window_long = user32.SetWindowLongW
    _set_window_long.restype = ctypes.c_long
    _set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

GA_ROOT = 2
GWLP_HWNDPARENT = -8
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

CMD_SHOW, CMD_PAUSE, CMD_AUTOSTART, CMD_OPEN_DIR, CMD_EXIT = 1, 2, 3, 4, 5
CMD_ASK_CLOSE = 6   # 恢复"关闭时询问"（托盘菜单用）
CMD_WAKE = 7        # 重复启动程序时：强制把窗口显示出来（不是切换）
CMD_QUIT = 8        # 外部请求优雅退出（先落库再关闭）


class MainWindow:
    def __init__(self, ctx: dict):
        self.counters = ctx["counters"]
        self.hooks = ctx["hooks"]
        self.tray = ctx.get("tray")
        self.data_dir = ctx["data_dir"]
        self.db_path = ctx["db_path"]
        self.note = ctx.get("note")
        self.on_quit = ctx["on_quit"]

        self.s = max(1.0, sysutil.system_dpi() / 96.0)
        self.root = tk.Tk()
        self.cn_font = th.pick_cn_font(self.root)
        self.cfg_path = os.path.join(self.data_dir, "config.json")
        self.cfg = self._load_cfg()

        self.actions: queue.Queue[int] = queue.Queue()
        self.hover_key: str | None = None
        self._key_boxes: list[tuple[float, float, float, float, str]] = []
        self._key_items: dict[str, tuple[int, int]] = {}
        self._today: dict[str, int] = {}
        self._today_max = 0
        self._tip = None
        self._drag: tuple[int, int] | None = None
        self._resize: tuple[int, int, int, int] | None = None
        self._cfg_dirty = False
        self._last_geom = ""
        self._chart_hover: str | None = None
        self._tray_tip_shown = False
        self._close_dlg = None
        self._prev_topmost: bool | None = None
        # 自启/权限状态缓存：autostart_kind() 会起 schtasks 进程，不能每秒查一次
        self._autostart_kind = sysutil.autostart_kind()
        self._autostart_error: str | None = None

        self.root.title(sysutil.APP_TITLE)
        self.root.configure(bg=th.BORDER)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        self._build()
        self._place_window()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_click)

        self.root.after(60, self._render_canvas)
        self.root.after(200, self._refresh)
        self.root.after(300, self._tick_actions)
        self.root.bind("<Configure>", self._on_configure)

    # ================================================================ 构建
    def px(self, v: float) -> int:
        return int(round(v * self.s))

    def _load_cfg(self) -> dict:
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_cfg(self) -> None:
        try:
            self.cfg["w"] = self.root.winfo_width()
            self.cfg["h"] = self.root.winfo_height()
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            with open(self.cfg_path, "w", encoding="utf-8") as fh:
                json.dump(self.cfg, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=th.PANEL, highlightthickness=0)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        self.outer = outer

        self._build_header(outer)
        if self.note:
            tk.Label(
                outer, text="⚠ " + self.note, bg=th.WARN, fg="#1a1200",
                font=(self.cn_font, -self.px(11)), anchor="w", padx=self.px(8),
                pady=self.px(3),
            ).pack(fill="x")
        self._build_detail(outer)

        self.canvas = tk.Canvas(outer, bg=th.PANEL, highlightthickness=0,
                                bd=0, height=self.px(330))
        self.canvas.pack(fill="both", expand=True, padx=self.px(6))
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self.canvas.bind("<Configure>", lambda e: self._render_canvas())

        self._build_status(outer)
        self._build_grip(outer)

    def _build_header(self, parent) -> None:
        bar = tk.Frame(parent, bg=th.PANEL)
        bar.pack(fill="x", padx=self.px(10), pady=(self.px(8), self.px(2)))
        self.header = bar

        self.dot = tk.Label(bar, text="●", bg=th.PANEL, fg=th.OK,
                            font=(self.cn_font, -self.px(13)))
        self.dot.pack(side="left")
        self.lbl_title = tk.Label(bar, text=sysutil.title_text(), bg=th.PANEL,
                                  fg=th.TEXT,
                                  font=(self.cn_font, -self.px(13), "bold"))
        self.lbl_title.pack(side="left", padx=(self.px(4), self.px(10)))

        self.btn_close = self._btn(bar, "✕", self.on_close_click, tone="danger")
        self.btn_close.pack(side="right")
        self.btn_min = self._btn(bar, "—", self.minimize_to_tray)
        self.btn_min.pack(side="right", padx=(0, self.px(4)))
        self.btn_dir = self._btn(bar, "数据文件夹", self.open_data_dir)
        self.btn_dir.pack(side="right", padx=(0, self.px(4)))
        self.btn_auto = self._btn(bar, "开机自启", self.toggle_autostart)
        self.btn_auto.pack(side="right", padx=(0, self.px(4)))
        self.btn_top = self._btn(bar, "置顶", self.toggle_topmost)
        self.btn_top.pack(side="right", padx=(0, self.px(4)))
        self.btn_pause = self._btn(bar, "暂停", self.toggle_pause)
        self.btn_pause.pack(side="right", padx=(0, self.px(4)))
        self.lbl_rate = tk.Label(bar, text="", bg=th.PANEL, fg=th.TEXT_DIM,
                                 font=(th.MONO_FONT, -self.px(11)))
        self.lbl_rate.pack(side="right", padx=(0, self.px(12)))

        for w in (bar, self.dot, self.lbl_title, self.lbl_rate):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    def _btn(self, parent, text, command, tone="normal"):
        bg = th.DANGER if tone == "danger" else th.PANEL_ALT
        fg = "#ffffff" if tone == "danger" else th.TEXT
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                       font=(self.cn_font, -self.px(11)),
                       padx=self.px(9), pady=self.px(3))
        hover = "#ff8a8a" if tone == "danger" else th.BORDER

        def on_enter(_e):
            if lbl.cget("bg") not in (th.OK, th.WARN):
                lbl.configure(bg=hover)

        def on_leave(_e):
            if lbl.cget("bg") not in (th.OK, th.WARN):
                lbl.configure(bg=bg)

        lbl.bind("<Button-1>", lambda e: command())
        lbl.bind("<Enter>", on_enter)
        lbl.bind("<Leave>", on_leave)
        lbl._normal_bg = bg
        return lbl

    def _build_detail(self, parent) -> None:
        panel = tk.Frame(parent, bg=th.PANEL_ALT, highlightthickness=1,
                         highlightbackground=th.BORDER)
        panel.pack(fill="x", padx=self.px(10), pady=(self.px(6), self.px(4)))
        self.detail = panel

        left = tk.Frame(panel, bg=th.PANEL_ALT)
        left.pack(side="left", padx=self.px(12), pady=self.px(8))
        self.lbl_key_cn = tk.Label(left, text="全部键位汇总", bg=th.PANEL_ALT,
                                   fg=th.TEXT, anchor="w",
                                   font=(self.cn_font, -self.px(17), "bold"))
        self.lbl_key_cn.pack(anchor="w")
        self.lbl_key_code = tk.Label(left, text="把鼠标移到任意键位/鼠标按键上查看明细",
                                     bg=th.PANEL_ALT, fg=th.TEXT_DIM, anchor="w",
                                     font=(th.MONO_FONT, -self.px(10)))
        self.lbl_key_code.pack(anchor="w")

        self.stat_total, self.dur_total = self._stat_block(panel, "总次数")
        self.stat_week, self.dur_week = self._stat_block(panel, "近七日")
        self.stat_today, self.dur_today = self._stat_block(panel, "今日")

        chart_wrap = tk.Frame(panel, bg=th.PANEL_ALT)
        chart_wrap.pack(side="left", padx=(self.px(6), self.px(6)))
        tk.Label(chart_wrap, text="近 7 日趋势", bg=th.PANEL_ALT, fg=th.TEXT_FAINT,
                 anchor="w", font=(self.cn_font, -self.px(9))).pack(anchor="w")
        self.chart = tk.Canvas(chart_wrap, width=self.px(210), height=self.px(64),
                               bg=th.PANEL_ALT, highlightthickness=0, bd=0)
        self.chart.pack()

        right = tk.Frame(panel, bg=th.PANEL_ALT)
        right.pack(side="right", padx=self.px(12), pady=self.px(8), fill="x",
                   expand=True)
        self.lbl_session = tk.Label(
            right, text="", bg=th.PANEL_ALT, fg=th.TEXT_DIM, anchor="e",
            justify="right", font=(th.MONO_FONT, -self.px(11)))
        self.lbl_session.pack(anchor="e")

    def _stat_block(self, parent, caption: str):
        """大数字（次数）+ 其下一行小字的按住时长。返回 (次数标签, 时长标签)。"""
        wrap = tk.Frame(parent, bg=th.PANEL_ALT)
        wrap.pack(side="left", padx=self.px(10), pady=self.px(6))
        tk.Label(wrap, text=caption, bg=th.PANEL_ALT, fg=th.TEXT_FAINT,
                 font=(self.cn_font, -self.px(10))).pack(anchor="w")
        val = tk.Label(wrap, text="0", bg=th.PANEL_ALT, fg=th.ACCENT,
                       font=(th.NUM_FONT, -self.px(24)))
        val.pack(anchor="w")
        hold = tk.Label(wrap, text="按住 -", bg=th.PANEL_ALT, fg=th.TEXT_DIM,
                        font=(self.cn_font, -self.px(10)))
        hold.pack(anchor="w")
        return val, hold

    def _build_status(self, parent) -> None:
        bar = tk.Frame(parent, bg=th.PANEL)
        bar.pack(fill="x", padx=self.px(12), pady=(0, self.px(6)))
        self.lbl_status = tk.Label(bar, text="", bg=th.PANEL, fg=th.TEXT_FAINT,
                                   anchor="w", font=(self.cn_font, -self.px(10)))
        self.lbl_status.pack(side="left")
        self.lbl_path = tk.Label(bar, text="", bg=th.PANEL, fg=th.TEXT_FAINT,
                                 anchor="e", font=(th.MONO_FONT, -self.px(9)))
        self.lbl_path.pack(side="right")

    def _build_grip(self, parent) -> None:
        grip = tk.Label(parent, text="◢", bg=th.PANEL, fg=th.TEXT_FAINT,
                        cursor="size_nw_se", font=(self.cn_font, -self.px(11)))
        grip.place(relx=1.0, rely=1.0, anchor="se", x=-self.px(3), y=-self.px(2))
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)

    # ================================================================ 位置
    def _place_window(self) -> None:
        w = int(self.cfg.get("w") or self.px(1140))
        h = int(self.cfg.get("h") or self.px(560))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None or not (-w + 80 <= x <= sw - 80 and -20 <= y <= sh - 60):
            x = max(10, sw - w - self.px(60))
            y = self.px(60)
        self.root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self.root.update_idletasks()
        self._round_corners()

    def _round_corners(self) -> None:
        try:
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, self.px(12), self.px(12))
            user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _on_configure(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        geom = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
        if geom != self._last_geom:
            self._last_geom = geom
            self._round_corners()
        self._cfg_dirty = True
        if not getattr(self, "_save_job", None):
            self._save_job = self.root.after(1200, self._save_cfg_later)

    def _save_cfg_later(self) -> None:
        self._save_job = None
        if self._cfg_dirty:
            self._cfg_dirty = False
            self._save_cfg()

    # ---------------------------------------------------------------- 拖动
    def _drag_start(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        self._set_hover(None)

    def _drag_move(self, e) -> None:
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, _e) -> None:
        self._drag = None
        self._save_cfg()

    def _resize_start(self, e) -> None:
        self._resize = (e.x_root, e.y_root, self.root.winfo_width(),
                        self.root.winfo_height())

    def _resize_move(self, e) -> None:
        if not self._resize:
            return
        x0, y0, w0, h0 = self._resize
        w = max(self.px(560), w0 + (e.x_root - x0))
        h = max(self.px(300), h0 + (e.y_root - y0))
        self.root.geometry(f"{w}x{h}")

    # ================================================================ 绘制
    def _render_canvas(self) -> None:
        c = self.canvas
        w = c.winfo_width()
        if w < 80:
            return
        c.delete("all")
        self._key_boxes.clear()
        self._key_items.clear()

        margin = self.px(6)
        gr = 0.10
        n_units = km.TOTAL_UNITS
        unit = (w - 2 * margin) / (n_units + (n_units - 1) * gr)
        gap = unit * gr
        rows = 6

        counts = self.counters.today_counts(km.LAYOUT_KEYS + km.MOUSE_TILES)
        self._today = counts
        self._today_max = max([v for v in counts.values()] + [0])

        base_font = max(6, int(unit * 0.34))
        for entry in km.LAYOUT:
            kid, row, xu, wu = entry[0], entry[1], entry[2], entry[3]
            hu = entry[4] if len(entry) > 4 else 1.0
            x1 = margin + xu * (unit + gap)
            y1 = margin + row * (unit + gap)
            x2 = x1 + wu * unit + (wu - 1) * gap
            y2 = y1 + hu * unit + (hu - 1) * gap
            self._draw_tile(kid, x1, y1, x2, y2, base_font, mouse=False)

        # ---- 鼠标面板
        tiles = km.MOUSE_TILES
        my1 = margin + rows * (unit + gap) + unit * 0.55
        tile_gap = gap
        tile_w = (w - 2 * margin - (len(tiles) - 1) * tile_gap) / len(tiles)
        tile_h = min(unit * 0.78, self.px(34))
        c.create_text(margin + 2, my1 - unit * 0.30, text="鼠标", anchor="w",
                      fill=th.TEXT_FAINT, font=(self.cn_font, -max(6, int(unit * 0.26))))
        for i, kid in enumerate(tiles):
            x1 = margin + i * (tile_w + tile_gap)
            self._draw_tile(kid, x1, my1, x1 + tile_w, my1 + tile_h,
                            max(6, int(unit * 0.30)), mouse=True)

        need_h = int(my1 + tile_h + margin)
        if abs(int(c.cget("height")) - need_h) > 2:
            c.configure(height=need_h)

    def _draw_tile(self, kid, x1, y1, x2, y2, base_font, mouse=False) -> None:
        c = self.canvas
        fill = self._heat(kid, mouse)
        rect = c.create_rectangle(x1, y1, x2, y2, fill=fill,
                                  outline=th.KEY_EDGE if not mouse else th.BORDER)
        label = self._tile_label(kid, mouse)
        size = base_font
        avail = (x2 - x1) - self.px(4)
        if label:
            size = max(5, min(size, int(avail / (0.62 * max(1, len(label))))))
        txt = c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label,
                            fill=th.TEXT if self._today.get(kid) else th.TEXT_DIM,
                            font=(th.MONO_FONT if len(label) == 1 else self.cn_font,
                                  -size))
        self._key_items[kid] = (rect, txt)
        self._key_boxes.append((x1, y1, x2, y2, kid))

    def _tile_label(self, kid: str, mouse: bool) -> str:
        if len(kid) == 1:
            return kid
        cn, en = km.display_of(kid)
        if mouse:
            return {
                km.MOUSE_LEFT: "左键", km.MOUSE_RIGHT: "右键", km.MOUSE_MIDDLE: "中键",
                km.MOUSE_X1: "侧1", km.MOUSE_X2: "侧2", km.WHEEL_UP: "滚上",
                km.WHEEL_DOWN: "滚下", km.WHEEL_LEFT: "滚左", km.WHEEL_RIGHT: "滚右",
            }.get(kid, en)
        return {
            "Backspace": "退格", "CapsLock": "大写", "LShift": "Shift", "RShift": "Shift",
            "LCtrl": "Ctrl", "RCtrl": "Ctrl", "LAlt": "Alt", "RAlt": "Alt",
            "LWin": "Win", "RWin": "Win", "Menu": "菜单", "Space": "空格",
            "Enter": "回车", "Tab": "Tab", "Esc": "Esc", "Delete": "Del",
            "Insert": "Ins", "PgUp": "PgUp", "PgDn": "PgDn", "PrtSc": "截屏",
            "ScrollLock": "滚动", "Pause": "暂停", "NumLock": "Num",
            "NumDiv": "/", "NumMul": "*", "NumSub": "-", "NumAdd": "+",
            "NumEnter": "回车", "NumDot": ".", "Backquote": "`", "Minus": "-",
            "Equal": "=", "BracketLeft": "[", "BracketRight": "]", "Backslash": "\\",
            "Semicolon": ";", "Quote": "'", "Comma": ",", "Period": ".", "Slash": "/",
            "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
        }.get(kid, en)

    def _heat(self, kid: str, mouse: bool = False) -> str:
        n = self._today.get(kid, 0)
        base = th.MOUSE_KEY if mouse else th.KEY
        if n <= 0 or self._today_max <= 0:
            return base
        import math

        f = math.log1p(n) / math.log1p(max(2, self._today_max))
        return th.blend(base, th.ACCENT_DIM, min(1.0, 0.25 + 0.75 * f))

    # ================================================================ 悬停
    def _hit(self, x: float, y: float) -> str | None:
        for x1, y1, x2, y2, kid in self._key_boxes:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return kid
        return None

    def _on_motion(self, event) -> None:
        kid = self._hit(event.x, event.y)
        self._set_hover(kid, event.x_root, event.y_root)

    def _set_hover(self, kid: str | None, rx: int | None = None, ry: int | None = None) -> None:
        if kid != self.hover_key:
            self.hover_key = kid
            self._update_detail()
            self._draw_chart()
            if kid is None:
                self._hide_tip()
            else:
                self._show_tip(kid, rx, ry)
        elif kid and self._tip is not None:
            self._place_tip(rx, ry)

    def _ensure_tip(self) -> None:
        if self._tip is not None:
            return
        self._tip = tk.Toplevel(self.root)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        self._tip.configure(bg=th.ACCENT)
        wrap = tk.Frame(self._tip, bg=th.PANEL_ALT)
        wrap.pack(padx=1, pady=1)
        self.tip_title = tk.Label(wrap, text="", bg=th.PANEL_ALT, fg=th.TEXT,
                                  font=(self.cn_font, -self.px(12), "bold"),
                                  anchor="w", padx=self.px(10), pady=self.px(2))
        self.tip_title.grid(row=0, column=0, columnspan=2, sticky="w")
        self.tip_rows = []
        for i, caption in enumerate(("总次数", "近七日", "今日"), start=1):
            tk.Label(wrap, text=caption, bg=th.PANEL_ALT, fg=th.TEXT_FAINT,
                     font=(self.cn_font, -self.px(10)), anchor="w",
                     padx=self.px(10)).grid(row=i, column=0, sticky="w")
            val = tk.Label(wrap, text="0", bg=th.PANEL_ALT, fg=th.ACCENT,
                           font=(th.NUM_FONT, -self.px(12)), anchor="e",
                           padx=self.px(10))
            val.grid(row=i, column=1, sticky="e")
            self.tip_rows.append(val)

        self.tip_hold_rows = []
        for i, caption in enumerate(("按住总时长", "按住近七日", "按住今日"), start=4):
            tk.Label(wrap, text=caption, bg=th.PANEL_ALT, fg=th.TEXT_FAINT,
                     font=(self.cn_font, -self.px(10)), anchor="w",
                     padx=self.px(10)).grid(row=i, column=0, sticky="w")
            hval = tk.Label(wrap, text="-", bg=th.PANEL_ALT, fg=th.TEXT,
                            font=(th.MONO_FONT, -self.px(11)), anchor="e",
                            padx=self.px(10))
            hval.grid(row=i, column=1, sticky="e")
            self.tip_hold_rows.append(hval)

    def _show_tip(self, kid: str, rx: int | None, ry: int | None) -> None:
        self._ensure_tip()
        cn, en = km.display_of(kid)
        st = self.counters.stats_for(kid)
        self.tip_title.configure(text=f"{cn}  ·  {en}")
        for lbl, key in zip(self.tip_rows, ("total", "week", "today")):
            lbl.configure(text=th.fmt_int(st[key]))
        hold = self.counters.dur_stats_for(kid)
        for lbl, key in zip(self.tip_hold_rows, ("total", "week", "today")):
            lbl.configure(text=th.fmt_dur(hold[key]))
        self._place_tip(rx, ry)

    def _place_tip(self, rx: int | None, ry: int | None) -> None:
        if self._tip is None:
            return
        if rx is None or ry is None:
            rx, ry = self.root.winfo_pointerxy()
        self._tip.update_idletasks()
        tw = self._tip.winfo_reqwidth()
        th_ = self._tip.winfo_reqheight()
        off = self.px(18)
        x = rx + off
        if x + tw > self.root.winfo_screenwidth() - self.px(4):
            x = rx - tw - off
        y = ry + off
        if y + th_ > self.root.winfo_screenheight() - self.px(4):
            y = ry - th_ - off
        self._tip.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _hide_tip(self) -> None:
        if self._tip is not None:
            self._tip.withdraw()

    # ================================================================ 刷新
    def _refresh(self) -> None:
        try:
            self._update_heat()
            self._update_detail()
            self._draw_chart()
            self._update_status()
            self._update_buttons()
        except Exception:
            pass
        self.root.after(1000, self._refresh)

    def _update_heat(self) -> None:
        kid = self.hover_key
        for key, (rect, txt) in self._key_items.items():
            mouse = key in km.MOUSE_TILES
            n = self._today.get(key, 0)
            fill = th.HOVER if key == kid else self._heat(key, mouse)
            self.canvas.itemconfigure(rect, fill=fill)
            self.canvas.itemconfigure(
                txt, fill=("#0d1117" if key == kid else
                           (th.TEXT if n else th.TEXT_DIM))
            )

    def _update_detail(self) -> None:
        if self.hover_key:
            cn, en = km.display_of(self.hover_key)
            st = self.counters.stats_for(self.hover_key)
            self.lbl_key_cn.configure(text=cn)
            self.lbl_key_code.configure(text=en)
        else:
            st = self.counters.overall_stats()
            self.lbl_key_cn.configure(text="全部键位汇总")
            self.lbl_key_code.configure(text="把鼠标移到任意键位/鼠标按键上查看明细")
        self.stat_total.configure(text=th.fmt_int(st["total"]))
        self.stat_week.configure(text=th.fmt_int(st["week"]))
        self.stat_today.configure(text=th.fmt_int(st["today"]))

        # 按住时长：与次数同样按 总 / 近七日 / 今日 三个口径
        hold = (self.counters.dur_stats_for(self.hover_key) if self.hover_key
                else self.counters.dur_overall_stats())
        for lbl, key in ((self.dur_total, "total"), (self.dur_week, "week"),
                         (self.dur_today, "today")):
            lbl.configure(text="按住 " + th.fmt_dur(hold[key]))

        sess = self.counters.session_stats()
        mv = self.counters.move_stats()
        cat = self.counters.category_totals()
        self.lbl_session.configure(
            text=(
                f"本次运行 键盘 {th.fmt_int(sess['keys'])} · 点击 {th.fmt_int(sess['clicks'])}\n"
                f"本次移动 {th.fmt_px(sess['px'])}   本次按住 {th.fmt_dur(sess['hold_ms'])}\n"
                f"今日移动 {th.fmt_px(mv['today'])}   累计 {th.fmt_px(mv['total'])}\n"
                f"累计键盘 {th.fmt_int(cat['keys'])} · 累计点击 {th.fmt_int(cat['clicks'])}"
            )
        )
        self.lbl_rate.configure(text=f"{sess['per_min']:.0f} 次/分")

    def _draw_chart(self) -> None:
        c = self.chart
        c.delete("all")
        w = max(60, c.winfo_width())
        h = max(30, c.winfo_height())
        pad = self.px(4)
        series = (
            self.counters.daily_series(self.hover_key, 7)
            if self.hover_key else self.counters.overall_series(7)
        )
        mx = max([v for _, v in series] + [1])
        n = len(series)
        slot = (w - 2 * pad) / n
        bw = slot * 0.58
        today = date.today().isoformat()
        for i, (day, v) in enumerate(series):
            x = pad + i * slot + (slot - bw) / 2
            bh = (h - self.px(16)) * (v / mx)
            bh = max(bh, 1.5)
            y1 = h - self.px(11) - bh
            color = th.ACCENT if day == today else th.ACCENT_DIM
            c.create_rectangle(x, y1, x + bw, h - self.px(11), fill=color, outline="")
            if v:
                c.create_text(x + bw / 2, y1 - self.px(5), text=th.fmt_int(v),
                              fill=th.TEXT_DIM, font=(th.MONO_FONT, -self.px(8)))
            mmdd = day[5:].replace("-", "/")
            c.create_text(x + bw / 2, h - self.px(5), text=mmdd, fill=th.TEXT_FAINT,
                          font=(th.MONO_FONT, -self.px(8)))

    def _update_status(self) -> None:
        name = os.path.basename(self.db_path)
        try:
            size = th.fmt_bytes(os.path.getsize(self.db_path))
        except OSError:
            size = "-"
        last = self.counters.last_flush_ts
        last_txt = "-" if not last else f"{int(time.time() - last)}s 前"
        hook_txt = "钩子正常" if self.hooks.installed else "钩子异常"
        if self.hooks.error:
            hook_txt = self.hooks.error
        if self.tray is None:
            tray_txt = "托盘 未启用"
        elif getattr(self.tray, "ok", False):
            tray_txt = "托盘 正常"
        else:
            tray_txt = f"托盘 失败({getattr(self.tray, 'error', '?')})"
        err_txt = f"写盘错误 {self.counters.flush_errors}"
        if self.counters.last_error:
            err_txt += f" ({self.counters.last_error.strip().splitlines()[-1][:60]})"
        # 权限很关键：非管理员时收不到"以管理员运行的窗口"的输入（UIPI 限制）
        admin_txt = "权限 管理员" if sysutil.is_admin() else "权限 普通⚠"
        auto_txt = {"task": "自启 管理员任务",
                    "run": "自启 Run键(普通权限)⚠",
                    "off": "自启 未开"}.get(self._autostart_kind, "自启 ?")
        if self._autostart_error:
            auto_txt += f"({self._autostart_error})"
        self.lbl_status.configure(
            text=(f"{hook_txt} · {tray_txt} · {admin_txt} · {sysutil.arch_tag()} · "
                  f"{auto_txt} · "
                  f"已重装 {self.hooks.reinstalls} 次 · "
                  f"落库 {last_txt} · {err_txt} · "
                  f"数据库 {name} {size}")
        )
        self.lbl_path.configure(text=self.data_dir)

    def _update_buttons(self) -> None:
        paused = self.counters.paused
        self.btn_pause.configure(text="继续" if paused else "暂停",
                                 bg=th.WARN if paused else self.btn_pause._normal_bg,
                                 fg="#1a1200" if paused else th.TEXT)
        self.dot.configure(fg=th.WARN if paused else th.OK)
        top = bool(self.root.attributes("-topmost"))
        self.btn_top.configure(text="已置顶" if top else "未置顶",
                               bg=th.ACCENT_DIM if top else self.btn_top._normal_bg,
                               fg=th.TEXT)
        auto = self._autostart_kind != "off"
        self.btn_auto.configure(text="开机自启 ✓" if auto else "开机自启",
                                bg=th.ACCENT_DIM if auto else self.btn_auto._normal_bg)

    # ================================================================ 动作
    def _tick_actions(self) -> None:
        try:
            while True:
                cmd = self.actions.get_nowait()
                self._handle(cmd)
        except queue.Empty:
            pass
        except Exception:
            pass
        self.root.after(200, self._tick_actions)

    def _handle(self, cmd: int) -> None:
        if cmd == CMD_SHOW:
            self.toggle_visible()
        elif cmd == CMD_WAKE:
            self.toggle_visible(True)
        elif cmd == CMD_QUIT:
            self.quit()
        elif cmd == CMD_ASK_CLOSE:
            self.ask_close_again()
        elif cmd == CMD_PAUSE:
            self.toggle_pause()
        elif cmd == CMD_AUTOSTART:
            self.toggle_autostart()
        elif cmd == CMD_OPEN_DIR:
            self.open_data_dir()
        elif cmd == CMD_EXIT:
            self.quit()

    def toggle_visible(self, show: bool | None = None) -> None:
        if show is None:
            show = not self.root.winfo_viewable()
        if show:
            self.root.deiconify()
            self.root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
            self.root.lift()
            try:
                user32.SetForegroundWindow(user32.GetAncestor(self.root.winfo_id(), 2))
            except Exception:
                pass
        else:
            self._hide_tip()
            self.root.withdraw()

    def minimize_to_tray(self) -> None:
        if self.tray is not None and getattr(self.tray, "ok", False):
            self.toggle_visible(False)
            if not self._tray_tip_shown:
                self._tray_tip_shown = True
                try:
                    self.tray.notify("键鼠使用统计仍在后台运行",
                                     "监控没有停止。右键托盘图标可显示窗口或退出程序。")
                except Exception:
                    pass
        else:
            self.quit()

    # ---------------------------------------------------------------- 关闭询问
    @property
    def tray_available(self) -> bool:
        return self.tray is not None and getattr(self.tray, "ok", False)

    def on_close_click(self) -> None:
        """点 ✕（或 Alt+F4）时：询问"直接退出"还是"最小化到托盘后台运行"。"""
        action = self.cfg.get("close_action")
        if action in ("tray", "quit"):
            self._apply_close_action(action)
            return
        self._show_close_dialog()

    def _show_close_dialog(self) -> None:
        if self._close_dlg is not None and self._close_dlg.winfo_exists():
            self._close_dlg.lift()
            self._raise_over_topmost(self._close_dlg)
            return

        dlg = tk.Toplevel(self.root)
        self._close_dlg = dlg
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.configure(bg=th.ACCENT_DIM if self.tray_available else th.BORDER)

        wrap = tk.Frame(dlg, bg=th.PANEL_ALT)
        wrap.pack(padx=1, pady=1)

        tk.Label(wrap, text="关闭键鼠使用统计", bg=th.PANEL_ALT, fg=th.TEXT,
                 anchor="w", font=(self.cn_font, -self.px(13), "bold"),
                 padx=self.px(14), pady=self.px(8)).pack(fill="x")

        if self.tray_available:
            question = "要退出程序，还是最小化到系统托盘在后台继续统计？"
        else:
            question = "系统托盘不可用，关闭将直接退出程序。"
        tk.Label(wrap, text=question, bg=th.PANEL_ALT, fg=th.TEXT_DIM, anchor="w",
                 justify="left", wraplength=self.px(330),
                 font=(self.cn_font, -self.px(11)),
                 padx=self.px(14)).pack(fill="x")

        row = tk.Frame(wrap, bg=th.PANEL_ALT)
        row.pack(fill="x", padx=self.px(14), pady=(self.px(12), self.px(6)))

        if self.tray_available:
            primary = self._dlg_btn(row, "最小化到托盘（后台运行）",
                                    lambda: self._close_choice("tray"),
                                    bg=th.ACCENT, fg="#0d1117")
            primary.pack(side="left")
        danger = self._dlg_btn(row, "直接退出程序", lambda: self._close_choice("quit"),
                               bg=th.DANGER, fg="#ffffff")
        danger.pack(side="left", padx=(self.px(6), 0))
        cancel = self._dlg_btn(row, "取消", lambda: self._close_choice("cancel"),
                               bg=th.PANEL, fg=th.TEXT)
        cancel.pack(side="left", padx=(self.px(6), 0))

        self._remember_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            wrap, text="不再询问（记住本次选择；可在托盘菜单恢复询问）",
            variable=self._remember_var, bg=th.PANEL_ALT, fg=th.TEXT_FAINT,
            activebackground=th.PANEL_ALT, activeforeground=th.TEXT,
            selectcolor=th.PANEL, highlightthickness=0, bd=0,
            font=(self.cn_font, -self.px(10)), anchor="w",
        ).pack(fill="x", padx=self.px(12), pady=(0, self.px(10)))

        dlg.bind("<Escape>", lambda e: self._close_choice("cancel"))
        dlg.bind("<Return>", lambda e: self._close_default())
        # 无边框(overrideredirect)窗口的键盘焦点不一定落到询问框上（实测按回车
        # 没反应），所以再加一层应用级按键绑定兜底；关闭时解除。
        self._bind_dialog_keys()
        dlg.update_idletasks()
        # 居中到主窗口
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px_, py_ = self.root.winfo_rootx(), self.root.winfo_rooty()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        x = px_ + max(0, (pw - w) // 2)
        y = py_ + max(0, (ph - h) // 2)
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"+{max(0, min(x, sw - w - 4))}+{max(0, min(y, sh - h - 4))}")
        try:
            dlg.grab_set()
            dlg.focus_force()
        except Exception:
            pass
        # 主窗口同样置顶，而且它是当前的**活动**窗口——Windows 会把"活动的置顶
        # 窗口"重新抬到询问框之上（实测弹出后约 0.3 秒询问框就被主窗口盖住，
        # 之前用定时器反复置顶就会和它打架、表现为闪烁）。所以询问框显示期间先把
        # 主窗口取消置顶：询问框成为唯一的置顶窗口，按 topmost 规则自然稳定处于
        # 最高层；关闭询问框时再恢复。只设一次、不轮询，因此不会闪烁。
        try:
            self._prev_topmost = bool(self.root.attributes("-topmost"))
            self.root.attributes("-topmost", False)
        except Exception:
            self._prev_topmost = None
        self._raise_over_topmost(dlg)
        # 窗口真正映射之后再抢一次焦点（创建瞬间抢焦点常常不生效）
        dlg.after(80, lambda: self._focus_dialog(dlg))

    def _close_default(self) -> None:
        self._close_choice("tray" if self.tray_available else "quit")

    def _focus_dialog(self, dlg) -> None:
        if dlg is None:
            return
        try:
            if dlg.winfo_exists():
                dlg.focus_force()
        except Exception:
            pass

    def _bind_dialog_keys(self) -> None:
        """询问框显示期间，应用内任何控件上的回车/ESC 都作用于询问框。"""
        try:
            self.root.bind_all("<Return>", lambda e: self._close_default())
            self.root.bind_all("<KP_Enter>", lambda e: self._close_default())
            self.root.bind_all("<Escape>", lambda e: self._close_choice("cancel"))
        except Exception:
            pass

    def _unbind_dialog_keys(self) -> None:
        for seq in ("<Return>", "<KP_Enter>", "<Escape>"):
            try:
                self.root.unbind_all(seq)
            except Exception:
                pass

    def _raise_over_topmost(self, win) -> None:
        """把询问框钉在主窗口之上、topmost 组的最前面（只做一次，不轮询、不闪烁）。

        只设 -topmost 不够：主窗口同样是置顶窗口、而且是当前的活动窗口，会把
        overrideredirect 的询问框压在下面。这里做两件事：

        1) 把主窗口显式设为询问框的**属主**（owned window）。Windows 保证拥有窗口
           在 Z 序上永远位于属主之上——这是结构性保证，不依赖反复置顶。
           tkinter 的 wm_transient() 对 overrideredirect 窗口不生效（实测属主仍是 0），
           所以直接用 SetWindowLongPtrW(GWLP_HWNDPARENT) 自己设。
        2) SetWindowPos(HWND_TOPMOST) 把它排到 topmost 组的最顶端。
        """
        try:
            hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT)
            if not hwnd:
                return
            owner = user32.GetAncestor(self.root.winfo_id(), GA_ROOT)
            if owner:
                _set_window_long(hwnd, GWLP_HWNDPARENT, owner)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _dlg_btn(self, parent, text, command, bg=th.PANEL, fg=th.TEXT):
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                       font=(self.cn_font, -self.px(11)),
                       padx=self.px(12), pady=self.px(6))
        lbl.bind("<Button-1>", lambda e: command())
        return lbl

    def _close_choice(self, choice: str) -> None:
        if self._close_dlg is None:
            return  # 询问框已关闭（例如回车被重复触发），不重复执行
        if choice in ("tray", "quit"):
            try:
                remember = bool(self._remember_var.get())
            except Exception:
                remember = False
            if remember:
                self.cfg["close_action"] = choice
                self._save_cfg()
        self._dismiss_close_dialog()
        if choice == "cancel":
            return
        self._apply_close_action(choice)

    def _dismiss_close_dialog(self) -> None:
        dlg, self._close_dlg = self._close_dlg, None
        self._unbind_dialog_keys()
        # 恢复主窗口原来的置顶状态（询问框显示期间被临时取消置顶）
        try:
            if self._prev_topmost is not None:
                self.root.attributes("-topmost", self._prev_topmost)
                if self._prev_topmost:
                    self.root.lift()
        except Exception:
            pass
        self._prev_topmost = None
        if dlg is None:
            return
        try:
            dlg.grab_release()
        except Exception:
            pass
        try:
            dlg.destroy()
        except Exception:
            pass

    def _apply_close_action(self, action: str) -> None:
        if action == "tray" and self.tray_available:
            self.minimize_to_tray()
        elif action == "tray":
            # 托盘不可用时不能真后台运行，直接退出更安全
            self.quit()
        else:
            self.quit()

    def ask_close_again(self) -> None:
        """托盘菜单：恢复"关闭时询问"。"""
        self.cfg.pop("close_action", None)
        self._save_cfg()
        if self.tray_available:
            try:
                self.tray.notify("已恢复询问", "下次点击 ✕ 会再次询问退出方式。")
            except Exception:
                pass

    def toggle_pause(self) -> None:
        paused = self.counters.toggle_pause()
        self.hooks.paused = paused
        self._update_buttons()

    def toggle_topmost(self) -> None:
        top = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", top)
        self.cfg["topmost"] = top
        self._save_cfg()
        self._update_buttons()

    def toggle_autostart(self) -> None:
        """开机自启开关。现在写的是"登录时 + 最高权限"的计划任务，
        这样开机就是管理员权限（才能收到以管理员运行的游戏窗口的输入）。"""
        want = self._autostart_kind != "off"
        try:
            sysutil.set_autostart(not want)
            self._autostart_error = None
        except Exception as exc:
            self._autostart_error = str(exc)[:120]
        self._autostart_kind = sysutil.autostart_kind()
        self._update_buttons()

    def open_data_dir(self) -> None:
        try:
            os.startfile(self.data_dir)  # noqa: S606
        except Exception:
            try:
                subprocess.Popen(["explorer", self.data_dir])
            except Exception:
                pass

    def tray_state(self) -> dict:
        try:
            return {
                "visible": bool(self.root.winfo_viewable()),
                "paused": bool(self.counters.paused),
                "autostart": sysutil.autostart_enabled(),
            }
        except Exception:
            return {}

    def quit(self) -> None:
        self._save_cfg()
        try:
            self._hide_tip()
        except Exception:
            pass
        self.on_quit()

    def run(self) -> None:
        self.root.mainloop()
