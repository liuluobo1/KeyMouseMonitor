"""验证自启"删除 + 回查"逻辑：用**临时任务名**跑，不碰你真实的开机自启项。

用法:
  python -X utf8 tools/autostart_check.py          (64 位 Python 3.14)
  py -3.8-32 tools/autostart_check.py             (32 位 Python 3.8，和 win7 版同环境)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sysutil  # noqa: E402

TMP = "KMM_selftest_del"


def main() -> int:
    fails = []
    print(f"Python {sys.version.split()[0]} ({8 * 4 if sys.maxsize > 2**32 else 4 * 8}"
          f"{'64' if sys.maxsize > 2**32 else '32'} 位)")
    print("is_admin:", sysutil.is_admin())
    print("真实自启状态:", sysutil.autostart_kind())

    # 1) 建一个临时任务（普通权限即可建 LeastPrivilege 任务）
    try:
        sysutil.create_autostart_task(run_level="LeastPrivilege", name=TMP)
    except Exception as exc:
        print(f"[SKIP] 无法创建临时任务（{exc}）→ 跳过删除逻辑实测")
        return 0
    if not sysutil._task_exists(TMP):
        print("[FAIL] 临时任务创建后查询不到")
        return 1
    print("临时任务已创建:", TMP)

    # 2) 用新逻辑删除，必须真的删掉
    try:
        sysutil.delete_autostart_task(TMP)
    except Exception as exc:
        fails.append(f"delete_autostart_task 抛错: {exc}")
    if sysutil._task_exists(TMP):
        fails.append("删除后任务仍然存在")
        # 兜底清理，别在系统里留垃圾
        sysutil._run_hidden(["schtasks", "/Delete", "/TN", TMP, "/F"])
    else:
        print("删除 + 回查通过：任务已不存在")

    # 3) 幂等：再删一次不应报错
    try:
        sysutil.delete_autostart_task(TMP)
        print("重复删除幂等通过")
    except Exception as exc:
        fails.append(f"重复删除不应报错: {exc}")

    if fails:
        for f in fails:
            print("  [x]", f)
        return 1
    print("[PASS] 自启删除逻辑（建→删→回查→幂等）全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
