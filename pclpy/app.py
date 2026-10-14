"""应用组装: 创建 QApplication / QML 引擎 / 后端对象。

界面全部由 QML 描述(见 qml/ 目录), 本模块只负责把 Python 后端对象注入 QML
上下文, 并加载 Main.qml。
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from . import icons, providers, theme
from .backend import (DownloadBackend, LauncherBackend, ResourcesBackend,
                      SettingsBackend, VersionSettingsBackend)

def _resource_roots() -> list:
    """列出可能存放 ``qml/`` 与 ``vendor/`` 的候选根目录。

    打包成 exe 之后 ``__file__`` 指向解包目录, 所以候选根按冻结形态排前面:

    * PyInstaller onedir: 数据文件被放进 ``_internal/``, 即 ``sys._MEIPASS``;
    * 冻结版兜底: exe 自身所在目录(方便把 ``qml/`` 与 ``vendor/`` 摆在 exe 旁边);
    * 源码运行: 项目根目录(``pclpy/`` 的上一级)。

    **源码运行(非冻结)时结果与原来完全一致**: ``sys._MEIPASS`` 不存在、
    ``sys.frozen`` 为假, 候选表里只剩项目根目录一项。
    """
    roots = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    unique = []
    for root in roots:
        if root and root not in unique:
            unique.append(root)
    return unique


_RESOURCE_ROOTS = _resource_roots()


def _find_resource(name: str) -> str:
    """在候选根目录里找到 ``qml`` / ``vendor``; 都找不到时退回第一个候选(便于报错定位)。"""
    for root in _RESOURCE_ROOTS:
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(_RESOURCE_ROOTS[0], name)


QML_DIR = _find_resource("qml")
VENDOR_DIR = _find_resource("vendor")


def _load_fluentui_module():
    """得到 ``vendor/FluentUI`` 这个 Python 包(冻结版走文件路径直载, 绕开导入器差异)。"""
    if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
        sys.path.append(VENDOR_DIR)
    try:
        import FluentUI  # type: ignore
        return FluentUI
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[app] import FluentUI failed: %r\n" % (exc,))
    # 兜底: 按文件路径直接加载 vendor/FluentUI/__init__.py
    init_py = os.path.join(VENDOR_DIR, "FluentUI", "__init__.py")
    if not os.path.isfile(init_py):
        sys.stderr.write("[app] FluentUI __init__.py not found at %s\n" % init_py)
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "FluentUI", init_py,
            submodule_search_locations=[os.path.dirname(init_py)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["FluentUI"] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[app] load FluentUI by path failed: %r\n" % (exc,))
        return None


def _setup_fluentui(engine) -> bool:
    """把项目内 vendor/ 里的 PySide6-FluentUI-QML 注册进 QML 引擎。

    套件提供一个 FluentUI QML 模块, 调用它的 init() 会把 `vendor/FluentUI/qml`
    加进 QML 导入路径, 之后 QML 里 `import FluentUI` 才可用。
    没带套件时静默跳过(界面仍可退回自绘组件)。
    """
    if not os.path.isdir(VENDOR_DIR):
        sys.stderr.write("[app] vendor dir not found, expected at %s\n" % VENDOR_DIR)
        return False
    module = _load_fluentui_module()
    if module is None:
        return False
    try:
        module.init(engine)
        return True
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[app] FluentUI.init failed: %r\n" % (exc,))
        return False


class LauncherApp(object):
    """启动器的运行时环境(可在测试/截图脚本里复用)。"""

    def __init__(self, argv: Optional[list] = None) -> None:
        argv = list(sys.argv if argv is None else argv)
        # 让 Qt Quick 用独立渲染线程(渲染不占用界面线程, 动画更顺)。必须在
        # QGuiApplication 之前设置; 用户显式指定过就不动它。
        # 注意: 软件渲染 + 渲染线程容易死锁, 所以软件后端下不启用。
        if str(os.environ.get("QT_QUICK_BACKEND", "")).lower() != "software":
            os.environ.setdefault("QSG_RENDER_LOOP", "threaded")
        self.app = QGuiApplication.instance() or QGuiApplication(argv)
        self.app.setApplicationName("CraftPilot")
        self.app.setApplicationDisplayName("CraftPilot")
        self.app.setOrganizationName("CraftPilot")
        self.app.setFont(theme.font(12))
        try:
            self.app.setWindowIcon(QIcon(icons.pixmap("pcl", theme.PRIMARY, 64, dpr=1.0)))
        except Exception:  # noqa: BLE001
            pass

        from .core import config as core_config
        self.config = core_config.Config()
        # 把主配置登记为"下载层可读的当前配置": 下载前会读一次
        # download.segments_* / connections / min_size_mb / slow_kbps / debug_log,
        # 这样设置页改完下一次下载就生效(不必重启进程、也不必改环境变量)。
        # 只在这里登记 —— 版本设置页(VersionSettingsBackend)会另建 Config,
        # 若在 Config.__init__ 里自动登记就会被它顶掉。
        core_config.set_current(self.config)

        self.backend = LauncherBackend(self.config)
        self.settings = SettingsBackend(self.config, self.backend)
        self.version_settings = VersionSettingsBackend(self.config, self.backend)
        self.resources = ResourcesBackend(self.config, self.backend)
        self.download = DownloadBackend(self.config, self.backend)

        self.engine = QQmlApplicationEngine()
        providers.register(self.engine)
        # 注册 FluentUI 的 QML 导入路径(内容区组件用它): QML 里才能 import FluentUI
        self.fluentui = _setup_fluentui(self.engine)
        # 注意: 必须保持 Python 引用, 否则 QObject 会被 GC 回收, QML 侧拿到 null
        # 主题色与启动器标题从配置读取, 改动后写回配置(设置 → 个性化)
        self.theme = theme.Theme(str(self.config.get("ui.theme_color", "") or ""),
                                 str(self.config.get("ui.app_title", "") or ""))
        self.theme.primaryChanged.connect(self._on_theme_changed)
        self.theme.titleChanged.connect(self._on_title_changed)
        ctx = self.engine.rootContext()
        ctx.setContextProperty("theme", self.theme)
        ctx.setContextProperty("backend", self.backend)
        ctx.setContextProperty("settings", self.settings)
        ctx.setContextProperty("versionSettings", self.version_settings)
        ctx.setContextProperty("community", self.resources)
        ctx.setContextProperty("download", self.download)

        self.engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))
        self.window = self.engine.rootObjects()[0] if self.engine.rootObjects() else None

        # 版本列表变化(例如刚安装完)时刷新下载页的「已安装」标记
        self.backend.versionsChanged.connect(self.download.refreshInstalled)

        # 首次运行时把"版本隔离档位"写死进配置(学 PCL2 的 Decide & Freeze):
        # 有旧配置的用户沿用旧默认(关闭), 全新用户才会是"隔离所有"。
        try:
            from .core import launch as core_launch
            core_launch.migrate_isolation_default(self.config, self.backend.root())
        except Exception:  # noqa: BLE001
            pass

        # 启动后就异步拉取版本列表(无网络时自动回退到内置列表)
        self.download.refresh()

    @property
    def ok(self) -> bool:
        return self.window is not None

    def _on_theme_changed(self) -> None:
        """主题色变化: 写回配置, 下次启动保持。"""
        try:
            self.config.set("ui.theme_color", self.theme.primary)
        except Exception:  # noqa: BLE001
            pass

    def _on_title_changed(self) -> None:
        """启动器标题变化: 写回配置。"""
        try:
            value = self.theme.appTitle
            if value == theme.APP_NAME:
                value = ""
            self.config.set("ui.app_title", value)
        except Exception:  # noqa: BLE001
            pass

    def qml_errors(self) -> list:
        """加载期收集到的 QML 报错(供命令行/测试打印)。"""
        collected = list(getattr(self, "_qml_messages", []) or [])
        try:
            if not (self.engine.rootObjects() or []):
                collected.append("QML 根对象为空(加载失败)")
        except Exception:  # noqa: BLE001
            pass
        return collected

    def run(self) -> int:
        if not self.ok:
            return 1
        return self.app.exec()
