"""矢量图标: 全部用 QPainter 现场绘制, 不依赖任何图片资源。

用法:
    icon("play", "#FFFFFF", 16)      -> QIcon
    pixmap("cube_grass", size=32)    -> QPixmap
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

from . import theme

BOX = 24.0  # 所有图标都在 24x24 的逻辑格子里绘制

CUBE_PALETTES = {
    "grass": ("#6FA84A", "#7B5231", "#94663C"),
    "sand": ("#E4D8B8", "#C9B78C", "#DCCBA4"),
    "orange": ("#E08A3C", "#B05F1F", "#CE7530"),
    "gray": ("#9AA3AE", "#6E7681", "#858D99"),
    "diamond": ("#7FD4E8", "#3E9CB8", "#5FBDD4"),
    "red": ("#C4553F", "#8E3626", "#A8452F"),
}
DEFAULT_CUBE = ("#6FA84A", "#7B5231", "#94663C")

_cache: Dict[Tuple[str, str, int], QPixmap] = {}


# --------------------------------------------------------------- 基础工具
def _pen(color, width=2.0, cap=Qt.RoundCap, join=Qt.RoundJoin) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(join)
    return pen


def _line(p: QPainter, x1, y1, x2, y2) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(*points) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _rounded(p: QPainter, x, y, w, h, r, color) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _arrow_head(p: QPainter, cx, cy, size, color) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawPolygon(_poly((cx - size, cy - size * 0.6), (cx + size, cy - size * 0.6),
                        (cx, cy + size * 0.9)))


# --------------------------------------------------------------- 各图标绘制
def _draw(p: QPainter, name: str, color: str) -> None:
    c = color
    if name == "play":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.drawPolygon(_poly((7.5, 4.5), (19, 12), (7.5, 19.5)))

    elif name == "download":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.drawPolygon(_poly((11, 3), (13, 3), (13, 11), (16.6, 11), (12, 16.4),
                            (7.4, 11), (11, 11)))
        _rounded(p, 4.5, 18.6, 15, 2.4, 1.2, c)

    elif name == "gear":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.save()
        p.translate(12, 12)
        for i in range(8):
            p.save()
            p.rotate(i * 45)
            p.drawRoundedRect(QRectF(-1.7, -10.2, 3.4, 5.0), 1.2, 1.2)
            p.restore()
        p.drawEllipse(QPointF(0, 0), 7.0, 7.0)
        p.restore()
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setBrush(QBrush(Qt.black))
        p.drawEllipse(QPointF(12, 12), 3.0, 3.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    elif name == "grid":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        for x, y in ((3.4, 3.4), (13.2, 3.4), (3.4, 13.2), (13.2, 13.2)):
            p.drawRoundedRect(QRectF(x, y, 7.4, 7.4), 1.6, 1.6)

    elif name in ("back", "next"):
        p.setPen(_pen(c, 2.2))
        p.setBrush(Qt.NoBrush)
        direction = -1 if name == "back" else 1
        _line(p, 12 + 2.5 * direction, 5.5, 12 - 3.5 * direction, 12)
        _line(p, 12 - 3.5 * direction, 12, 12 + 2.5 * direction, 18.5)

    elif name == "chevron_down":
        p.setPen(_pen(c, 2.0))
        _line(p, 6.5, 9.5, 12, 15)
        _line(p, 12, 15, 17.5, 9.5)

    elif name == "chevron_up":
        p.setPen(_pen(c, 2.0))
        _line(p, 6.5, 14.5, 12, 9)
        _line(p, 12, 9, 17.5, 14.5)

    elif name == "chevron_right":
        p.setPen(_pen(c, 2.0))
        _line(p, 9.5, 6.5, 15, 12)
        _line(p, 15, 12, 9.5, 17.5)

    elif name.startswith("cube"):
        parts = name.split("_")
        palette_name = parts[1] if len(parts) > 1 else "grass"
        top, left, right = CUBE_PALETTES.get(palette_name, DEFAULT_CUBE)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(top)))
        p.drawPolygon(_poly((12, 2.6), (21.4, 7.4), (12, 12.2), (2.6, 7.4)))
        p.setBrush(QBrush(QColor(left)))
        p.drawPolygon(_poly((2.6, 7.4), (12, 12.2), (12, 21.4), (2.6, 16.6)))
        p.setBrush(QBrush(QColor(right)))
        p.drawPolygon(_poly((21.4, 7.4), (12, 12.2), (12, 21.4), (21.4, 16.6)))
        p.setPen(_pen("#00000038", 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(_poly((12, 2.6), (21.4, 7.4), (21.4, 16.6), (12, 21.4),
                            (2.6, 16.6), (2.6, 7.4)))
        _line(p, 2.6, 7.4, 12, 12.2)
        _line(p, 21.4, 7.4, 12, 12.2)
        _line(p, 12, 12.2, 12, 21.4)

    elif name == "folder":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(3, 7.5)
        path.lineTo(9.2, 7.5)
        path.lineTo(11, 5)
        path.lineTo(19.5, 5)
        path.quadTo(21, 5, 21, 6.6)
        path.lineTo(21, 17.4)
        path.quadTo(21, 19, 19.4, 19)
        path.lineTo(4.6, 19)
        path.quadTo(3, 19, 3, 17.4)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "folder_new":
        _draw(p, "folder", c)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.drawEllipse(QPointF(17.6, 16.4), 5.6, 5.6)
        p.setPen(_pen("#FFFFFF", 1.8))
        _line(p, 17.6, 13.8, 17.6, 19.0)
        _line(p, 15.0, 16.4, 20.2, 16.4)

    elif name == "import":
        p.setPen(_pen(c, 2.0))
        p.setBrush(Qt.NoBrush)
        _line(p, 12, 3.5, 12, 12.5)
        _arrow_head(p, 12, 13.6, 3.6, c)
        path = QPainterPath()
        path.moveTo(4, 15.2)
        path.lineTo(4, 19)
        path.lineTo(20, 19)
        path.lineTo(20, 15.2)
        p.drawPath(path)

    elif name in ("export", "export_script"):
        p.setPen(_pen(c, 2.0))
        p.setBrush(Qt.NoBrush)
        _line(p, 12, 12.6, 12, 3.6)
        _arrow_head(p, 12, 2.4, 3.6, c)
        path = QPainterPath()
        path.moveTo(4, 15.2)
        path.lineTo(4, 19)
        path.lineTo(20, 19)
        path.lineTo(20, 15.2)
        p.drawPath(path)

    elif name == "shield_check":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        path = QPainterPath()
        path.moveTo(12, 2.6)
        path.lineTo(19.8, 5.6)
        path.lineTo(19.8, 12.0)
        path.quadTo(19.8, 18.0, 12, 21.4)
        path.quadTo(4.2, 18.0, 4.2, 12.0)
        path.lineTo(4.2, 5.6)
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(_pen("#FFFFFF", 2.0))
        _line(p, 8.4, 12.2, 11.0, 14.8)
        _line(p, 11.0, 14.8, 15.6, 9.4)

    elif name in ("offline", "wifi_off"):
        p.setPen(_pen(c, 2.0))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(4.5, 11.0)
        path.quadTo(12, 4.6, 19.5, 11.0)
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(8.0, 14.6)
        path2.quadTo(12, 11.2, 16.0, 14.6)
        p.drawPath(path2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.drawEllipse(QPointF(12, 18.4), 1.5, 1.5)
        p.setPen(_pen(c, 2.0))
        _line(p, 4.6, 4.6, 19.4, 19.4)

    elif name == "search":
        p.setPen(_pen(c, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(10.4, 10.4), 6.0, 6.0)
        _line(p, 15.0, 15.0, 20.0, 20.0)

    elif name == "plus":
        p.setPen(_pen(c, 2.2))
        _line(p, 12, 5, 12, 19)
        _line(p, 5, 12, 19, 12)

    elif name == "check":
        p.setPen(_pen(c, 2.6))
        p.setBrush(Qt.NoBrush)
        _line(p, 4.8, 12.6, 9.8, 17.6)
        _line(p, 9.8, 17.6, 19.2, 6.6)

    elif name == "close":
        p.setPen(_pen(c, 1.6))
        _line(p, 7.5, 7.5, 16.5, 16.5)
        _line(p, 16.5, 7.5, 7.5, 16.5)

    elif name == "minimize":
        p.setPen(_pen(c, 1.6))
        _line(p, 7.0, 12.0, 17.0, 12.0)

    elif name == "maximize":
        p.setPen(_pen(c, 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(7.0, 7.0, 10.0, 10.0))

    elif name == "restore":
        p.setPen(_pen(c, 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(6.0, 9.0, 9.0, 9.0))
        path = QPainterPath()
        path.moveTo(9.0, 9.0)
        path.lineTo(9.0, 6.0)
        path.lineTo(18.0, 6.0)
        path.lineTo(18.0, 15.0)
        path.lineTo(15.0, 15.0)
        p.drawPath(path)

    elif name == "java":
        p.setPen(_pen(c, 1.9))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(5.5, 9.5)
        path.lineTo(5.5, 14.5)
        path.quadTo(5.5, 19.0, 10.5, 19.0)
        path.lineTo(13.5, 19.0)
        path.quadTo(18.5, 19.0, 18.5, 14.5)
        path.lineTo(18.5, 9.5)
        p.drawPath(path)
        _line(p, 4.4, 9.5, 19.6, 9.5)
        p.setPen(_pen(c, 1.6))
        path2 = QPainterPath()
        path2.moveTo(10.5, 3.2)
        path2.quadTo(12.6, 5.0, 10.5, 7.0)
        p.drawPath(path2)
        path3 = QPainterPath()
        path3.moveTo(14.4, 3.2)
        path3.quadTo(16.5, 5.0, 14.4, 7.0)
        p.drawPath(path3)

    elif name == "refresh":
        p.setPen(_pen(c, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(4.5, 4.5, 15, 15), 60 * 16, 250 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.drawPolygon(_poly((19.6, 3.0), (20.4, 10.0), (14.0, 7.6)))

    elif name == "star":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        path = QPainterPath()
        for i in range(10):
            r = 9.4 if i % 2 == 0 else 4.2
            a = math.radians(-90 + i * 36)
            x = 12 + r * math.cos(a)
            y = 12 + r * math.sin(a)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "package":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(3.4, 6.4, 17.2, 13.2))
        _line(p, 3.4, 10.6, 20.6, 10.6)
        path = QPainterPath()
        path.moveTo(9.4, 6.4)
        path.lineTo(9.4, 3.4)
        path.lineTo(14.6, 3.4)
        path.lineTo(14.6, 6.4)
        p.drawPath(path)

    elif name == "edit":
        p.setPen(_pen(c, 1.9))
        p.setBrush(Qt.NoBrush)
        _line(p, 4.5, 19.5, 8.5, 18.6)
        _line(p, 8.5, 18.6, 19.6, 7.5)
        _line(p, 16.6, 4.5, 19.6, 7.5)
        _line(p, 16.6, 4.5, 5.7, 15.4)
        _line(p, 5.7, 15.4, 4.5, 19.5)

    elif name == "pcl":
        # 镐子: 白色, 用于标题栏 Logo
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        p.save()
        p.translate(12, 12)
        p.rotate(45)
        p.drawRoundedRect(QRectF(-1.35, -2.0, 2.7, 12.0), 1.0, 1.0)
        p.restore()
        path = QPainterPath()
        path.moveTo(4.6, 8.6)
        path.quadTo(11.6, 2.2, 19.4, 8.6)
        path.quadTo(11.6, 6.0, 4.6, 8.6)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "skin":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(4.0, 3.6, 16.0, 16.8), 2.0, 2.0)
        _line(p, 4.0, 9.6, 20.0, 9.6)
        _line(p, 12, 9.6, 12, 20.4)

    elif name == "clock":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(12, 12), 8.4, 8.4)
        _line(p, 12, 6.6, 12, 12.2)
        _line(p, 12, 12.2, 16.2, 14.4)

    elif name in ("info", "warn", "error", "question"):
        p.setPen(_pen(c, 1.9))
        p.setBrush(Qt.NoBrush)
        if name == "warn":
            path = QPainterPath()
            path.moveTo(12, 3.2)
            path.lineTo(21.4, 19.6)
            path.lineTo(2.6, 19.6)
            path.closeSubpath()
            p.drawPath(path)
            glyph = "!"
            gy = 15.6
        else:
            p.drawEllipse(QPointF(12, 12), 8.8, 8.8)
            glyph = {"info": "i", "error": "\u00d7", "question": "?"}[name]
            gy = 16.4
        font = p.font()
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor(c)))
        p.drawText(QRectF(0, gy - 11.0, 24, 13), Qt.AlignHCenter | Qt.AlignVCenter, glyph)

    elif name == "mod":
        # 拼图块: Mod
        path = QPainterPath()
        path.addRoundedRect(QRectF(4.0, 4.0, 16.0, 16.0), 2.5, 2.5)
        p.setPen(_pen(c, 1.7))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.drawEllipse(QPointF(12.0, 12.0), 3.4, 3.4)

    elif name == "modpack":
        # 箱子: 整合包
        p.setPen(_pen(c, 1.7))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 6.5, 17.0, 13.0), 2.0, 2.0)
        p.drawPath(path)
        _line(p, 3.5, 11.0, 20.5, 11.0)
        _line(p, 12.0, 6.5, 12.0, 11.0)

    elif name == "datapack":
        # 网格: 数据包
        p.setPen(_pen(c, 1.7))
        p.setBrush(Qt.NoBrush)
        for gx in (4.0, 10.0, 16.0):
            p.drawRect(QRectF(gx, 4.0, 4.0, 4.0))
            p.drawRect(QRectF(gx, 10.0, 4.0, 4.0))
            p.drawRect(QRectF(gx, 16.0, 4.0, 4.0))

    elif name == "resourcepack":
        # 画框: 资源包
        p.setPen(_pen(c, 1.7))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17.0, 15.0), 2.0, 2.0)
        p.drawEllipse(QPointF(8.5, 9.5), 1.5, 1.5)
        path = QPainterPath()
        path.moveTo(5.5, 18.0)
        path.lineTo(10.5, 12.5)
        path.lineTo(14.0, 16.0)
        path.lineTo(16.5, 13.5)
        path.lineTo(20.0, 18.0)
        p.drawPath(path)

    elif name == "shader":
        # 太阳 + 光线: 光影包
        p.setPen(_pen(c, 1.7))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(12.0, 12.0), 4.2, 4.2)
        for dx, dy in ((0, -8.0), (0, 8.0), (-8.0, 0), (8.0, 0),
                       (-5.6, -5.6), (5.6, 5.6), (-5.6, 5.6), (5.6, -5.6)):
            _line(p, 12.0 + dx * 0.72, 12.0 + dy * 0.72, 12.0 + dx, 12.0 + dy)

    elif name == "trash":
        # 垃圾桶(用于删除版本)
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        _line(p, 4.6, 6.4, 19.4, 6.4)
        path = QPainterPath()
        path.moveTo(6.6, 6.4)
        path.lineTo(7.6, 20.0)
        path.lineTo(16.4, 20.0)
        path.lineTo(17.4, 6.4)
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(9.4, 6.4)
        path2.lineTo(9.9, 3.6)
        path2.lineTo(14.1, 3.6)
        path2.lineTo(14.6, 6.4)
        p.drawPath(path2)
        _line(p, 10.6, 9.4, 11.1, 17.0)
        _line(p, 13.4, 9.4, 12.9, 17.0)

    elif name == "palette":
        # 调色盘: 一个圆 + 几个小色点(用于「个性化」)
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(12, 3.4)
        path.quadTo(21.0, 3.4, 21.0, 12.0)
        path.quadTo(21.0, 20.6, 12.0, 20.6)
        path.quadTo(3.0, 20.6, 3.0, 12.0)
        path.quadTo(3.0, 3.4, 12.0, 3.4)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c)))
        for px, py in ((8.6, 8.0), (14.4, 8.6), (8.2, 14.6), (14.8, 14.0)):
            p.drawEllipse(QPointF(px, py), 1.7, 1.7)

    else:  # 兜底: 画个方块
        _rounded(p, 5, 5, 14, 14, 3, c)


# --------------------------------------------------------------- 对外接口
def pixmap(name: str, color: str = theme.TEXT_SUB, size: int = 18,
           dpr: Optional[float] = None) -> QPixmap:
    if dpr is None:
        dpr = 1.0
    key = (name, color, int(size), round(dpr, 2))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    px = int(round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(px / BOX, px / BOX)
    _draw(p, name, color)
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def icon(name: str, color: str = theme.TEXT_SUB, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


def image(name: str, color: str = theme.TEXT_SUB, size: int = 18) -> QImage:
    """画到 QImage 上(可在任意线程调用, 供 QQuickImageProvider 使用)。"""
    px = max(4, int(size))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(px / BOX, px / BOX)
    _draw(p, name, color)
    p.end()
    return img


def save_pixmap(name: str, path: str, color: str = theme.TEXT_SUB,
                size: int = 18) -> str:
    pm = pixmap(name, color, size, dpr=1.0)
    pm.save(path, "PNG")
    return path
