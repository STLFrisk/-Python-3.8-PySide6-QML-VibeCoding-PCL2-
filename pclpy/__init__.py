"""PCL-Py: 基于 PySide6 + QML 的 Minecraft 启动器。

模块结构:
    pclpy.core     纯 Python 逻辑(配置/版本/启动/安装/导出), 无 Qt 依赖
    pclpy.backend  暴露给 QML 的 QObject / 列表模型 / 工作线程
    pclpy.icons    全部图标用 QPainter 现画, 通过 image://icon 提供
    qml/           全部界面(标题栏/页面/窗口)
"""

__version__ = "1.0.0"
__all__ = ["app", "theme", "icons", "providers", "avatar", "core", "backend"]
