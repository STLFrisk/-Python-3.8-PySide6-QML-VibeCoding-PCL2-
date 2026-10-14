"""主题: 调色板 + 暴露给 QML 的 Theme 对象。

GUI 全部用 QML 描述, 这里提供设计变量, QML 通过 context property ``theme`` 访问
(例如 ``color: theme.primary``)。

主题色可运行时修改: ``Theme.setPrimary("#RRGGBB")`` 会重新计算派生色并发出
``primaryChanged`` 信号, 所有绑定到 ``theme.*`` 的组件会自动跟着变
(设置窗口的「个性化」页就是这么实现的)。
"""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QColor, QFont

# ---------------------------------------------------------------- 默认色(改主题色前的基准)
PRIMARY = "#2B7CDB"
PRIMARY_DARK = "#1F6AC6"
PRIMARY_LIGHT = "#4E97E8"
PRIMARY_SOFT = "#E8F1FD"
TITLE_TOP = "#3C8DE8"
TITLE_BOTTOM = "#1E6BCC"
HOVER = "#EAF2FD"
SELECTED = "#DFEBFB"

# 不随主题色变化的中性色
BG = "#EDF2FA"
BG_DEEP = "#E3EBF7"
CARD = "#FFFFFF"
BORDER = "#DCE4EF"
BORDER_INPUT = "#C9D6E8"
TEXT = "#2C2C2C"
TEXT_TITLE = "#1F2D3D"
TEXT_SUB = "#8A93A0"
TEXT_HINT = "#A9B3C0"
DANGER = "#D9534F"
SUCCESS = "#3FA45B"
WHITE = "#FFFFFF"
SHADOW = "#C8D4E6"
SIDE_BG = "#F4F8FD"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_FALLBACK = "Microsoft YaHei"
FONT_SIZE = 12
APP_NAME = "CraftPilot"

# 主题色预设(设置 → 个性化 里显示)
PRESETS = [
    {"name": "默认蓝", "color": "#2B7CDB"},
    {"name": "湖水青", "color": "#17A2B8"},
    {"name": "草木绿", "color": "#3FA45B"},
    {"name": "暖橙", "color": "#E08A3C"},
    {"name": "枫叶红", "color": "#D9534F"},
    {"name": "薰衣草", "color": "#7B5FD1"},
    {"name": "樱花粉", "color": "#D65A9A"},
    {"name": "石墨灰", "color": "#5A6B7C"},
]


