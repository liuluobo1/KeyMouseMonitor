# KeyMouseMonitor
<img width="1425" height="700" alt="image" src="https://github.com/user-attachments/assets/c28f432e-2a2a-4db3-b39f-fcb2b5a34bb5" />
效果如图
# 键鼠使用统计 (KeyMouseMonitor)

一个常驻 Windows 托盘的键鼠使用统计工具：全局统计每一次按键、鼠标点击与鼠标移动距离，
并累计每个键**按住不放的时长**，用 104 键热力图展示，鼠标悬停到任意键位即可看到
**总次数 / 近七日 / 今日** 以及对应的 **按住总时长 / 按住近七日 / 按住今日**。

* 全局监听：`WH_KEYBOARD_LL` + `WH_MOUSE_LL` 低级钩子（ctypes 直接调用，**无需管理员权限、无驱动、无第三方库**）
* 只统计次数与时长：**不记录、不保存你输入的任何文本内容**
* 数据永久保留：按天明细 + 累计总数，存于 SQLite
* 开机自启：一键写入 `HKCU\...\Run`，可随时取消
* 单文件 exe，无控制台窗口，点 `✕` 会询问"直接退出"还是"最小化到系统托盘后台继续运行"

---

## 一、快速开始

1. 双击 `KeyMouseMonitor.exe`：**会弹出 UAC 申请管理员权限，请点"是"**（不加管理员会收不到管理员程序/游戏的
   输入，详见第六节）；首次运行 Windows 可能还会弹 SmartScreen 提示，选择"更多信息 → 仍要运行"
2. 程序出现在屏幕右上角并常驻托盘；鼠标移到任意键位上即可查看该键统计
3. 在界面右上角勾选 **开机自启**，会注册一个「登录时触发 + 使用最高权限」的计划任务：
   开机自动以管理员启动且**不弹 UAC**（也可命令行执行 `KeyMouseMonitor.exe --autostart on`）。
   旧版写在注册表 `HKCU\...\Run` 里的自启项，新版首次以管理员运行时会**自动升级**成该计划任务
   （因为 Run 键只能以普通权限启动，正是"收不到游戏输入"的原因）
4. 关闭窗口（`✕`）会弹出询问框：**直接退出程序** 或 **最小化到系统托盘（后台继续统计）**；
   勾选"不再询问"可记住本次选择，之后点 `✕` 直接按该选择执行（托盘右键菜单 → 恢复"关闭时询问" 可改回每次询问）

## 二、界面说明

| 区域 | 说明 |
| --- | --- |
| 顶部标题栏 | 可拖动窗口；`暂停/继续`、`置顶`、`开机自启`、`数据文件夹`、`—`（最小化到托盘）、`✕`（询问：退出 / 最小化到托盘后台运行） |
| 详情面板 | 悬停键位的中文名/代号 + **总次数 / 近七日（含今日）/ 今日**，每格下方同时显示 **按住时长**（同样三个口径）+ 近 7 日柱状趋势 |
| 键位热力图 | 完整 104 键 ANSI 布局（F 区、修饰键左右区分、方向键、小键盘）；今日次数越多底色越蓝 |
| 鼠标面板 | 左键 / 右键 / 中键 / 侧键1 / 侧键2 / 滚轮上·下·左·右，同样支持悬停查看（左右中侧键也有按住时长） |
| 右下角 ◢ | 拖动可调整窗口大小；窗口位置与尺寸会被记住 |
| 状态栏 | 钩子状态、托盘状态、钩子自愈重装次数、最近落库时间、写盘错误数、数据库文件名与大小 |

悬停时鼠标旁还会弹出跟随光标的小气泡，同样显示次数与按住时长这两组数字。

## 三、数据存放

* 默认目录：`F:\KeyMouseMonitor\`（若 F 盘不可用，自动回退到 `%APPDATA%\KeyMouseMonitor\`，界面顶部会显示黄色提示条）
* 数据库：`stats.db`（SQLite，**永久保留，不自动清理历史**）
* 配置：`config.json`（窗口位置/大小/置顶状态）

表结构：

| 表 | 内容 |
| --- | --- |
| `key_day(day, key, n)` | 每个键位每天的次数 |
| `key_total(key, n)` | 每个键位的累计总次数 |
| `move_day(day, px)` | 每天鼠标移动像素距离 |
| `dur_day(day, key, ms)` | 每个键位每天被按住的毫秒数 |
| `dur_total(key, ms)` | 每个键位累计被按住的毫秒数 |
| `session(id, started, ended, keys, clicks, px)` | 每次运行的会话记录 |
| `meta(k, v)` | 首次运行时间、累计移动距离等 |

键位 id 采用 `KeyboardEvent.code` 风格（`A`、`Digit1`→`1`、`LShift`/`RShift` 左右区分、`Num0` 小键盘、
`MouseLeft`、`WheelUp` 等），与键盘布局无关，长期统计不会错位。

> 提示：数据库使用 WAL 模式，可直接用任意 SQLite 工具只读打开查看，不影响程序运行。

## 四、命令行参数

```
KeyMouseMonitor.exe                 正常启动（界面 + 托盘 + 全局监听）
KeyMouseMonitor.exe --no-ui         无界面后台运行（调试用，Ctrl+C 退出）
KeyMouseMonitor.exe --no-tray       不启用托盘图标
KeyMouseMonitor.exe --dump --out x.json   只读导出统计数据为 JSON
KeyMouseMonitor.exe --data-dir D:\X   指定数据目录
KeyMouseMonitor.exe --autostart on|off|status   开机自启开关 / 查询
KeyMouseMonitor.exe --quit          让正在运行的实例优雅退出（先落库再关闭）
KeyMouseMonitor.exe --no-elevate    启动时不要申请管理员权限（默认会提权）
KeyMouseMonitor.exe --selftest      运行内置自检
```

## 五、从源码运行 / 构建

```powershell
# 运行（开发）
python main.py

# 自检（键位映射 / 布局 / 存储 / 统计口径）
python -X utf8 main.py --selftest

# 端到端验证：启动程序 -> SendInput 合成键鼠输入 -> 核对落库
python -X utf8 tools/e2e.py
python -X utf8 tools/e2e.py --exe dist\KeyMouseMonitor.exe   # 验证打包后的 exe

# UI 断言 + 截图（布局/热力/悬停气泡/详情面板/趋势图/缩放/暂停/托盘/关闭询问）
python -X utf8 tools/ui_check.py

# 打包 exe 的关闭流程实测：点 ✕ -> 询问框 -> 回车最小化到托盘 -> 唤回 -> --quit
python -X utf8 tools/close_dialog_check.py --exe dist\KeyMouseMonitor.exe

# 退出 -> 重启后数据恢复实测（逐键/逐日/移动距离/按住时长 + 界面显示）
python -X utf8 tools/restore_check.py --exe dist\KeyMouseMonitor.exe

# 单独诊断：钩子是否收到输入 / 悬停为何没命中
python -X utf8 tools/hook_probe.py
python -X utf8 tools/hover_probe.py

