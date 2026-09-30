"""系统集成小工具：数据目录、单实例、唤醒事件、开机自启、DPI。"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import tempfile
import winreg
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# 64 位下句柄必须按指针宽度传递
user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.MessageBoxW.restype = ctypes.c_int
user32.MessageBoxW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                               wintypes.LPCWSTR, wintypes.UINT]
user32.SetProcessDPIAware.restype = wintypes.BOOL
user32.SetProcessDPIAware.argtypes = []
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.SetEvent.argtypes = [ctypes.c_void_p]
kernel32.ResetEvent.restype = wintypes.BOOL
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]

APP_NAME = "KeyMouseMonitor"
APP_TITLE = "键鼠使用统计"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ---------------------------------------------------------------- 架构标识
# 判断位数只看**指针宽度**，最可靠：不看文件名、也不看系统位数
# （32 位包跑在 64 位系统上，这里依然正确返回 32）。
def arch_bits() -> int:
    return ctypes.sizeof(ctypes.c_void_p) * 8


def arch_tag() -> str:
    """状态栏用：x86 / x64。"""
    return "x86" if arch_bits() == 32 else "x64"


def title_text() -> str:
    """界面标题栏文字：32 位那份同时标明是 Win7 兼容版。"""
    if arch_bits() == 32:
        return f"{APP_TITLE} · 32位 (Win7兼容版)"
    return f"{APP_TITLE} · 64位"


ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000

_MUTEX_NAME = "Local\\KeyMouseMonitor_SingleInstance_v1"
_EVENT_NAME = "Local\\KeyMouseMonitor_Wake_v1"
_QUIT_EVENT_NAME = "Local\\KeyMouseMonitor_Quit_v1"

_mutex_handle = None


# ---------------------------------------------------------------- 路径
def resource_path(name: str) -> str:
    """打包后从 _MEIPASS 取资源，开发时取脚本同级目录。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    if not getattr(sys, "_MEIPASS", None):
        base = os.path.dirname(base)  # core/ -> 项目根
    return os.path.join(base, name)


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def exe_path() -> str:
    return os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else ""


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def resolve_data_dir(preferred: str = r"F:\KeyMouseMonitor") -> tuple[str, str | None]:
    """返回 (数据目录, 回退说明或 None)。优先 F 盘，不可用则回退到 %APPDATA%。"""
    if _writable(preferred):
        return preferred, None
    fallback = os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME
    )
    _writable(fallback)
    return fallback, f"{preferred} 不可写，已自动回退到 {fallback}"


# ---------------------------------------------------------------- 单实例
def acquire_single_instance() -> bool:
    """True = 本进程是唯一实例；False = 已有实例在运行。"""
    global _mutex_handle
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def _open_wake_event(name: str = _EVENT_NAME):
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                      wintypes.BOOL, wintypes.LPCWSTR]
    return kernel32.CreateEventW(None, True, False, name)


def signal_existing_instance() -> None:
    """让已在运行的实例把窗口显示出来。"""
    ev = _open_wake_event()
    if ev:
        kernel32.SetEvent(ev)


def signal_existing_instance_quit() -> None:
    """让已在运行的实例优雅退出（先落库再关闭）。"""
    ev = _open_wake_event(_QUIT_EVENT_NAME)
    if ev:
        kernel32.SetEvent(ev)


def instance_running() -> bool:
    """是否已有实例在运行（只查询，不创建）。

    必须用 OpenMutexW，不能用 CreateMutexW：CreateMutexW 会把互斥体在本进程里
    **真的创建出来**，于是同一个进程紧接着调用 acquire_single_instance() 就会读到
    ERROR_ALREADY_EXISTS，把自己误判成"已有实例"而直接退出——表现为双击后程序
    静默不启动。
    """
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, _MUTEX_NAME)
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


