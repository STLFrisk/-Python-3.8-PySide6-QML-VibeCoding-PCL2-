"""设置页 / 版本独立设置 的后端控制器。"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import config as core_config
from ..core import launch as core_launch
from ..core import paths as core_paths
from ..core import remote as core_remote

JAVA_ROLES = ["label", "path", "version"]


def total_memory_mb() -> int:
    """物理内存总量(MB), 取不到时返回 8192。"""
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys / (1024 * 1024))
    except Exception:  # noqa: BLE001
        pass
    return 8192


class SettingsBackend(QObject):
    """全局设置(设置窗口的「启动」和「其他」页)。"""

    changed = Signal(str)
    javaChanged = Signal()

    def __init__(self, cfg: core_config.Config, launcher=None, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.launcher = launcher
        self._java = []  # type: List[core_launch.JavaInfo]
        self.detectJava()

    # ------------------------------------------------------------ 通用读写
    @Slot(str, result="QVariant")
    def value(self, key: str):
        return self.cfg.get(key, "")

    @Slot(str, "QVariant")
    def setValue(self, key: str, value) -> None:
        self.cfg.set(key, value)
        self.changed.emit(key)

    @Slot(str, result=bool)
    def flag(self, key: str) -> bool:
        return bool(self.cfg.get(key, False))

    # ------------------------------------------------------------ 下载/分片生效值
    @Property(str, notify=changed)
    def downloadTuning(self) -> str:
        """「当前实际生效值」一行(设置 → 其他 → 调试选项 → 下载分片调参)。

        只读: 直接问下载层 ``pclpy/core/remote.py`` 要"现在这一刻真正在用的"
        参数 —— 也就是 环境变量 > 设置项 > 代码默认 之后的落点, 所以界面上
        能看出"勾了开关但环境变量把它关掉了"这类情况。
        ``changed`` 是 setValue() 发出的信号, 所以改完任一项这一行会立刻重算。
        """
        try:
            t = core_remote.download_tuning()
        except Exception as exc:  # noqa: BLE001
            return "读取生效值失败: %s" % (exc,)
        if not t.get("enabled"):
            head = "分片已关闭 (单流下载"
            if t.get("max_segments", 1) > 1:
                head = "分片已关闭 (环境变量 PCLPY_DOWNLOAD_SEGMENTS=%s" % (
                    t.get("max_segments"),)
            text = head + ")"
        else:
            text = "起步 %d 段 / 上限 %d 段 / 全局 %d 连接 / 阈值 %dMB / 低速 %dKB/s" % (
                int(t.get("start_segments", 1)), int(t.get("max_segments", 1)),
                int(t.get("connections", 0)), int(t.get("min_size_mb", 0)),
                int(t.get("slow_kbps", 0)))
        text += "\n日志" + ("开" if t.get("debug") else "关")
        text += " · " + (
            "环境变量已覆盖: " + ", ".join(t.get("env") or [])
            if t.get("env") else "当前无环境变量覆盖")
        return text

    # ------------------------------------------------------------ 内存
    @Property(int, notify=changed)
    def customMemoryMb(self) -> int:
        """「自定义」模式下的分配内存(MB), 非法值回落到 4096。"""
        try:
            value = int(float(self.cfg.get("launch.memory_mb", 0) or 0))
        except (TypeError, ValueError):
            value = 0
        return value if value >= 512 else 4096

    @Slot(int)
    def setCustomMemoryMb(self, value: int) -> None:
        try:
            mb = max(512, int(value))
        except (TypeError, ValueError):
            return
        if mb == self.customMemoryMb:
            return
        self.cfg.set("launch.memory_mb", mb)
        self.changed.emit("launch.memory_mb")

    @Property(int, constant=True)
    def totalMemoryMb(self) -> int:
        return total_memory_mb()

    @Property(int, constant=True)
    def usedMemoryMb(self) -> int:
        """当前系统已用内存(近似: 总量 - 可用量)。"""
        try:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int((status.ullTotalPhys - status.ullAvailPhys) / (1024 * 1024))
        except Exception:  # noqa: BLE001
            pass
        return 4096

    @Property(int, notify=javaChanged)
    def autoMemoryMb(self) -> int:
        return max(1024, int(self.totalMemoryMb / 4))

    @Slot(result=str)
    def memorySummary(self) -> str:
        total = self.totalMemoryMb / 1024.0
        used = self.usedMemoryMb / 1024.0
        return "已使用内存   %.1f GB / %.1f GB" % (used, total)

    # ------------------------------------------------------------ Java
    @Slot()
    def detectJava(self) -> None:
        self._java = core_launch.find_javas()
        self.javaChanged.emit()

    @Property("QVariantList", notify=javaChanged)
    def javaList(self) -> List[Dict]:
        rows = [{"label": j.label(), "path": j.path, "version": j.version}
                for j in self._java]
        return [{"label": "自动选择", "path": "auto", "version": ""}] + rows

    @Slot(result=str)
    def javaHint(self) -> str:
        configured = self.cfg.get("launch.java_path", "auto")
        if configured and configured != "auto" and os.path.exists(configured):
            for j in self._java:
                if os.path.normcase(j.path) == os.path.normcase(configured):
                    return "将会使用:  %s :  %s" % (j.label(), j.path)
            return "将会使用:  %s" % configured
        required = 21
        try:
            if self.launcher is not None:
                required = self.launcher.required_java()
        except Exception:  # noqa: BLE001
            required = 21
        picked, ok = core_launch.pick_java(self._java, required)
        if not ok:
            return "该版本需要 Java %d, 但未检测到满足要求的 Java(已退回 %s)" % (
                required, picked.label())
        if picked.version:
            return "将会使用:  %s :  %s" % (picked.label(), picked.path)
        return "未检测到 Java，请手动指定 javaw.exe 路径"

    # ------------------------------------------------------------ 配置导入导出
    @Slot(str)
    def exportSettings(self, path: str) -> None:
        import json
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.cfg.as_dict(), fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.changed.emit("error:%s" % exc)
            return
        self.changed.emit("exported")

    @Slot(str)
    def importSettings(self, path: str) -> None:
        import json
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            self.changed.emit("error:%s" % exc)
            return
        if isinstance(data, dict):
            for key, value in data.items():
                self.cfg.set(key, value, autosave=False)
            self.cfg.save()
        self.changed.emit("imported")

    @Slot()
    def checkUpdate(self) -> None:
        self.changed.emit("check-update")


class VersionSettingsBackend(QObject):
    """版本设置窗口: 概览 / 设置 / Mod 管理 / 导出。

    每个版本的独立设置保存在 ``<版本目录>/pclpy.json``; 未写入的项回退到全局设置,
    对应界面上的「跟随全局设置」。
    """

    changed = Signal()
    infoChanged = Signal()
    globalSettingsRequested = Signal()

    def __init__(self, cfg: core_config.Config, launcher, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.launcher = launcher
        self._local = core_config.Config(path=os.path.join(core_paths.app_home(),
                                                           "version_default.json"))
        self._version_id = ""
        self._info: Dict = {}

    # ------------------------------------------------------------ 信息
    @Slot(str)
    def load(self, version_id: str) -> None:
        self._version_id = version_id or ""
        self._info = dict(self.launcher.versionInfo(self._version_id) or {})
        path = self._info.get("path", "")
        local_path = os.path.join(path, "pclpy.json") if path else ""
        if local_path and os.path.isdir(path):
            self._local = core_config.Config(path=local_path)
        else:
            self._local = core_config.Config(path=os.path.join(
                core_paths.app_home(), "version_%s.json" % core_paths.safe_name(
                    self._version_id or "default")))
        self.infoChanged.emit()
        self.changed.emit()

    @Property(str, notify=infoChanged)
    def versionId(self) -> str:
        return self._version_id

    @Property(str, notify=infoChanged)
    def title(self) -> str:
        return self._info.get("name", self._version_id or "未选择版本")

    @Property(str, notify=infoChanged)
    def subtitle(self) -> str:
        return self._info.get("subtitle", "")

    @Property(str, notify=infoChanged)
    def icon(self) -> str:
        return self._info.get("icon", "cube_grass")

    @Property(str, notify=infoChanged)
    def path(self) -> str:
        return self._info.get("path", "")

    @Property(str, notify=infoChanged)
    def description(self) -> str:
        return self._info.get("description", "") or ""

    @Property(bool, notify=infoChanged)
    def favorite(self) -> bool:
        return bool(self._info.get("favorite"))

    @Property(bool, notify=infoChanged)
    def isDemo(self) -> bool:
        return not bool(self._info.get("path"))

    @Property(str, notify=infoChanged)
    def sizeText(self) -> str:
        return self._info.get("size", "") or "未知"

    @Property(str, notify=infoChanged)
    def mcVersion(self) -> str:
        return self._info.get("mcVersion", "")

    @Property(str, notify=infoChanged)
    def loader(self) -> str:
        return self._info.get("loader", "")

    @Property(str, notify=infoChanged)
    def isolationText(self) -> str:
        return "开启" if self.launcher.isolated(self._version_id) else "关闭"

    # ------------------------------------------------------------ 版本独立设置读写
    @Slot(str, result="QVariant")
    def value(self, key: str):
        local = self._local.get(key, None)
        if local is not None and local != "":
            return local
        return self.cfg.get(key, "")

    @Slot(str, bool, result="QVariant")
    def valueOr(self, key: str, _unused: bool):
        return self.value(key)

    @Slot(str, result=bool)
    def isFollow(self, key: str) -> bool:
        local = self._local.get(key, None)
        return local is None or local == ""

    @Slot(str, "QVariant")
    def setValue(self, key: str, value) -> None:
        if value == "follow":
            self._local.set(key, "", autosave=True)
        else:
            self._local.set(key, value)
        # 版本隔离需要在主界面立刻生效, 因此同时写一份到全局配置
        if key == "launch.isolation" and self._version_id:
            self.cfg.set("version_isolation.%s" % self._version_id,
                         "" if value == "follow" else value)
        self.changed.emit()
        self.infoChanged.emit()

    @Slot(str)
    def setFollow(self, key: str) -> None:
        self._local.set(key, "")
        self.changed.emit()

    @Slot(str, result=str)
    def followLabel(self, key: str) -> str:
        return "跟随全局设置" if self.isFollow(key) else str(self.value(key))

    # ------------------------------------------------------------ 操作
    @Slot(str)
    def openFolder(self, kind: str) -> None:
        info = self.launcher.folderInfo(self._version_id)
        path = info.get(kind, "")
        if not path:
            return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        core_paths.open_in_explorer(path)

    @Slot(str)
    def rename(self, name: str) -> None:
        self.launcher.renameVersion(self._version_id, name)
        self.load(self._version_id)

    @Slot(str)
    def setDescription(self, text: str) -> None:
        self.launcher.setVersionDescription(self._version_id, text)
        self.load(self._version_id)

    @Slot()
    def toggleFavorite(self) -> None:
        self.launcher.toggleFavorite(self._version_id)
        self.load(self._version_id)

    @Slot()
    def deleteVersion(self) -> None:
        self.launcher.requestDeleteVersion(self._version_id)

    @Slot()
    def completeFiles(self) -> None:
        self.launcher.completeFiles()

    @Slot()
    def exportScript(self) -> None:
        self.launcher.exportStartScript(self._version_id)

    @Slot()
    def openGlobalSettings(self) -> None:
        self.globalSettingsRequested.emit()
