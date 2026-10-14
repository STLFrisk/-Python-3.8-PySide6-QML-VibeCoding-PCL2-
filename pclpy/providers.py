"""QML 图片提供者: 矢量图标与像素头像。

QML 里这样用::

    Image { source: "image://icon/play?color=%23FFFFFF&size=16" }
    Image { source: "image://avatar/HanazonoTae?size=64" }

图标全部由 :mod:`pclpy.icons` 用 QPainter 现画, 因此项目不依赖任何图片资源。
"""
from __future__ import annotations

import urllib.parse
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from . import avatar as avatar_mod
from . import icons, theme


def _parse(image_id: str):
    """把 "play?color=%23FFF&size=16" 拆成 (名字, 参数字典)。"""
    if "?" in image_id:
        name, _, query = image_id.partition("?")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
    else:
        name, params = image_id, {}
    return name, params


class IconProvider(QQuickImageProvider):
    """image://icon/<名字>?color=<%23RRGGBB>&size=<px>"""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, image_id: str, size: QSize, requestedSize: QSize) -> QImage:  # noqa: N802
        name, params = _parse(image_id or "")
        color = params.get("color", theme.TEXT_SUB)
        try:
            px = int(params.get("size", 18))
        except ValueError:
            px = 18
        if requestedSize and requestedSize.width() > 0:
            px = max(px, requestedSize.width())
        px = max(4, min(px, 512))
        img = icons.image(name or "cube_grass", color, px)
        return img


class AvatarProvider(QQuickImageProvider):
    """image://avatar/<玩家名>?size=<px>&model=<steve|alex>"""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, image_id: str, size: QSize, requestedSize: QSize) -> QImage:  # noqa: N802
        name, params = _parse(image_id or "")
        try:
            px = int(params.get("size", 64))
        except ValueError:
            px = 64
        if requestedSize and requestedSize.width() > 0:
            px = max(px, requestedSize.width())
        px = max(8, min(px, 512))
        model = params.get("model", "steve")
        return avatar_mod.avatar_image(name or "Steve", px, model)


def register(engine) -> None:
    engine.addImageProvider("icon", IconProvider())
    engine.addImageProvider("avatar", AvatarProvider())