class InstanceSignals:
    """监听"唤起窗口"与"优雅退出"两个跨进程事件。"""

    def __init__(self, on_wake, on_quit, interval: float = 0.4):
        self._wake = _open_wake_event()
        self._quit = _open_wake_event(_QUIT_EVENT_NAME)
        self._on_wake = on_wake
        self._on_quit = on_quit
        self._interval = interval
        self._stop = False
        import threading

        self._t = threading.Thread(target=self._loop, name="km-signals", daemon=True)

    def start(self) -> None:
        if self._wake or self._quit:
            self._t.start()

    def _loop(self) -> None:
        import time
        import traceback

        while not self._stop:
            if self._quit and kernel32.WaitForSingleObject(self._quit, 0) == 0:
                kernel32.ResetEvent(self._quit)
                try:
                    self._on_quit()
                except Exception:
                    # 事件已经清掉，这里再吞异常就等于把退出请求丢了；
                    # 一定要留下痕迹（曾经因为静默吞掉 NameError 导致 --quit 永远无效）
                    try:
                        sys.stderr.write(traceback.format_exc())
                        sys.stderr.flush()
                    except Exception:
                        pass
            if self._wake and kernel32.WaitForSingleObject(self._wake, 0) == 0:
                kernel32.ResetEvent(self._wake)
                try:
                    self._on_wake()
                except Exception:
                    try:
                        sys.stderr.write(traceback.format_exc())
                        sys.stderr.flush()
                    except Exception:
                        pass
            time.sleep(self._interval)

    def stop(self) -> None:
        self._stop = True


# 兼容旧名字
WakeWatcher = InstanceSignals


# ---------------------------------------------------------------- 权限
shell32.IsUserAnAdmin.restype = wintypes.BOOL
shell32.ShellExecuteW.restype = ctypes.c_void_p
shell32.ShellExecuteW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, ctypes.c_int]
SW_SHOWNORMAL = 1


def is_admin() -> bool:
    """当前进程是否以管理员（已提升）权限运行。

    为什么需要：Windows 的 UIPI 限制下，**非管理员进程的全局低级钩子收不到
    以管理员运行的窗口的输入**（和 AutoHotkey 不提权就管不到管理员窗口同理）。
    所以玩游戏（游戏是管理员启动）时会完全收不到按键。
    """
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(argv: list[str] | None = None) -> bool:
    """以管理员身份重新启动自己。

    返回 True = 用户同意 UAC、新进程已拉起，调用方**应立刻退出**；
    返回 False = 用户点了"否"或 UAC 弹不出来，调用方继续以普通权限运行。
    """
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        # 带上内部标记：万一提权后权限检测仍为 False，也只会再申请一次，不会死循环
        if "--elevated" not in args and "--no-elevate" not in args:
            args.append("--elevated")
        if getattr(sys, "frozen", False):
            exe = os.path.abspath(sys.executable)
            params = subprocess.list2cmdline(args)
        else:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            exe = pyw if os.path.exists(pyw) else sys.executable
            params = subprocess.list2cmdline([os.path.join(app_dir(), "main.py")] + args)
        rc = shell32.ShellExecuteW(None, "runas", exe, params, app_dir(), SW_SHOWNORMAL)
        # ShellExecuteW 返回值 > 32 才算成功（<=32 是错误码，含用户取消 UAC）
        return int(rc or 0) > 32
    except Exception:
        return False


# ---------------------------------------------------------------- 进程优先级
PRIORITY_CLASSES = {
    "high": 0x00000080,      # HIGH_PRIORITY_CLASS（激进）
    "above": 0x00008000,     # ABOVE_NORMAL_PRIORITY_CLASS
    "normal": 0x00000020,    # NORMAL_PRIORITY_CLASS
}
_PRIORITY_NAMES = {
    0x00000040: "idle", 0x00004000: "below", 0x00000020: "normal",
    0x00008000: "above", 0x00000080: "high", 0x00000100: "realtime",
    0x00000100 | 0x00000080: "high",
}


def set_process_priority(level: str = "high") -> str:
    """设置本进程优先级类并**回读确认**，返回实际生效的档位名。

    采集靠全局低级钩子：回调由系统在"安装钩子的线程"里调用，进程优先级太低时
    （全屏游戏 / 高 CPU 占用）钩子会被饿死并丢事件，所以这里提到 HIGH。
    设置失败不抛异常，返回 "unknown"，由调用方决定是否提示。
    """
    want = PRIORITY_CLASSES.get(str(level).lower(), PRIORITY_CLASSES["high"])
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.SetPriorityClass.restype = ctypes.c_int
        k32.GetPriorityClass.restype = ctypes.c_uint
        k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        handle = k32.GetCurrentProcess()
        k32.SetPriorityClass(handle, want)
        return _PRIORITY_NAMES.get(int(k32.GetPriorityClass(handle)), "unknown")
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- 自启动
TASK_NAME = APP_NAME
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def autostart_command() -> str:
    """当前应注册到自启项的命令行。"""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    script = os.path.join(app_dir(), "main.py")
    return f'"{exe}" "{script}"'


