"""系统托盘图标（纯 ctypes 调 Shell_NotifyIcon，无第三方依赖）。

托盘有自己的线程与消息循环；菜单点击只把命令塞进队列，
由 UI 线程消费，避免跨线程操作 tkinter。
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_APP = 0x8000
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_COMMAND = 0x0111
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512

MF_STRING = 0x0000
MF_CHECKED = 0x0008
MF_SEPARATOR = 0x0800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

# 菜单命令（数值必须与 ui/app.py 中的 CMD_* 保持一致）
CMD_SHOW = 1
CMD_PAUSE = 2
CMD_AUTOSTART = 3
CMD_OPEN_DIR = 4
CMD_EXIT = 5
CMD_ASK_CLOSE = 6


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", ctypes.c_void_p),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  ctypes.c_size_t, ctypes.c_ssize_t]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
user32.RegisterClassW.restype = wintypes.WORD
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.CreatePopupMenu.argtypes = []
user32.AppendMenuW.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                               ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  ctypes.c_void_p]
user32.DestroyMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                ctypes.c_size_t, ctypes.c_ssize_t]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.LoadImageW.restype = ctypes.c_void_p
user32.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadIconW.restype = ctypes.c_void_p
user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]
shell32.ExtractIconExW.restype = wintypes.UINT
shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.UINT]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

WM_TRAY = WM_APP + 20


class TrayIcon:
    """托盘图标 + 右键菜单。state_provider() 返回菜单勾选状态。"""

    def __init__(self, title: str, on_command, state_provider, icon_path: str | None = None,
                 on_session_end=None):
        self.title = title
        self.on_command = on_command
        self.state_provider = state_provider
        self.icon_path = icon_path
        self.on_session_end = on_session_end  # 关机/注销时抢救数据用
        self.hwnd = None
        self._nid = None
        self._hproc = WNDPROC(self._wnd_proc)
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self.ok = False
        self.error: str | None = None

    # ------------------------------------------------------------ 生命周期
    def start(self, timeout: float = 4.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="km-tray", daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        return self.ok

    def stop(self) -> None:
        if self.hwnd:
            self._delete_icon()
            user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(2.0)

    # ------------------------------------------------------------ 内部
    def _load_icon(self):
        if self.icon_path and os.path.exists(self.icon_path):
            h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        if getattr(sys, "frozen", False):
            large = ctypes.c_void_p()
            small = ctypes.c_void_p()
            if shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(large),
                                      ctypes.byref(small), 1) > 0 and large:
                return large
        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _run(self) -> None:
        try:
            hinst = kernel32.GetModuleHandleW(None)
            cls_name = "KeyMouseMonitorTrayWnd"
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._hproc
            wc.hInstance = hinst
            wc.lpszClassName = cls_name
            if not user32.RegisterClassW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err not in (0, 1410):  # 1410 = 类已注册
                    raise OSError(f"RegisterClassW failed: {err}")
            self.hwnd = user32.CreateWindowExW(
                0, cls_name, "KeyMouseMonitorTray", 0, 0, 0, 0, 0, None, None,
                hinst, None
            )
            if not self.hwnd:
                raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")

            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = self._load_icon()
            nid.szTip = self.title[:127]
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                raise OSError("Shell_NotifyIcon(NIM_ADD) failed")
            self._nid = nid
            self.ok = True
        except Exception as exc:  # 托盘失败不能拖垮程序
            self.error = str(exc)
        finally:
            self._started.set()

        if not self.ok:
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _delete_icon(self) -> None:
        try:
            if self._nid is not None:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        self._nid = None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                low = lparam & 0xFFFF
                if low == WM_RBUTTONUP:
                    self._popup_menu()
                elif low in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.on_command(CMD_SHOW)
                return 0
            if msg == WM_QUERYENDSESSION:
                # 注销/关机：立刻把内存里的增量写盘，避免丢掉最后几秒
                self._session_end(False)
                return 1
            if msg == WM_ENDSESSION:
                self._session_end(bool(wparam))
                return 0
            if msg == WM_DESTROY:
                self._delete_icon()
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _session_end(self, ending: bool) -> None:
        if self.on_session_end is None:
            return
        try:
            self.on_session_end(ending)
        except Exception:
            pass

    def _popup_menu(self) -> None:
        state = {}
        try:
            state = self.state_provider() or {}
        except Exception:
            pass
        menu = user32.CreatePopupMenu()
        visible = state.get("visible", True)
        paused = state.get("paused", False)
        autostart = state.get("autostart", False)

        user32.AppendMenuW(menu, MF_STRING, CMD_SHOW,
                           "隐藏窗口" if visible else "显示窗口")
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if paused else 0), CMD_PAUSE,
                           "继续监控" if paused else "暂停监控")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if autostart else 0),
                           CMD_AUTOSTART, "开机自启动")
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN_DIR, "打开数据文件夹")
        user32.AppendMenuW(menu, MF_STRING, CMD_ASK_CLOSE, "恢复“关闭时询问”")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "退出")

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, self.hwnd, None,
        )
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd:
            self.on_command(int(cmd))

    def notify(self, title: str, text: str) -> None:
        if not self.ok or self._nid is None:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_INFO
        nid.szInfo = text[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = 0x01  # NIIF_INFO
        try:
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass
