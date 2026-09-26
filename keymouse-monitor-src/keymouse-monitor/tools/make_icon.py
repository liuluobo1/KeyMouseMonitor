"""生成 app.ico（构建期工具，需要 Pillow；运行期程序不依赖 Pillow）。"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app.ico")

BG = (18, 20, 27, 255)
CARD = (35, 41, 54, 255)
EDGE = (77, 163, 255, 255)
ACCENT = (77, 163, 255, 255)
DIM = (110, 120, 140, 255)


def render(size: int) -> Image.Image:
    s = 4  # 4x 超采样
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(n * 0.22)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=r, fill=BG, outline=EDGE,
                        width=max(1, int(n * 0.018)))
    # 键盘主体
    kx0, ky0 = n * 0.17, n * 0.30
    kx1, ky1 = n * 0.83, n * 0.70
    d.rounded_rectangle([kx0, ky0, kx1, ky1], radius=int(n * 0.05), fill=CARD,
                        outline=EDGE, width=max(1, int(n * 0.012)))
    # 键位（其中几个高亮成蓝色）
    cols, rows = 5, 3
    gap = n * 0.022
    bw = (kx1 - kx0 - gap * (cols + 1)) / cols
    bh = (ky1 - ky0 - gap * (rows + 1)) / rows
    hot = {(0, 0), (2, 1), (4, 2), (1, 2)}
    for r_ in range(rows):
        for c in range(cols):
            x0 = kx0 + gap + c * (bw + gap)
            y0 = ky0 + gap + r_ * (bh + gap)
            d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh],
                                radius=int(n * 0.012),
                                fill=ACCENT if (c, r_) in hot else DIM)
    # 鼠标（右下角小圆 + 滚轮）
    mx, my = n * 0.70, n * 0.80
    mw, mh = n * 0.22, n * 0.15
    d.rounded_rectangle([mx - mw / 2, my - mh / 2, mx + mw / 2, my + mh / 2],
                        radius=int(mh * 0.48), fill=CARD, outline=ACCENT,
                        width=max(1, int(n * 0.012)))
    d.line([mx, my - mh * 0.34, mx, my - mh * 0.06], fill=ACCENT,
           width=max(1, int(n * 0.02)))
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = render(256)
    big.save(OUT, format="ICO", sizes=[(sz, sz) for sz in sizes])
    with Image.open(OUT) as check:
        got = sorted(check.info.get("sizes", []))
    print(f"已生成 {OUT} ({os.path.getsize(OUT)} bytes), 尺寸: {got}")
    # 顺便输出一张 PNG 便于预览
    png = os.path.join(ROOT, "app_icon_preview.png")
    big.save(png)
    print("预览图:", png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