def get_autostart() -> str | None:
    """旧的 HKCU\\...\\Run 自启项（普通权限启动）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return value
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _delete_run_value() -> None:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    except OSError:
        pass


def _run_hidden(args: list[str]) -> subprocess.CompletedProcess:
    """跑外部命令且不弹控制台窗口。

    注意不要用 text=True / encoding='utf-8'：schtasks 的输出是 OEM/ANSI 编码
    （中文系统为 GBK），在 `-X utf8` 模式下会直接抛 UnicodeDecodeError。
    所以这里收字节，再自己安全解码。

    另外必须加 timeout：这个函数会在启动路径上被调用，schtasks 万一卡住
    不能把整个程序一起拖死。
    """
    return subprocess.run(args, capture_output=True, timeout=8,
                          creationflags=CREATE_NO_WINDOW)


def _out_text(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        return data.decode("mbcs")
    except Exception:
        return data.decode("utf-8", errors="replace")


def _task_exists(name: str) -> bool:
    """指定名字的计划任务是否存在（schtasks 查询）。"""
    try:
        return _run_hidden(["schtasks", "/Query", "/TN", name]).returncode == 0
    except Exception:
        return False


def autostart_task_exists() -> bool:
    """是否已注册"登录时 + 最高权限"的计划任务。"""
    return _task_exists(TASK_NAME)


def autostart_kind() -> str:
    """'task' = 管理员计划任务；'run' = 旧的 Run 键（普通权限）；'off' = 未开启。

    注意：这个函数会调用 schtasks（起进程），不要在每秒刷新里调用。
    """
    try:
        if autostart_task_exists():
            return "task"
    except Exception:
        pass
    return "run" if get_autostart() else "off"


def _task_parts() -> tuple[str, str]:
    """(程序路径, 参数) —— 计划任务里 Command 与 Arguments 是**两个独立字段**。

    不要把路径用引号包起来塞进 Command：schtasks /TR 会把引号原样写进
    <Command>，Task Scheduler 按字面路径去找，结果任务"创建成功、上次结果 0"，
    但实际上**进程根本没起来**（开机自启静默失效）。
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), ""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return exe, f'"{os.path.join(app_dir(), "main.py")}"'


