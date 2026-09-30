"""键鼠使用统计 —— 核心层（钩子 / 存储 / 统计）。

导入本包时立刻把进程优先级提到 HIGH_PRIORITY_CLASS（激进档）：
低级键鼠钩子的回调由系统在"安装钩子的线程"里调用，进程优先级偏低时
（全屏游戏 / 高负载）会被饿死并丢事件。

设环境变量 KMM_NO_PRIORITY=1 可关闭这次提升（排查问题时用）。
实际生效的档位保存在 core.PRIORITY 里（'high'/'normal'/'off'/'failed'/'unknown'）。
"""

from __future__ import annotations

import os


def _boost_priority() -> str:
    if os.environ.get("KMM_NO_PRIORITY") == "1":
        return "off"
    try:
        from . import sysutil

        return sysutil.set_process_priority("high")
    except Exception:
        return "failed"


PRIORITY = _boost_priority()
