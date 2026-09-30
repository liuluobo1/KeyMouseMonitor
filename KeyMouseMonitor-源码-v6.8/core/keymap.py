"""键位映射与 104 键物理布局表。

- 统计 key id 采用 KeyboardEvent.code 风格（稳定、与键盘布局无关）。
- 鼠标事件使用 Mouse*/Wheel* 前缀的 id。
- 布局表用于 UI 绘制，单位为 "u"（一个标准键宽），总宽 23u。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 常量
LLKHF_EXTENDED = 0x01

# 一个标准键的布局单位数（UI 用）
TOTAL_UNITS = 23.0

# ---------------------------------------------------------------- 鼠标 id
MOUSE_LEFT = "MouseLeft"
MOUSE_RIGHT = "MouseRight"
MOUSE_MIDDLE = "MouseMiddle"
MOUSE_X1 = "MouseX1"
MOUSE_X2 = "MouseX2"
WHEEL_UP = "WheelUp"
WHEEL_DOWN = "WheelDown"
WHEEL_LEFT = "WheelLeft"
WHEEL_RIGHT = "WheelRight"

MOUSE_KEYS = (
    MOUSE_LEFT,
    MOUSE_RIGHT,
    MOUSE_MIDDLE,
    MOUSE_X1,
    MOUSE_X2,
    WHEEL_UP,
    WHEEL_DOWN,
    WHEEL_LEFT,
    WHEEL_RIGHT,
)

# 统一的中文/英文展示名（键盘 + 鼠标）
DISPLAY: dict[str, tuple[str, str]] = {
    # 鼠标
    MOUSE_LEFT: ("鼠标左键", "LMB"),
    MOUSE_RIGHT: ("鼠标右键", "RMB"),
    MOUSE_MIDDLE: ("鼠标中键", "MMB"),
    MOUSE_X1: ("鼠标侧键1", "X1"),
    MOUSE_X2: ("鼠标侧键2", "X2"),
    WHEEL_UP: ("滚轮向上", "Wheel Up"),
    WHEEL_DOWN: ("滚轮向下", "Wheel Down"),
    WHEEL_LEFT: ("滚轮向左", "Wheel Left"),
    WHEEL_RIGHT: ("滚轮向右", "Wheel Right"),
    # 特殊键中文名
    "Esc": ("退出键", "Esc"),
    "Tab": ("制表键", "Tab"),
    "CapsLock": ("大写锁定", "Caps"),
    "LShift": ("左 Shift", "LShift"),
    "RShift": ("右 Shift", "RShift"),
    "LCtrl": ("左 Ctrl", "LCtrl"),
    "RCtrl": ("右 Ctrl", "RCtrl"),
    "LAlt": ("左 Alt", "LAlt"),
    "RAlt": ("右 Alt", "RAlt"),
    "LWin": ("左 Win", "LWin"),
    "RWin": ("右 Win", "RWin"),
    "Menu": ("菜单键", "Menu"),
    "Space": ("空格", "Space"),
    "Enter": ("回车", "Enter"),
    "Backspace": ("退格", "Backspace"),
    "Delete": ("删除", "Del"),
    "Insert": ("插入", "Ins"),
    "Home": ("行首", "Home"),
    "End": ("行尾", "End"),
    "PgUp": ("上翻页", "PgUp"),
    "PgDn": ("下翻页", "PgDn"),
    "Up": ("方向键上", "Up"),
    "Down": ("方向键下", "Down"),
    "Left": ("方向键左", "Left"),
    "Right": ("方向键右", "Right"),
    "PrtSc": ("截屏", "PrtSc"),
    "ScrollLock": ("滚动锁定", "ScrLk"),
    "Pause": ("暂停", "Pause"),
    "NumLock": ("数字锁定", "Num"),
    "NumDiv": ("小键盘 /", "Num /"),
    "NumMul": ("小键盘 *", "Num *"),
    "NumSub": ("小键盘 -", "Num -"),
    "NumAdd": ("小键盘 +", "Num +"),
    "NumEnter": ("小键盘回车", "Num Enter"),
    "NumDot": ("小键盘 .", "Num ."),
    "Backquote": ("反引号 ~", "` ~"),
    "Minus": ("减号 -", "- _"),
    "Equal": ("等号 =", "= +"),
    "BracketLeft": ("左方括号 [", "[ {"),
    "BracketRight": ("右方括号 ]", "] }"),
    "Backslash": ("反斜杠 \\", "\\ |"),
    "Semicolon": ("分号 ;", "; :"),
    "Quote": ("单引号 '", "' \""),
    "Comma": ("逗号 ,", ", <"),
    "Period": ("句点 .", ". >"),
    "Slash": ("斜杠 /", "/ ?"),
}
for _i in range(1, 25):
    DISPLAY.setdefault(f"F{_i}", (f"功能键 F{_i}", f"F{_i}"))
for _i in range(10):
    DISPLAY.setdefault(f"Num{_i}", (f"小键盘 {_i}", f"Num {_i}"))
for _i in range(10):
    DISPLAY.setdefault(str(_i), (f"数字 {_i}", str(_i)))


def display_of(key_id: str) -> tuple[str, str]:
    """返回 (中文名, 英文名)。未知键位给出兜底展示。"""
    if key_id in DISPLAY:
        return DISPLAY[key_id]
    if len(key_id) == 1 and key_id.isalpha():
        return (f"字母 {key_id.upper()}", key_id.upper())
    if len(key_id) == 1 and key_id.isdigit():
        return (f"数字 {key_id}", key_id)
    if key_id.startswith("VK_"):
        return (f"未知键 {key_id}", key_id)
    return (key_id, key_id)


# ---------------------------------------------------------------- VK -> id
VK_TO_ID: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PgUp",
    0x22: "PgDn",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrtSc",
    0x2D: "Insert",
    0x2E: "Delete",
    0x5B: "LWin",
    0x5C: "RWin",
    0x5D: "Menu",
    0x5F: "Sleep",
    0x6A: "NumMul",
    0x6B: "NumAdd",
    0x6C: "NumEnter",
    0x6D: "NumSub",
    0x6E: "NumDot",
    0x6F: "NumDiv",
    0x90: "NumLock",
    0x91: "ScrollLock",
    0xBA: "Semicolon",
    0xBB: "Equal",
    0xBC: "Comma",
    0xBD: "Minus",
    0xBE: "Period",
    0xBF: "Slash",
    0xC0: "Backquote",
    0xDB: "BracketLeft",
    0xDC: "Backslash",
    0xDD: "BracketRight",
    0xDE: "Quote",
    0xE2: "Backslash",
    # 低级钩子有时直接给出左右手专用的虚拟键码
    0xA0: "LShift",
    0xA1: "RShift",
    0xA2: "LCtrl",
    0xA3: "RCtrl",
    0xA4: "LAlt",
    0xA5: "RAlt",
}
for _i in range(0x30, 0x3A):  # 0-9
    VK_TO_ID[_i] = chr(_i)
for _i in range(0x41, 0x5B):  # A-Z
    VK_TO_ID[_i] = chr(_i)
for _i in range(0x60, 0x6A):  # 小键盘 0-9
    VK_TO_ID[_i] = f"Num{_i - 0x60}"
for _i in range(0x70, 0x88):  # F1-F24
    VK_TO_ID[_i] = f"F{_i - 0x6F}"

# 需要靠 scanCode 区分左右手的修饰键
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12


def resolve_key(vk: int, scan: int, flags: int) -> str:
    """把低级键盘钩子的 (vkCode, scanCode, flags) 解析为稳定的 key id。"""
    ext = bool(flags & LLKHF_EXTENDED)
    if vk == VK_SHIFT:
        return "RShift" if scan == 0x36 else "LShift"
    if vk == VK_CONTROL:
        return "RCtrl" if ext else "LCtrl"
    if vk == VK_MENU:
        return "RAlt" if ext else "LAlt"
    if vk == 0x0D and ext:
        return "NumEnter"
    key_id = VK_TO_ID.get(vk)
    if key_id:
        return key_id
    return f"VK_{vk:02X}"


# ---------------------------------------------------------------- 物理布局
# (key_id, 行, 起始 x(u), 宽(u), 高(u))  —— 宽/高为 1 时可省略
LAYOUT: list[tuple[str, int, float, float, float]] = [
    # --- 行 0：功能键区
    ("Esc", 0, 0, 1),
    ("F1", 0, 2, 1), ("F2", 0, 3, 1), ("F3", 0, 4, 1), ("F4", 0, 5, 1),
    ("F5", 0, 6.5, 1), ("F6", 0, 7.5, 1), ("F7", 0, 8.5, 1), ("F8", 0, 9.5, 1),
    ("F9", 0, 11, 1), ("F10", 0, 12, 1), ("F11", 0, 13, 1), ("F12", 0, 14, 1),
    ("PrtSc", 0, 15.5, 1), ("ScrollLock", 0, 16.5, 1), ("Pause", 0, 17.5, 1),
    # --- 行 1
    ("Backquote", 1, 0, 1),
    ("1", 1, 1, 1), ("2", 1, 2, 1), ("3", 1, 3, 1), ("4", 1, 4, 1), ("5", 1, 5, 1),
    ("6", 1, 6, 1), ("7", 1, 7, 1), ("8", 1, 8, 1), ("9", 1, 9, 1), ("0", 1, 10, 1),
    ("Minus", 1, 11, 1), ("Equal", 1, 12, 1), ("Backspace", 1, 13, 2),
    ("Insert", 1, 15.5, 1), ("Home", 1, 16.5, 1), ("PgUp", 1, 17.5, 1),
    ("NumLock", 1, 19, 1), ("NumDiv", 1, 20, 1), ("NumMul", 1, 21, 1), ("NumSub", 1, 22, 1),
    # --- 行 2
    ("Tab", 2, 0, 1.5),
    ("Q", 2, 1.5, 1), ("W", 2, 2.5, 1), ("E", 2, 3.5, 1), ("R", 2, 4.5, 1), ("T", 2, 5.5, 1),
    ("Y", 2, 6.5, 1), ("U", 2, 7.5, 1), ("I", 2, 8.5, 1), ("O", 2, 9.5, 1), ("P", 2, 10.5, 1),
    ("BracketLeft", 2, 11.5, 1), ("BracketRight", 2, 12.5, 1), ("Backslash", 2, 13.5, 1.5),
    ("Delete", 2, 15.5, 1), ("End", 2, 16.5, 1), ("PgDn", 2, 17.5, 1),
    ("Num7", 2, 19, 1), ("Num8", 2, 20, 1), ("Num9", 2, 21, 1), ("NumAdd", 2, 22, 1, 2),
    # --- 行 3
    ("CapsLock", 3, 0, 1.75),
    ("A", 3, 1.75, 1), ("S", 3, 2.75, 1), ("D", 3, 3.75, 1), ("F", 3, 4.75, 1), ("G", 3, 5.75, 1),
    ("H", 3, 6.75, 1), ("J", 3, 7.75, 1), ("K", 3, 8.75, 1), ("L", 3, 9.75, 1),
    ("Semicolon", 3, 10.75, 1), ("Quote", 3, 11.75, 1), ("Enter", 3, 12.75, 2.25),
    ("Num4", 3, 19, 1), ("Num5", 3, 20, 1), ("Num6", 3, 21, 1),
    # --- 行 4
    ("LShift", 4, 0, 2.25),
    ("Z", 4, 2.25, 1), ("X", 4, 3.25, 1), ("C", 4, 4.25, 1), ("V", 4, 5.25, 1), ("B", 4, 6.25, 1),
    ("N", 4, 7.25, 1), ("M", 4, 8.25, 1),
    ("Comma", 4, 9.25, 1), ("Period", 4, 10.25, 1), ("Slash", 4, 11.25, 1), ("RShift", 4, 12.25, 2.75),
    ("Up", 4, 16.5, 1),
    ("Num1", 4, 19, 1), ("Num2", 4, 20, 1), ("Num3", 4, 21, 1), ("NumEnter", 4, 22, 1, 2),
    # --- 行 5
    ("LCtrl", 5, 0, 1.25), ("LWin", 5, 1.25, 1.25), ("LAlt", 5, 2.5, 1.25),
    ("Space", 5, 3.75, 6.25),
    ("RAlt", 5, 10, 1.25), ("RWin", 5, 11.25, 1.25), ("Menu", 5, 12.5, 1.25), ("RCtrl", 5, 13.75, 1.25),
    ("Left", 5, 15.5, 1), ("Down", 5, 16.5, 1), ("Right", 5, 17.5, 1),
    ("Num0", 5, 19, 2), ("NumDot", 5, 21, 1),
]

# 布局中出现的所有键位（用于 UI 反查）
LAYOUT_KEYS = tuple(e[0] for e in LAYOUT)

# 鼠标面板：UI 上的顺序
MOUSE_TILES = (
    MOUSE_LEFT, MOUSE_RIGHT, MOUSE_MIDDLE, MOUSE_X1, MOUSE_X2,
    WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT,
)