def _task_xml(command: str, arguments: str,
              run_level: str = "HighestAvailable") -> str:
    user = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    user = user.strip("\\")

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>KeyMouseMonitor 开机自启（以管理员权限运行，不弹 UAC）</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{esc(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{esc(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{run_level}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(command)}</Command>
      <Arguments>{esc(arguments)}</Arguments>
      <WorkingDirectory>{esc(app_dir())}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def create_autostart_task(extra_args: str = "", run_level: str = "HighestAvailable",
                          name: str = TASK_NAME) -> None:
    """用任务 XML 建/更新计划任务（Command 与 Arguments 分开写，绝不把引号写进路径）。"""
    command, arguments = _task_parts()
    if extra_args:
        arguments = (arguments + " " + extra_args).strip()
    xml = _task_xml(command, arguments, run_level)
    path = os.path.join(tempfile.gettempdir(), f"kmm_task_{os.getpid()}.xml")
    with open(path, "w", encoding="utf-16") as fh:
        fh.write(xml)
    try:
        r = _run_hidden(["schtasks", "/Create", "/TN", name, "/XML", path, "/F"])
        if r.returncode != 0:
            msg = (_out_text(r.stderr) or _out_text(r.stdout)
                   or "schtasks 创建计划任务失败").strip()
            raise RuntimeError(msg.splitlines()[-1][:200] if msg else "schtasks 失败")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def autostart_task_target(name: str = TASK_NAME) -> tuple[str, str] | None:
    """计划任务当前配置的 (Command, Arguments)；没有任务返回 None。"""
    try:
        r = _run_hidden(["schtasks", "/Query", "/TN", name, "/XML"])
        if r.returncode != 0:
            return None
        text = _out_text(r.stdout)

        def grab(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
            return m.group(1).strip() if m else ""

        cmd = grab("Command")
        return (cmd, grab("Arguments")) if cmd else None
    except Exception:
        return None


def delete_autostart_task(name: str = TASK_NAME) -> None:
    """删除计划任务，删完必须**回查确认**；仍然存在就抛错（绝不静默失败）。

    背景：任务是 RunLevel=HighestAvailable（最高权限）注册的，删除这种任务需要
    管理员权限。普通权限下 schtasks 会返回"拒绝访问"，旧代码把返回码和异常都吞掉，
    于是界面重新查询发现任务还在、按钮状态不变 —— 用户看到的就是"点了没反应"。
    """
    if not _task_exists(name):
        return
    last = ""
    for tn in (name, "\\" + name):
        try:
            r = _run_hidden(["schtasks", "/Delete", "/TN", tn, "/F"])
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            continue
        msg = (_out_text(r.stderr) or _out_text(r.stdout) or "").strip()
        if r.returncode == 0 and not _task_exists(name):
            return
        last = (msg.splitlines() or [f"schtasks 返回 {r.returncode}"])[-1][:160]
    # 删不掉时至少禁用它，避免开机仍然自启（状态栏会提示失败原因）
    try:
        _run_hidden(["schtasks", "/Change", "/TN", name, "/DISABLE"])
    except Exception:
        pass
    if not _task_exists(name):
        return
    raise RuntimeError(
        f"计划任务 {name} 删除失败：{last}"
        f"（最高权限任务需要管理员权限；已尝试禁用其触发器）"
    )


def run_autostart_off_elevated() -> bool:
    """以管理员身份再跑一次 `--autostart off`（调用方需自行等待并回查状态）。

    Returns True = 用户同意 UAC 且新进程已拉起。
    """
    try:
        args = ["--autostart", "off", "--elevated", "--no-elevate"]
        if getattr(sys, "frozen", False):
            exe = os.path.abspath(sys.executable)
            params = subprocess.list2cmdline(args)
        else:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            exe = pyw if os.path.exists(pyw) else sys.executable
            params = subprocess.list2cmdline(
                [os.path.join(app_dir(), "main.py")] + args)
        rc = shell32.ShellExecuteW(None, "runas", exe, params, app_dir(),
                                   SW_SHOWNORMAL)
        return int(rc or 0) > 32
    except Exception:
        return False


def set_autostart(enabled: bool) -> None:
    """开关开机自启。

    开启时用「登录时触发 + 使用最高权限」的计划任务：开机即管理员权限，
    而且**不弹 UAC**（Run 键做不到这一点，开机只会以普通权限启动）。
    同时清掉旧的 Run 项，否则它可能先以普通权限启动、抢占单实例。

    关闭时：删任务 + 回查确认，失败会抛 RuntimeError（不再静默失败）。
    """
    if enabled:
        create_autostart_task()
        _delete_run_value()
    else:
        delete_autostart_task()
        _delete_run_value()


def autostart_enabled() -> bool:
    return autostart_kind() != "off"


def _run_value_is_ours(run: str) -> bool:
    if getattr(sys, "frozen", False):
        target = os.path.abspath(sys.executable)
    else:
        target = os.path.join(app_dir(), "main.py")
    return os.path.normcase(target) in os.path.normcase(run)


def migrate_autostart_to_task() -> str | None:
    """让开机自启始终是「指向当前程序、且格式正确」的最高权限计划任务。

    处理两种历史问题，返回说明文本或 None：
      1) 旧版把自启写在 HKCU\\Run（开机只有普通权限）-> 升级成计划任务并删掉 Run 项
      2) 计划任务已存在但要运行的命令不对（换了目录/版本；或早期版本用
         schtasks /TR 建的任务，路径被多加了引号，**开机其实起不来**）-> 按当前路径重建
    """
    want = _task_parts()
    run = get_autostart()
    if run and _run_value_is_ours(run):
        _delete_run_value()          # 旧 Run 项一律清掉，避免它抢单实例
        if not autostart_task_exists():
            try:
                create_autostart_task()
            except Exception as exc:
                return f"开机自启升级失败（仍是普通权限）：{exc}"
            return "开机自启已升级为管理员计划任务（登录静默启动，不弹 UAC）"
    if autostart_task_exists():
        have = autostart_task_target()
        if have is not None and have != want:
            try:
                create_autostart_task()
            except Exception as exc:
                return f"开机自启任务修正失败：{exc}"
            return f"开机自启任务已修正为当前程序：{want[0]}"
    return None


# ---------------------------------------------------------------- DPI / 窗口
def enable_dpi_awareness() -> None:
    try:
        # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi() -> int:
    try:
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        dc = user32.GetDC(None)
        if not dc:
            return 96
        dpi = gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        user32.ReleaseDC(None, dc)
        return int(dpi) or 96
    except Exception:
        return 96


def show_console_warning(msg: str) -> None:
    try:
        user32.MessageBoxW(None, msg, APP_TITLE, 0x40)
    except Exception:
        pass
