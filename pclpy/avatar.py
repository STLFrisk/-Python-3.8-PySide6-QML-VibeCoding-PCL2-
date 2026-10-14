"""像素风玩家头像: 用 QPainter 画一个 Steve/Alex 头像, 不需要皮肤文件。

不同玩家名会得到略微不同的配色(头发/皮肤色相偏移), 便于区分账号。
"""
from __future__ import annotations

import colorsys
import hashlib
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

# 8x8 的 Steve 脸部色块图: H=头发 S=皮肤 E=眼白 I=瞳孔 B=胡须/嘴 N=鼻子
_FACE = [
    "HHHHHHHH",
    "HHHHHHHH",
    "HHHHHHHH",
    "SSSSSSSS",
    "SIIssIIS",
    "SSSSSSSS",
    "SSBBBBSS",
    "SSSBBSSS",
]
_ALEX_FACE = [
    "HHHHHHHH",
    "HHHHHHHH",
    "HSSSSSSH",
    "SSSSSSSS",
    "SIIssIIS",
    "SSSSSSSS",
    "SSBBBBSS",
    "SSSSSSSS",
]

_BASE = {
    "H": (58, 40, 26),      # 头发(深棕)
    "S": (188, 143, 106),   # 皮肤
    "E": (245, 245, 245),   # 眼白
    "I": (86, 74, 160),     # 瞳孔(紫蓝)
    "B": (108, 76, 52),     # 胡须/嘴
    "N": (160, 120, 88),
    "s": (150, 108, 80),    # 眼眶阴影
}


def _shift(rgb: Tuple[int, int, int], seed: int, slot: int) -> QColor:
    """根据玩家名对颜色做一点点色相/明度扰动。"""
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    delta = ((seed >> (slot * 3)) & 0x7) / 100.0 - 0.035
    h = (h + delta) % 1.0
    s = min(1.0, max(0.0, s + delta * 0.5))
    v = min(1.0, max(0.0, v + delta * 0.4))
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return QColor(int(r2 * 255), int(g2 * 255), int(b2 * 255))


def face_grid(model: str = "steve") -> List[str]:
    return _ALEX_FACE if str(model).lower().startswith("alex") else _FACE


def avatar_image(name: str, size: int = 64, model: str = "steve") -> QImage:
    """生成一张 ``size x size`` 的头像。"""
    name = name or "Steve"
    seed = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
    grid = face_grid(model)

    small = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    small.fill(Qt.transparent)
    colors = {k: _shift(v, seed, i) for i, (k, v) in enumerate(sorted(_BASE.items()))}
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            small.setPixelColor(x, y, colors.get(ch, colors["S"]))

    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    p.drawImage(0, 0, small.scaled(size, size, Qt.IgnoreAspectRatio, Qt.FastTransformation))
    p.end()
    return img