def font(size: int = FONT_SIZE, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setFamilies([FONT_FAMILY, FONT_FALLBACK, "Segoe UI"])
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def qcolor(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """把两个颜色按比例混合(ratio=0 得到 a, =1 得到 b)。"""
    a, b = QColor(color_a), QColor(color_b)
    if not a.isValid():
        a = QColor(PRIMARY)
    if not b.isValid():
        b = QColor(WHITE)
    ratio = max(0.0, min(1.0, float(ratio)))
    return QColor(
        int(round(a.red() + (b.red() - a.red()) * ratio)),
        int(round(a.green() + (b.green() - a.green()) * ratio)),
        int(round(a.blue() + (b.blue() - a.blue()) * ratio)),
    ).name()


class Theme(QObject):
    """给 QML 用的设计变量集合(主题色/启动器标题可改)。"""

    primaryChanged = Signal()
    titleChanged = Signal()
    cornersChanged = Signal()

    def __init__(self, primary: str = "", app_title: str = "", parent=None) -> None:
        super().__init__(parent)
        self._primary = QColor(primary) if QColor(primary).isValid() else QColor(PRIMARY)
        self._derived = self._compute(self._primary)
        self._app_title = str(app_title or "").strip() or APP_NAME
        self._corner = 10
        self._maximized = False

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _compute(base: QColor) -> dict:
        value = base.name()
        return {
            "primary": value,
            "primaryLight": mix(value, WHITE, 0.18),
            "primaryDark": mix(value, "#000000", 0.16),
            "primarySoft": mix(value, WHITE, 0.88),
            "hover": mix(value, WHITE, 0.92),
            "selected": mix(value, WHITE, 0.86),
            "titleTop": mix(value, WHITE, 0.14),
            "titleBottom": mix(value, "#000000", 0.12),
        }

    # ------------------------------------------------------------ 主题色
    @Property(str, notify=primaryChanged)
    def primary(self) -> str:
        return self._derived["primary"]

    @Property(str, notify=primaryChanged)
    def primaryLight(self) -> str:
        return self._derived["primaryLight"]

    @Property(str, notify=primaryChanged)
    def primaryDark(self) -> str:
        return self._derived["primaryDark"]

    @Property(str, notify=primaryChanged)
    def primarySoft(self) -> str:
        return self._derived["primarySoft"]

    @Property(str, notify=primaryChanged)
    def hover(self) -> str:
        return self._derived["hover"]

    @Property(str, notify=primaryChanged)
    def selected(self) -> str:
        return self._derived["selected"]

    @Property(str, notify=primaryChanged)
    def titleTop(self) -> str:
        return self._derived["titleTop"]

    @Property(str, notify=primaryChanged)
    def titleBottom(self) -> str:
        return self._derived["titleBottom"]

    @Property(str, notify=primaryChanged)
    def defaultPrimary(self) -> str:
        return PRIMARY

    @Property("QVariantList", constant=True)
    def presets(self) -> list:
        return [dict(item) for item in PRESETS]

    @Slot(str)
    def setPrimary(self, value: str) -> None:
        color = QColor(str(value or "").strip())
        if not color.isValid():
            return
        if color.name() == self._derived["primary"]:
            return
        self._primary = color
        self._derived = self._compute(color)
        self.primaryChanged.emit()

    @Slot()
    def resetPrimary(self) -> None:
        self.setPrimary(PRIMARY)

    # ------------------------------------------------------------ 固定色
    @Property(str, constant=True)
    def bg(self) -> str:
        return BG

    @Property(str, constant=True)
    def bgDeep(self) -> str:
        return BG_DEEP

    @Property(str, constant=True)
    def card(self) -> str:
        return CARD

    @Property(str, constant=True)
    def border(self) -> str:
        return BORDER

    @Property(str, constant=True)
    def borderInput(self) -> str:
        return BORDER_INPUT

    @Property(str, constant=True)
    def text(self) -> str:
        return TEXT

    @Property(str, constant=True)
    def textTitle(self) -> str:
        return TEXT_TITLE

    @Property(str, constant=True)
    def textSub(self) -> str:
        return TEXT_SUB

    @Property(str, constant=True)
    def textHint(self) -> str:
        return TEXT_HINT

    @Property(str, constant=True)
    def danger(self) -> str:
        return DANGER

    @Property(str, constant=True)
    def success(self) -> str:
        return SUCCESS

    @Property(str, constant=True)
    def white(self) -> str:
        return WHITE

    @Property(str, constant=True)
    def shadow(self) -> str:
        return SHADOW

    @Property(str, constant=True)
    def sideBg(self) -> str:
        return SIDE_BG

    @Property(str, constant=True)
    def fontFamily(self) -> str:
        return FONT_FAMILY

    @Property(int, constant=True)
    def fontSize(self) -> int:
        return FONT_SIZE

    @Property(int, constant=True)
    def titleBarHeight(self) -> int:
        return 42

    @Property(int, constant=True)
    def sidebarWidth(self) -> int:
        return 160

    @Property(int, constant=True)
    def windowRadius(self) -> int:
        return 10

    @Property(str, constant=True)
    def appName(self) -> str:
        return APP_NAME

    # ------------------------------------------------------------ 启动器标题
    @Property(str, notify=titleChanged)
    def appTitle(self) -> str:
        return self._app_title

    @Property(str, constant=True)
    def defaultAppTitle(self) -> str:
        return APP_NAME

    @Slot(str)
    def setAppTitle(self, value: str) -> None:
        text = str(value or "").strip() or APP_NAME
        if text == self._app_title:
            return
        self._app_title = text
        self.titleChanged.emit()

    # ------------------------------------------------------------ 圆角
    @Property(int, notify=cornersChanged)
    def cornerRadius(self) -> int:
        """当前应该使用的圆角: 最大化时为 0(变直角)。"""
        return self._corner

    @Slot(bool)
    def setMaximized(self, value: bool) -> None:
        maximized = bool(value)
        if maximized == self._maximized:
            return
        self._maximized = maximized
        self._corner = 0 if maximized else 10
        self.cornersChanged.emit()
