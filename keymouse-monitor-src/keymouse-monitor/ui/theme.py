"""配色、字体与数字格式化。"""

from __future__ import annotations

BG = "#0f1117"
PANEL = "#161a23"
PANEL_ALT = "#1b202b"
BORDER = "#2a3040"
KEY = "#232936"
KEY_EDGE = "#2f3748"
TEXT = "#e8ecf4"
TEXT_DIM = "#8b93a7"
TEXT_FAINT = "#5d6577"
ACCENT = "#4da3ff"
ACCENT_DIM = "#2b5f96"
OK = "#3ddc97"
WARN = "#ffb454"
DANGER = "#ff6b6b"
MOUSE_KEY = "#2b3446"
HOVER = "#4da3ff"

CN_FONT = "Microsoft YaHei UI"
NUM_FONT = "Segoe UI Semibold"
MONO_FONT = "Consolas"


def pick_cn_font(root) -> str:
    try:
        import tkinter.font as tkfont

        families = set(tkfont.families(root))
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimHei"):
            if name in families:
                return name
    except Exception:
        pass
    return "Segoe UI"


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def fmt_px(px: float) -> str:
    """像素 -> 人类可读距离（按 96 DPI 换算）。"""
    m = float(px) / 3779.53
    if m < 1:
        return f"{m * 100:.0f} cm"
    if m < 1000:
        return f"{m:.1f} m"
    return f"{m / 1000:.2f} km"


def fmt_dur(ms) -> str:
    """毫秒 -> 人类可读时长（中文，紧凑）。"""
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return "-"
    if ms < 0:
        ms = 0.0
    if ms < 1000:
        return f"{ms:.0f} 毫秒"
    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒" if sec else f"{minutes} 分"
    hours, minute = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时 {minute} 分" if minute else f"{hours} 小时"
    days, hour = divmod(hours, 24)
    return f"{days} 天 {hour} 小时" if hour else f"{days} 天"


def fmt_dur_short(ms) -> str:
    """更紧凑的时长（用于悬停气泡/小字）。"""
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return "-"
    if ms <= 0:
        return "0"
    seconds = ms / 1000.0
    if seconds < 1:
        return f"{ms:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def fmt_bytes(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def blend(c1: str, c2: str, t: float) -> str:
    """两个 #rrggbb 之间线性插值，t∈[0,1]。"""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{int(round(a[i] + (b[i] - a[i]) * t)):02x}" for i in range(3))
