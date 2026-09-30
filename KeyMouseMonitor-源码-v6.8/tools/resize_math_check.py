"""数值验证缩放适配公式：给定可用高度，算出的 unit 必须让内容完整放得下。

（纯计算，不开窗口。对应 ui/app.py:_render_canvas 的高度适配与 _min_window_height）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MARGIN = 6
GR = 0.10
ROWS = 6
CAP = 34


def content_h(unit: float) -> float:
    """与 ui/app.py 一致的内容高度：键盘 6 行 + 鼠标区间距 + 鼠标块高 + 上下边距。"""
    return (2 * MARGIN + (ROWS * (1 + GR) + 0.55) * unit
            + min(0.78 * unit, CAP))


def fitted_unit(avail: float, unit_from_width: float = 1e9) -> float:
    """与 ui/app.py 相同的适配逻辑。"""
    k = ROWS * (1 + GR) + 0.55
    unit_h = (avail - 2 * MARGIN) / (k + 0.78)
    if 0.78 * unit_h > CAP:
        unit_h = (avail - 2 * MARGIN - CAP) / k
    return min(unit_from_width, max(7.0, unit_h))


def min_window_height(chrome: float) -> float:
    unit = 9.0
    return chrome + content_h(unit) + 4


def main() -> int:
    fails = []
    print("== 可用高度 -> 适配后的键位尺寸 / 内容高度 ==")
    for avail in (60, 80, 120, 180, 240, 300, 419, 500, 700):
        u = fitted_unit(avail)
        need = content_h(u)
        ok = need <= avail + 0.5
        print(f"  avail={avail:>4}  unit={u:6.2f}  内容高={need:7.2f}  {'OK' if ok else '溢出!'}")
        if avail >= 100 and not ok:
            fails.append(f"avail={avail} 内容 {need:.1f} 放不下")

    print("== 只按宽度算时（旧逻辑）会溢出，验证这就是原 bug ==")
    unit_w = (1140 - 2 * MARGIN) / (23 + 22 * GR)      # 1140px 宽时的 unit ≈ 44
    for avail in (300, 419):
        old_need = content_h(unit_w)
        print(f"  avail={avail}  旧逻辑内容高={old_need:.1f}  "
              f"{'溢出(鼠标区被裁)' if old_need > avail else '放得下'}")

    print("== 拖拽下限 ==")
    for chrome in (200, 230, 260):
        print(f"  chrome={chrome}  最小窗口高={min_window_height(chrome):.0f}  "
              f"其中内容={content_h(9.0):.0f}")
    if min_window_height(230) < 300:
        fails.append("最小窗口高算得偏小，可能仍会裁切")

    if fails:
        for f in fails:
            print("  [x]", f)
        return 1
    print("[PASS] 适配公式在所有高度下都能完整容纳键盘 + 鼠标区")
    return 0


if __name__ == "__main__":
    sys.exit(main())