# 打包
python -m pip install pyinstaller pillow
pwsh -File tools/build.ps1        # 或见 README 末尾的手动命令
```

目录结构：

```
core/keymap.py     键位映射表 + 104 键物理布局
core/hooks.py      WH_KEYBOARD_LL / WH_MOUSE_LL 钩子引擎（含看门狗自愈）
core/store.py      SQLite 持久层
core/counters.py   内存统计聚合 + 定时落库线程
core/tray.py       托盘图标与右键菜单（纯 ctypes）
core/sysutil.py    数据目录、单实例、唤醒事件、开机自启、DPI
ui/app.py          tkinter 主界面
ui/theme.py        配色与格式化
tools/             构建与验证脚本（不参与打包）
```

## 六、实现要点与已知限制

* **钩子自愈**：低级钩子若回调超时会被系统静默摘除，引擎每 15 秒重装一次钩子（仅在新钩子创建成功时替换），
  状态栏显示重装次数，长期运行不会"悄悄失效"。
* **必须以管理员身份运行**（默认启动时会自动申请）：Windows 的 UIPI 限制下，**非管理员进程的全局低级钩子
  收不到"以管理员运行的窗口"的输入**。很多游戏（含 Java 版 MC，若启动器以管理员运行）就是管理员进程，
  不开管理员时会出现"游戏里一直按住 W 却完全没有记录"，而状态栏仍显示"钩子正常"。
  状态栏的「权限 管理员 / 权限 普通⚠」就是用来一眼看出这件事的。开机自启用的是「最高权限计划任务」，
  开机即管理员且**不弹 UAC**。
* **计数口径**：只统计**真正按下**的次数。按住不放时 Windows 会以约 30 次/秒合成"按键重复"，
  低级钩子也收得到这些重复事件，但**它们不再计入次数**（只用来维持按住时长）；否则按住 10 秒
  就会变成 286 次。滚轮按格计数（每 120 为 1 格），鼠标左/右/中/侧键每次按下计 1 次。
* **按住时长口径**：从**真正按下**（含自动重复的第一次）计到抬起，重复的 `KEYDOWN` 不会重算起点，
  所以"按住 A 两秒"只记 2 秒、不会因为按键重复被截断或累加。键盘按键与鼠标左/右/中/侧键都统计；
  滚轮没有"按住"语义，不产生时长。一次按住若超过 30 分钟（例如抬键事件被其他程序吞掉），
  该次按住的时长会被丢弃，避免出现几小时的异常值。
* **抬键兜底**：万一抬键事件丢了（切窗口、全屏游戏抢焦点、钩子重装的一瞬间），引擎每 0.5 秒用
  `GetAsyncKeyState` 核对一次"物理上是不是真的还按着"，把已经松开却没收到抬键的键结算掉。
  否则那个键会永远卡在"按住"状态，**之后再也不会计数**。
* **历史数据口径**：本次修改之前，库里已有的次数是"含自动重复"的口径，无法回溯区分，
  因此**旧数据原样保留**；从现在起次数才等于真实的按下次数（同一段时间里次数会明显变小，
  这是正常的，不是漏记）。
* **历史数据**：`dur_day`/`dur_total` 是后加的表，升级后旧库会自动建表并**从本次运行开始**累计时长，
  之前的按键没有时长数据（次数不受影响）。
* **也统计合成输入**：被其他程序（含测试脚本）用 SendInput 合成的按键同样计数。
* **跨天**：以本机自然日划分；极端情况下跨零点前后数秒内的按键可能计入前一天。
* **鼠标移动距离**：按光标位移的欧氏距离累计，并换算为米/公里展示（按 96 DPI 估算，仅作参考量级）。
* **杀软/系统警告**：PyInstaller 单文件 exe 未做数字签名，可能被 SmartScreen 或个别杀软拦一次；
  源码完全公开在本目录，可自行用 `tools/build.ps1` 重新打包。
* **多用户/远程桌面**：钩子是"当前登录会话"级别，切换用户或 RDP 会话时各自独立统计。
* 首次运行若提示钩子安装失败，通常是被安全软件拦截了全局钩子，请放行本程序。

## 七、手动打包命令

```powershell
python -X utf8 tools/make_icon.py
python -X utf8 -m PyInstaller --noconfirm --clean --onefile --noconsole `
  --name KeyMouseMonitor --icon app.ico --add-data "app.ico;." `
  --distpath dist --workpath build --specpath build main.py
```

产物：`dist\KeyMouseMonitor.exe`
（纯Deepseek写的，我也不知道是啥）
