"""主界面/版本选择/版本设置 共用的后端控制器。

QML 侧通过 context property ``backend`` 使用本对象。

**本模块是兼容入口**: 实现已按职责原样拆到 mixin 模块(``launcher_tasks`` /
``launcher_launch``), 这里把同样的公共名字重新导出 —— 外部继续
``from pclpy.backend.launcher import LauncherBackend`` / ``INSTALL_STEPS`` 不变;
``LauncherBackend`` 的方法经 MRO 全部还在(含 QML 按元对象调用的 slot/property)。

"""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Dict, List, Optional

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from ..core import accounts as core_accounts
from ..core import config as core_config
from ..core import install as core_install
from ..core import launch as core_launch
from ..core import mods as core_mods
from ..core import packexport
from ..core import paths as core_paths
from ..core import versions as core_versions
from .models import DictListModel, FilterableListModel
from .workers import (ExportWorker, InstallWorker, JavaScanWorker, ProcessReader,
                      ResourceDownloadWorker,
                      TailLogReader, VersionScanWorker, WindowTitleWorker)
from .launcher_tasks import TaskMixin
from .launcher_launch import LaunchMixin

VERSION_ROLES = ["versionId", "name", "subtitle", "icon", "installed", "source", "size",
                 "kind", "mcVersion", "loader", "loaderVersion", "note", "description",
                 "favorite", "search"]
FOLDER_ROLES = ["name", "path", "active"]
MOD_ROLES = ["fileName", "name", "subtitle", "enabled", "size", "selected", "path"]
JAVA_ROLES = ["label", "path", "version"]
TASK_ROLES = ["taskId", "title", "kind", "state", "stateText", "percent", "speedText",
              "remainingText", "steps", "canCancel", "canClear"]

# 安装任务的步骤(phase_id, 显示名)
INSTALL_STEPS = [
    ("prepare", "获取版本列表"),
    ("json", "下载原版 json 文件"),
    ("client", "下载客户端 jar"),
    ("libraries", "下载原版支持库文件"),
    ("assets", "下载原版资源文件"),
    ("natives", "解压本地库"),
    ("done", "安装游戏"),
]
EXPORT_STEPS = [
    ("prepare", "收集文件"),
    ("done", "写入整合包"),
]
# 社区资源下载/整合包安装的任务步骤(与安装游戏用同一套任务系统)
RESOURCE_STEPS = [
    ("prepare", "准备下载"),
    ("download", "下载文件"),
    ("done", "完成"),
]
# 整合包安装的阶段(顺序与文案对齐 PCL2 的整合包安装页):
#   解压整合包文件 → 下载额外文件 → 解压覆盖文件 → 下载原版 json → 下载原版客户端 jar
#   → 下载原版支持库 → 下载原版资源文件 → 获取并安装加载器 → 安装游戏 → 下载游戏支持库
# 说明: ("deps"/"loader") 等价, 保留 deps 作为旧别名, 免得历史任务显示错位。
MODPACK_STEPS = [
    ("prepare", "解压整合包文件"),
    ("files", "下载额外文件"),
    ("overrides", "解压覆盖文件"),
    ("json", "下载原版 json 文件"),
    ("client", "下载原版客户端 jar"),
    ("libraries", "下载原版支持库文件"),
    ("assets", "下载原版资源文件"),
    ("natives", "解压本地库"),
    # deps = 取加载器信息(版本列表/安装器), loader = 真正安装加载器;
    # 两者是**不同阶段**, 所以文案要分开写 —— 之前写成同一句, 任务页上看起来像重复了两行。
    ("deps", "获取模组加载器信息"),
    ("loader", "安装模组加载器"),
    ("install", "安装游戏"),
    ("libs", "下载游戏支持库"),
    ("done", "完成"),
]


class LauncherBackend(TaskMixin, LaunchMixin, QObject):
    # ------------------------------------------------------------ 信号
    messageRequested = Signal(str, str, str)      # 标题, 内容, 类型
    confirmRequested = Signal(str, str)           # 标题, 内容
    versionsChanged = Signal()
    accountsChanged = Signal()
    statusChanged = Signal()
    launchStateChanged = Signal()
    windowRequested = Signal(str)
    toastRequested = Signal(str)
    versionDeleted = Signal(str)                   # 版本 id
    resourceDownloaded = Signal(str, str)          # 说明文字, 落盘路径
    logAppended = Signal(str)

    def __init__(self, cfg: Optional[core_config.Config] = None, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg or core_config.Config()
        self._folder_model = DictListModel(FOLDER_ROLES, self)
        self._installable_model = DictListModel(VERSION_ROLES, self)
        self._catalog_model = DictListModel(VERSION_ROLES, self)
        self._normal_model = DictListModel(VERSION_ROLES, self)
        self._uncommon_model = DictListModel(VERSION_ROLES, self)
        self._mod_model = FilterableListModel(MOD_ROLES, self)
        self._java_model = DictListModel(JAVA_ROLES, self)
        self._task_model = DictListModel(TASK_ROLES, self)

        # 任务管理(下载/安装/导出)
        self._tasks: List[Dict] = []
        self._task_seq = 0
        # 速度**单点计算**(学 PCL2): 200ms 采样一次"全局已下载字节"的增量,
        # 再做递减加权平均。所有任务共享同一个速度值 ——
        # 以前是每个任务各自 delta/0.7, 并行下载时某个文件回调一稀疏就会显示 -- 或乱跳。
        self._bytes_global = 0
        self._speed_window: List[float] = []
        self._speed = 0.0
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(200)
        self._speed_timer.timeout.connect(self._tick_speed)
        self._speed_timer.start()

        # 后台线程(扫描版本 / 检测 Java / 改游戏窗口标题)
        self._scan_worker = None
        self._scan_pending = False
        self._java_worker = None
        self._title_worker = None
        self._last_scan_at = 0.0

        # 配置写盘防抖: 拖动滑块之类的连续改动不会每次都写磁盘
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(lambda: self.cfg.save(force=True))
        self.cfg.defer = self._save_timer.start

        self._status = "准备就绪"
        self._launch_state = "idle"
        self._demo_mode = False
        self._versions: List[core_versions.VersionInfo] = []
        self._installable: List[core_versions.VersionInfo] = []
        self._javas: List[core_launch.JavaInfo] = []
        self._install_worker: Optional[InstallWorker] = None
        self._resource_worker = None
        self._resource_paths = {}          # 任务 id -> 落盘路径
        self._export_worker: Optional[ExportWorker] = None
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[ProcessReader] = None
        self._log_tail = None
        self._log_handle = None
        self._log_path = ""
        self._pending_action = ""
        self._log_lines: List[str] = []

        self._ensure_defaults()
        self.refresh()

    # ================================================================ 初始化
    def _ensure_defaults(self) -> None:
        folders = self.cfg.folders or []
        official = core_paths.official_minecraft_dir()
        if not any(os.path.normcase(f.get("path", "")) == os.path.normcase(official)
                   for f in folders):
            folders.insert(0, {"name": "官方启动器文件夹", "path": official})
            self.cfg.set("folders", folders, autosave=False)
        if not self.cfg.selected_folder:
            self.cfg.set("selected_folder", folders[0].get("path", official), autosave=False)
        if not self.cfg.accounts:
            self.cfg.set("accounts", [core_accounts.to_dict(core_accounts.offline("HanazonoTae"))],
                         autosave=False)
            self.cfg.set("selected_account", "HanazonoTae", autosave=False)
        self.cfg.save()

    # ================================================================ 属性
    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=launchStateChanged)
    def launchState(self) -> str:
        return self._launch_state

    @Property(bool, notify=versionsChanged)
    def demoMode(self) -> bool:
        """是否在用内置示例数据(默认关闭, 只在测试/截图时显式打开)。"""
        return self._demo_mode

    @Property(int, notify=versionsChanged)
    def versionCount(self) -> int:
        """当前文件夹里检索到的已安装版本数量。"""
        return len(self._versions)

    @Property(str, notify=versionsChanged)
    def folderName(self) -> str:
        """当前游戏文件夹的名字(给「正在检索 xxx」这类提示用)。"""
        root = self.root()
        for folder in self.cfg.folders:
            if not isinstance(folder, dict):
                continue
            if os.path.normcase(str(folder.get("path", ""))) == os.path.normcase(root):
                return str(folder.get("name") or os.path.basename(root) or root)
        return os.path.basename(root.rstrip("\\/")) or root

    @Property(str, notify=versionsChanged)
    def selectedFolderPath(self) -> str:
        return self.cfg.selected_folder or ""

    @Property(str, notify=versionsChanged)
    def selectedFolderName(self) -> str:
        path = self.cfg.selected_folder or ""
        for f in self.cfg.folders:
            if os.path.normcase(f.get("path", "")) == os.path.normcase(path):
                return f.get("name", "") or os.path.basename(path)
        return os.path.basename(path) if path else "未选择"

    @Property(str, notify=versionsChanged)
    def selectedVersionId(self) -> str:
        return self.cfg.selected_version or ""

    @Property(str, notify=versionsChanged)
    def selectedVersionTitle(self) -> str:
        ver = self.current_version()
        return ver.name if ver else "未选择版本"

    @Property(str, notify=versionsChanged)
    def selectedVersionSubtitle(self) -> str:
        ver = self.current_version()
        if ver is None:
            return "请先选择一个游戏版本"
        return ver.subtitle()

    @Property(str, notify=versionsChanged)
    def selectedVersionIcon(self) -> str:
        ver = self.current_version()
        return ver.icon_name() if ver else "cube_grass"

    @Property(bool, notify=versionsChanged)
    def selectedVersionInstalled(self) -> bool:
        ver = self.current_version()
        return bool(ver and ver.installed and ver.path)

    @Property(str, notify=accountsChanged)
    def accountName(self) -> str:
        acc = self.current_account()
        return acc.name if acc else "未添加账号"

    @Property(str, notify=accountsChanged)
    def accountKind(self) -> str:
        acc = self.current_account()
        return acc.kind if acc else "offline"

    @Property(str, notify=accountsChanged)
    def accountAvatar(self) -> str:
        acc = self.current_account()
        return "image://avatar/%s?size=64" % (acc.name if acc else "Steve")

    @Property("QVariantList", notify=accountsChanged)
    def accounts(self) -> List[Dict]:
        out = []
        for item in self.cfg.accounts:
            acc = core_accounts.from_dict(item)
            out.append({"name": acc.name, "kind": acc.kind,
                        "display": core_accounts.display(acc)})
        return out

    @Property(int, notify=accountsChanged)
    def accountIndex(self) -> int:
        name = self.cfg.selected_account
        for i, item in enumerate(self.cfg.accounts):
            if item.get("name") == name:
                return i
        return 0

    @Property(int, notify=versionsChanged)
    def totalVersionCount(self) -> int:
        return (self._installable_model.count + self._normal_model.count
                + self._uncommon_model.count)

    # ------------------------------------------------------------ QML 列表模型
    # 注意: 必须是 Qt 属性, 普通 Python 属性在 QML 中访问不到
    @Property(QObject, constant=True)
    def folderModel(self):  # noqa: N802
        return self._folder_model

    @Property(QObject, constant=True)
    def installableModel(self):  # noqa: N802
        """真实存在的、带 Mod 加载器的已安装版本。"""
        return self._installable_model

    @Property(QObject, constant=True)
    def catalogModel(self):  # noqa: N802
        """还没安装的 Mod 加载器(从下载目录里来, 点了会去安装)。"""
        return self._catalog_model

    @Property(QObject, constant=True)
    def normalModel(self):  # noqa: N802
        return self._normal_model

    @Property(QObject, constant=True)
    def uncommonModel(self):  # noqa: N802
        return self._uncommon_model

    @Property(QObject, constant=True)
    def modModel(self):  # noqa: N802
        return self._mod_model

    @Property(QObject, constant=True)
    def javaModel(self):  # noqa: N802
        return self._java_model

    # ================================================================ 版本与文件夹
    def root(self) -> str:
        return self.cfg.selected_folder or core_paths.official_minecraft_dir()

    def current_version(self) -> Optional[core_versions.VersionInfo]:
        vid = self.cfg.selected_version
        for ver in self._versions + self._installable:
            if ver.id == vid:
                return ver
        return None

    def current_account(self):
        for item in self.cfg.accounts:
            if item.get("name") == self.cfg.selected_account:
                return core_accounts.from_dict(item)
        if self.cfg.accounts:
            return core_accounts.from_dict(self.cfg.accounts[0])
        return core_accounts.offline("Steve")

    def _folder_rows(self) -> List[Dict]:
        rows = []
        current = os.path.normcase(self.cfg.selected_folder or "")
        for f in self.cfg.folders:
            path = f.get("path", "")
            rows.append({"name": f.get("name") or os.path.basename(path),
                         "path": path,
                         "active": os.path.normcase(path) == current})
        return rows

    def _version_row(self, ver: core_versions.VersionInfo) -> Dict:
        name = self.cfg.get("version_names.%s" % ver.id, "") or ver.name
        desc = self.cfg.get("version_descriptions.%s" % ver.id, "") or ver.description
        subtitle = ver.subtitle()
        note = ver.note or ""
        if note and note == subtitle:
            note = ""      # 避免与副标题重复显示
        return {
            "versionId": ver.id,
            "name": name,
            "subtitle": subtitle,
            "icon": ver.icon_name(),
            "installed": bool(ver.installed),
            "source": ver.source,
            "size": core_paths.human_size(ver.size_bytes) if ver.size_bytes else "",
            "kind": ver.kind,
            "mcVersion": ver.mc_version,
            "loader": ver.loader,
            "loaderVersion": ver.loader_version,
            "note": note,
            "description": desc,
            "favorite": self.cfg.is_favorite(ver.id),
            "search": " ".join([ver.id, name, ver.mc_version, ver.loader, ver.kind]),
        }

    @Slot()
    def reloadVersions(self) -> None:
        """重新扫描已安装版本(在后台线程扫描, 避免卡住界面动画)。"""
        # 短时间内重复请求(比如连续开关版本选择)直接跳过, 免得白扫一遍
        now = time.time()
        if now - self._last_scan_at < 1.5 and self._versions:
            return
        self._last_scan_at = now
        self._folder_model.set_rows(self._folder_rows())
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_pending = True
            return
        self.setStatus("正在扫描已安装版本…")
        self._scan_worker = VersionScanWorker(self.root(), self)
        self._scan_worker.scanned.connect(self._on_versions_scanned)
        self._scan_worker.start()

    @Slot()
    def refreshVersions(self) -> None:
        """强制重新扫描版本(进入版本选择页时用, 不做节流)。"""
        self._last_scan_at = 0.0
        self.reloadVersions()

    @Property(bool, notify=versionsChanged)
    def scanning(self) -> bool:
        """是否正在后台扫描版本。"""
        running = self._scan_worker is not None and self._scan_worker.isRunning()
        return bool(running or self._scan_pending)

    @Slot(object)
    def _on_versions_scanned(self, installed) -> None:
        self._apply_versions(list(installed or []))
        if self._scan_pending:
            self._scan_pending = False
            self.reloadVersions()
        else:
            self.setStatus("已加载 %d 个已安装版本" % len(self._versions))

    def _apply_versions(self, installed: List[core_versions.VersionInfo]) -> None:
        # 只显示真正装了的版本。示例数据仅在显式打开 use_demo_data 时(测试/截图)使用。
        self._demo_mode = False
        if not installed and bool(self.cfg.get("use_demo_data", False)):
            installed = core_versions.demo_installed()
            self._demo_mode = True

        catalog = core_versions.catalog_installable()
        installed_ids = {v.id for v in installed}
        for ver in catalog:
            if ver.id in installed_ids:
                ver.installed = True

        groups = core_versions.group_versions(installed)
        self._versions = installed
        self._installable = catalog

        # 先定好当前版本, 再生成行(否则列表里的选中态与删除按钮不会显示)
        if not self.cfg.selected_version and installed:
            self.cfg.set("selected_version", installed[0].id, autosave=False)
            self.cfg.save()

        # 「含 Mod 的版本」只列真实存在的版本文件; 还没有安装的加载器单独放一边
        not_installed = [v for v in catalog if not v.installed]
        self._normal_model.set_rows([self._version_row(v) for v in groups["normal"]])
        self._uncommon_model.set_rows([self._version_row(v) for v in groups["uncommon"]])
        self._installable_model.set_rows([self._version_row(v) for v in groups["modded"]])
        self._catalog_model.set_rows([self._version_row(v) for v in not_installed])

        self._folder_model.set_rows(self._folder_rows())
        self.versionsChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self.reloadVersions()
        self.reloadMods()
        self.detectJava()
        self.setStatus("已加载 %d 个已安装版本" % len(self._versions))
        self.accountsChanged.emit()

    @Slot(int)
    def selectFolder(self, index: int) -> None:
        rows = self._folder_rows()
        if 0 <= index < len(rows):
            self.cfg.set("selected_folder", rows[index]["path"])
            self.cfg.set("selected_version", "")
            self.reloadVersions()
            self.toastRequested.emit("已切换到文件夹: %s" % rows[index]["name"])

    @Slot(str)
    def addFolderPath(self, path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        self.cfg.add_folder(os.path.basename(path) or path, path)
        self.cfg.set("selected_folder", path)
        self.reloadVersions()
        self.toastRequested.emit("已添加文件夹: %s" % os.path.basename(path))

    @Slot(str)
    def createMinecraftFolderAt(self, parent_dir: str) -> None:
        if not parent_dir:
            return
        target = os.path.join(parent_dir, ".minecraft")
        try:
            os.makedirs(os.path.join(target, "versions"), exist_ok=True)
        except OSError as exc:
            self.messageRequested.emit("新建失败", "无法创建文件夹：\n%s" % exc, "error")
            return
        self.cfg.add_folder(os.path.basename(parent_dir) or ".minecraft", target)
        self.cfg.set("selected_folder", target)
        self.reloadVersions()
        self.messageRequested.emit("创建成功", "已新建 .minecraft 文件夹：\n%s" % target, "info")

    @Slot(str)
    def importPackPath(self, zip_path: str) -> None:
        if not zip_path:
            return
        base = os.path.splitext(os.path.basename(zip_path))[0]
        parent = os.path.dirname(zip_path)
        target = os.path.join(parent, base)
        try:
            os.makedirs(target, exist_ok=True)
            name = packexport.import_pack(zip_path, target)
        except Exception as exc:  # noqa: BLE001
            self.messageRequested.emit("导入失败", str(exc), "error")
            return
        self.cfg.add_folder(name or base, target)
        self.cfg.set("selected_folder", target)
        self.reloadVersions()
        self.messageRequested.emit("导入完成", "整合包已导入到：\n%s" % target, "info")

    @Slot(str)
    def selectVersion(self, version_id: str) -> None:
        if not version_id:
            return
        self.cfg.set("selected_version", version_id)
        self.versionsChanged.emit()
        self.reloadMods()

    # ================================================================ 账号
    @Slot(int)
    def setAccountIndex(self, index: int) -> None:
        items = self.cfg.accounts
        if 0 <= index < len(items):
            self.cfg.set("selected_account", items[index].get("name", ""))
            self.accountsChanged.emit()

    @Slot(str)
    def addOfflineAccount(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        acc = core_accounts.offline(name)
        self.cfg.add_account(core_accounts.to_dict(acc))
        self.cfg.set("selected_account", name)
        self.accountsChanged.emit()
        self.toastRequested.emit("已添加离线账号: %s" % name)

    @Slot(int)
    def removeAccount(self, index: int) -> None:
        items = self.cfg.accounts
        if 0 <= index < len(items):
            removed = items.pop(index)
            self.cfg.set("accounts", items)
            if self.cfg.selected_account == removed.get("name") and items:
                self.cfg.set("selected_account", items[0].get("name", ""))
            self.accountsChanged.emit()

    @Slot()
    def loginMicrosoft(self) -> None:
        self.messageRequested.emit(
            "正版登录",
            "本启动器未内置微软 OAuth 登录流程（需要自行申请 Azure 应用并实现设备码登录）。\n"
            "当前请使用「离线」账号启动游戏。",
            "warn")

    # ================================================================ 版本详情/管理
    @Slot(str, result="QVariantMap")
    def versionInfo(self, version_id: str) -> Dict:
        ver = None
        for item in self._versions + self._installable:
            if item.id == version_id:
                ver = item
                break
        if ver is None:
            return {}
        row = self._version_row(ver)
        row["path"] = ver.path
        row["releaseTime"] = ver.release_time
        row["isolation"] = "开启" if self.isolated() else "关闭"
        return row

    @Slot(str, result="QVariantMap")
    def folderInfo(self, version_id: str) -> Dict:
        """返回该版本涉及的各个目录(用于「快捷方式」按钮)。"""
        ver = None
        for item in self._versions:
            if item.id == version_id:
                ver = item
                break
        root = self.root()
        if ver is None or not ver.path:
            return {"version": "", "saves": os.path.join(root, "saves"),
                    "mods": os.path.join(root, "mods"),
                    "screenshots": os.path.join(root, "screenshots")}
        isolated = self.isolated(version_id)
        return {
            "version": ver.path,
            "saves": os.path.join(ver.path, "saves") if isolated else os.path.join(root, "saves"),
            "mods": os.path.join(ver.path, "mods") if isolated else os.path.join(root, "mods"),
            "screenshots": (os.path.join(ver.path, "screenshots") if isolated
                            else os.path.join(root, "screenshots")),
        }

    def isolated(self, version_id: str = "") -> bool:
        mode = self.cfg.get("launch.isolation", "follow")
        if mode == "follow":
            mode = self.cfg.get("launch.default_isolation", "open")
        if version_id:
            local = self.cfg.get("version_isolation.%s" % version_id, "follow")
            if local != "follow":
                mode = local
        return mode == "open"

    @Slot(str)
    def openFolder(self, kind: str) -> None:
        vid = self.cfg.selected_version
        info = self.folderInfo(vid)
        path = {"version": info.get("version", ""), "saves": info.get("saves", ""),
                "mods": info.get("mods", ""), "screenshots": info.get("screenshots", "")}.get(kind, "")
        if not path:
            self.messageRequested.emit("无法打开", "该版本尚未安装到磁盘，没有对应文件夹。", "warn")
            return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        if not core_paths.open_in_explorer(path):
            self.messageRequested.emit("无法打开", "打开文件夹失败：\n%s" % path, "error")

    @Slot(str, str, str, str, str)
    def startResourceDownload(self, kind: str, url: str, filename: str, game_dir: str,
                              name: str) -> None:
        """下载社区资源 / 安装整合包 —— 与安装游戏用同一套任务系统(任务管理页 + 右下圆标)。"""
        kind_key = str(kind or "mod").lower()
        source = str(self.cfg.get("download.source") or "official")
        label = {"mod": "Mod", "modpack": "整合包", "datapack": "数据包",
                 "resourcepack": "资源包", "shader": "光影包"}.get(kind_key, "资源")
        title = ("安装整合包 %s" % (name or filename)) if kind_key == "modpack" \
            else ("下载%s %s" % (label, filename or name))
        steps = MODPACK_STEPS if kind_key == "modpack" else RESOURCE_STEPS
        worker = ResourceDownloadWorker(kind_key, url, filename, game_dir, self.root(),
                                        name, source, self)
        self._resource_worker = worker
        task = self._new_task(title, "download", steps, worker)
        worker.progress.connect(lambda text, pct, t=task: self._on_task_progress(t, text, pct))
        worker.phase.connect(lambda pid, pct, text, t=task: self._on_task_phase(t, pid, pct, text))
        # 落盘路径按"任务 id"记录: 多个下载并行时不会串台,
        # 也不会被任务刷新时的字典重建弄丢
        worker.saved.connect(
            lambda path, t=task: self._resource_paths.__setitem__(id(t), str(path or "")))
        worker.succeeded.connect(lambda msg, t=task: self._on_task_done_msg(t, msg))
        worker.failed.connect(lambda msg, t=task: self._on_task_failed(msg, t))
        worker.start()
        self.toastRequested.emit("已开始%s，可在右下角查看进度" % title)

    @Slot(object, str)
    def _on_task_done_msg(self, task: Dict, message: str) -> None:
        self._finish_task(task, "done", "已完成")
        if message:
            self.appendLog("[任务] %s" % message)
            self.toastRequested.emit(message)
        if str(task.get("kind")) == "download":
            self.reloadVersions()
            # 下载类任务完成后: 把落盘路径给用户(自动复制到剪贴板, 弹窗里也会显示)
            path = str(self._resource_paths.pop(id(task), "") or "")
            if not path and "已下载到" in str(message):
                path = str(message).split("已下载到", 1)[1].strip()
            if path:
                self.copyToClipboard(path)
            self.resourceDownloaded.emit(str(message), path)

    @Slot(str)
    def _on_resource_saved(self, path: str) -> None:
        self._resource_path = str(path or "")

    @Slot(str)
    def openPath(self, path: str) -> None:  # noqa: N802
        """在文件管理器里定位到某个文件/文件夹。"""
        target = str(path or "").strip()
        if not target:
            return
        try:
            if os.path.isfile(target) and os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
                return
            folder = target if os.path.isdir(target) else os.path.dirname(target)
            if folder and not core_paths.open_in_explorer(folder):
                self.messageRequested.emit("打不开文件夹", folder, "warn")
        except Exception as exc:  # noqa: BLE001
            self.messageRequested.emit("打不开文件夹", str(exc), "warn")

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:  # noqa: N802
        """把文本放进系统剪贴板(路径太长不好手打)。"""
        try:
            from PySide6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(text or ""))
                self.toastRequested.emit("已复制到剪贴板")
        except Exception:  # noqa: BLE001
            pass

    @Slot(str, str)
    def installOptifine(self, mc_version: str, version: str) -> None:
        """下载并启动 OptiFine 官方安装器(它自带 GUI)。"""
        try:
            core_install.run_optifine_installer(
                mc_version, version, self.root(), self.cfg,
                progress_cb=lambda pct, text: self.setStatus(text))
        except Exception as exc:  # noqa: BLE001
            self.messageRequested.emit("OptiFine 安装", str(exc), "warn")
            return
        self.messageRequested.emit(
            "OptiFine 安装",
            "已启动 OptiFine 安装器窗口，请在里面点一次 Install。\n"
            "装好后回到启动器，在「版本选择」里就能看到 %s-OptiFine_%s，"
            "它只带原版 + OptiFine（OptiFine 不能和 Forge/Fabric 同时装在一个版本里）。"
            % (mc_version, version), "info")
        self.toastRequested.emit("请在弹出的 OptiFine 安装器里点 Install")

    def _inheriting_versions(self, version_id: str) -> List[str]:
        """列出仍在声明继承 ``version_id`` 的其它版本(A)。

        我们自己安装的版本现在都会自包含(`make_self_contained` ✓), 所以正常情况下
        这里是空的; 命中的通常是**外部导入**的版本(PCL2/HMCL/整合包带来的),
        它们删/改父版本后就会启动不了 —— 这时给用户一个明确提示, 而不是静默失效。
        """
        target = str(version_id or "").strip()
        if not target:
            return []
        root = os.path.join(str(self.root()), "versions")
        result = []  # type: List[str]
        try:
            names = os.listdir(root)
        except OSError:
            return result
        for name in names:
            if name == target:
                continue
            path = os.path.join(root, name, name + ".json")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    data = json.load(handle)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(data, dict) and str(data.get("inheritsFrom") or "") == target:
                result.append(name)
        return result

    @Slot(str, str)
    def renameVersion(self, version_id: str, new_name: str) -> None:
        """改版本名: **磁盘上的目录/json 一起改名**, 并同步显示名。"""
        new_name = (new_name or "").strip()
        if not version_id or not new_name:
            return
        error = ""
        for ch in '\\/:*?"<>|':
            if ch in new_name:
                error = "名称不能包含 \\ / : * ? \" < > | 这些符号"
        if new_name in (".", "..") or new_name.endswith("."):
            error = "名称不合法"
        root = self.root()
        if not error and os.path.normcase(new_name) != os.path.normcase(version_id):
            if os.path.isdir(os.path.join(root, "versions", new_name)):
                error = "已经存在同名版本，请换一个名字"
        if not error and os.path.normcase(new_name) != os.path.normcase(version_id):
            renamed = ""
            try:
                renamed = core_install.rename_version(root, version_id, new_name)
            except Exception:  # noqa: BLE001
                renamed = version_id
            if renamed == version_id:
                error = "改名失败（可能有文件被占用），请关掉游戏后重试"
        if error:
            self.messageRequested.emit("无法修改版本名", error, "warn")
            return
        # A: 改名会让"仍在继承它的版本"失效 —— 我们自己装的版本已自包含(不会命中),
        # 只有**外部导入**的版本(PCL2/HMCL/整合包带来的)才会留下 inheritsFrom 引用。
        orphans = self._inheriting_versions(version_id)
        if orphans:
            self.messageRequested.emit(
                "已改名，但有版本仍然依赖它",
                "「%s」已被改名为「%s」，但下面这些版本仍然声明继承它，"
                "现在会启动不了：\n  %s\n\n建议重新安装这些版本，或把它们也做成独立副本。"
                % (version_id, new_name, "\n  ".join(orphans[:8])), "warn")
        self.cfg.set("version_names.%s" % new_name, new_name)
        self.cfg.set("selected_version", new_name, autosave=False)
        self.cfg.save(force=True)
        self.reloadVersions()
        self.toastRequested.emit("版本已改名为 %s" % new_name)

    @Slot(str, str)
    def setVersionDescription(self, version_id: str, text: str) -> None:
        if not version_id:
            return
        self.cfg.set("version_descriptions.%s" % version_id, text or "")
        self.reloadVersions()
        self.toastRequested.emit("版本描述已保存")

    @Slot(str)
    def toggleFavorite(self, version_id: str) -> None:
        state = self.cfg.toggle_favorite(version_id)
        self.reloadVersions()
        self.toastRequested.emit("已加入收藏夹" if state else "已移出收藏夹")

    @Slot(str)
    def requestDeleteVersion(self, version_id: str) -> None:
        self._pending_action = "delete_version:%s" % version_id
        message = ("确定要删除版本 %s 吗？\n该版本的整个文件夹都会被删除，操作不可恢复。"
                   % version_id)
        # A: 删除前检查是否还有版本声明继承它(正常情况下为空 —— 自己装的都自包含了)
        orphans = self._inheriting_versions(version_id)
        if orphans:
            message += ("\n\n⚠️ 注意：下面这些版本仍然声明继承它，删除后将无法启动：\n  %s"
                        % "\n  ".join(orphans[:8]))
        self.confirmRequested.emit("删除版本", message)

    @Slot()
    def completeFiles(self) -> None:
        ver = self.current_version()
        if ver is None or not ver.path:
            self.messageRequested.emit("补全文件", "示例数据无法补全，请先安装真实版本。", "warn")
            return
        self.startInstall("vanilla", ver.mc_version or ver.id)

    @Slot(str)
    def exportStartScript(self, version_id: str) -> None:
        ver = None
        for item in self._versions:
            if item.id == version_id:
                ver = item
                break
        if ver is None or not ver.path:
            self.messageRequested.emit("导出启动脚本", "该版本尚未安装，无法导出启动脚本。", "warn")
            return
        try:
            plan = core_launch.build_launch(self.root(), ver.id, self.current_account(),
                                            self.cfg, self.java_path())
        except Exception as exc:  # noqa: BLE001
            self.messageRequested.emit("导出失败", str(exc), "error")
            return
        out = os.path.join(core_paths.app_home(), "%s.bat" % core_paths.safe_name(ver.id))
        try:
            core_paths.ensure_dir(os.path.dirname(out))
            with open(out, "w", encoding="gbk", errors="ignore") as fh:
                fh.write("@echo off\r\n")
                fh.write('cd /d "%s"\r\n' % plan.cwd)
                fh.write(" ".join('"%s"' % a if " " in a else a for a in plan.command))
                fh.write("\r\npause\r\n")
        except OSError as exc:
            self.messageRequested.emit("导出失败", str(exc), "error")
            return
        self.messageRequested.emit("导出完成", "启动脚本已保存到：\n%s" % out, "info")

    # ================================================================ Mod 管理
    def mods_dir(self) -> str:
        ver = self.current_version()
        if ver is None or not ver.path:
            return os.path.join(self.root(), "mods")
        return core_mods.mods_dir_for(ver.path, self.root(), self.isolated(ver.id))

    @Slot()
    def reloadMods(self) -> None:
        rows = []
        for mod in core_mods.list_mods(self.mods_dir()):
            rows.append({"fileName": mod.file_name, "name": mod.name,
                         "subtitle": mod.subtitle(), "enabled": mod.enabled,
                         "size": core_paths.human_size(mod.size_bytes),
                         "selected": False, "path": mod.path,
                         "search": mod.file_name + " " + mod.name})
        self._mod_model.set_source(rows)

    @Slot(str)
    def filterMods(self, text: str) -> None:
        self._mod_model.set_filter(text)

    @Slot()
    def openModsFolder(self) -> None:
        path = self.mods_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        if not core_paths.open_in_explorer(path):
            self.messageRequested.emit("无法打开", "打开 Mod 文件夹失败：\n%s" % path, "error")

    @Slot(str)
    def installModFromPath(self, path: str) -> None:
        if not path:
            return
        mod = core_mods.install_mod(path, self.mods_dir())
        if mod is None:
            self.messageRequested.emit("安装失败", "无法复制 Mod 文件：\n%s" % path, "error")
            return
        self.reloadMods()
        self.toastRequested.emit("已安装 Mod: %s" % mod.file_name)

    @Slot(int)
    def toggleMod(self, index: int) -> None:
        row = self._mod_model.at(index)
        if not row:
            return
        mod = core_mods.ModInfo(file_name=row["fileName"], path=row["path"],
                                name=row["name"], enabled=bool(row["enabled"]))
        core_mods.set_enabled(mod, not mod.enabled)
        self.reloadMods()

    @Slot(int, bool)
    def setModSelected(self, index: int, value: bool) -> None:
        self._mod_model.update_row(index, {"selected": bool(value)})

    @Slot(bool)
    def selectAllMods(self, value: bool) -> None:
        for i in range(self._mod_model.count):
            self._mod_model.update_row(i, {"selected": bool(value)})

    @Slot(str)
    def batchMods(self, operation: str) -> None:
        rows = self._mod_model.rows()
        targets = [r for r in rows if r.get("selected")]
        if not targets:
            self.toastRequested.emit("请先勾选要操作的 Mod")
            return
        if operation == "delete":
            self._pending_action = "batch_delete_mods"
            self.confirmRequested.emit("删除 Mod", "确定要删除选中的 %d 个 Mod 吗？" % len(targets))
            return
        for row in targets:
            mod = core_mods.ModInfo(file_name=row["fileName"], path=row["path"],
                                    name=row["name"], enabled=bool(row["enabled"]))
            core_mods.set_enabled(mod, operation == "enable")
        self.reloadMods()
        self.toastRequested.emit("已%s %d 个 Mod" % ("启用" if operation == "enable" else "禁用",
                                                    len(targets)))

    def _batch_delete_mods(self) -> None:
        rows = self._mod_model.rows()
        for row in [r for r in rows if r.get("selected")]:
            core_mods.delete_mod(core_mods.ModInfo(file_name=row["fileName"], path=row["path"],
                                                   name=row["name"]))
        self.reloadMods()
        self.toastRequested.emit("已删除选中的 Mod")

    @Slot()
    def downloadModHint(self) -> None:
        self.messageRequested.emit(
            "下载 Mod",
            "下载 Mod 依赖「社区资源」功能，按需求本次未实现。\n"
            "可以点击「从文件安装」选择本地已下载的 .jar。",
            "info")

    # ================================================================ 导出整合包
    @Slot(result="QVariantMap")
    def defaultExportOptions(self) -> Dict:
        ver = self.current_version()
        return {
            "pack_name": ver.id if ver else "整合包",
            "pack_version": "1.0.0",
            "mods": True, "mod_configs": True, "resourcepacks": True,
            "screenshots": False, "saves": False, "servers": False,
            "launcher_config": True, "game_settings": True,
        }

    @Slot("QVariantMap", str)
    def startExport(self, options: Dict, out_path: str) -> None:
        ver = self.current_version()
        if ver is None or not ver.path:
            self.messageRequested.emit("导出失败", "示例数据无法导出，请先安装真实版本。", "warn")
            return
        worker = ExportWorker(self.root(), ver.id, out_path, dict(options or {}), self)
        task = self._new_task("导出整合包 %s" % ver.id, "export", EXPORT_STEPS, worker)
        self._export_worker = worker
        worker.progress.connect(lambda text, pct, t=task: self._on_task_progress(t, text, pct))
        worker.succeeded.connect(lambda path, t=task: self._on_export_done(path, t))
        worker.failed.connect(lambda msg, t=task: self._on_task_failed(msg, t))
        worker.start()
        self.toastRequested.emit("已开始导出整合包")

    def _on_export_done(self, path: str, task: Optional[Dict] = None) -> None:
        if task is not None:
            self._finish_task(task, "done", "已完成")
        self.messageRequested.emit("导出完成", "整合包已保存到：\n%s" % path, "info")

    # ================================================================ 安装/下载
    @Slot(str, str, str, str)
    def startInstall(self, mode: str, mc_version: str, loader_version: str = "",
                     target_name: str = "") -> None:
        """开始安装。``target_name`` 是用户自定义的版本名(留空用默认命名)。"""
        if not mc_version:
            return
        root = self.root()
        try:
            core_paths.ensure_dir(root)
        except OSError:
            pass
        worker = InstallWorker(mode, mc_version, root, self.cfg, loader_version, target_name, self)
        label = {"forge": "Forge", "neoforge": "NeoForge", "fabric": "Fabric",
                 "quilt": "Quilt"}.get(str(mode).lower(), "")
        title = "%s%s 安装" % (mc_version, (" " + label) if label else "")
        task = self._new_task(title, "install", INSTALL_STEPS, worker)
        self._install_worker = worker
        worker.progress.connect(lambda text, pct, t=task: self._on_task_progress(t, text, pct))
        worker.phase.connect(lambda pid, pct, text, t=task: self._on_task_phase(t, pid, pct, text))
        worker.succeeded.connect(lambda vid, t=task: self._on_install_done(vid, t))
        worker.failed.connect(lambda msg, t=task: self._on_task_failed(msg, t))
        worker.start()
        self.setStatus("正在安装 %s" % mc_version)
        self.toastRequested.emit("已开始安装 %s，可在右下角查看进度" % title)

    @Slot(str, result=bool)
    def versionExists(self, name: str) -> bool:  # noqa: N802
        """版本目录里是否已经有这个名字(安装前查重名用)。"""
        text = str(name or "").strip()
        if not text:
            return False
        try:
            return os.path.isdir(os.path.join(self.root(), "versions", text))
        except OSError:
            return False

    @Slot()
    def cancelTask(self) -> None:
        cancelled = False
        for worker in (self._install_worker, self._export_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                cancelled = True
        if cancelled:
            for task in self._tasks:
                if task.get("state") == "running":
                    task["stateText"] = "正在取消…"
                    self._update_task(task)

    @Slot(str)
    def installCatalogVersion(self, version_id: str) -> None:
        """安装「可安装 Mod」列表里的条目。"""
        target = None
        for ver in self._installable:
            if ver.id == version_id:
                target = ver
                break
        if target is None:
            return
        loader = (target.loader or "").lower()
        if loader == "fabric":
            self.startInstall("fabric", target.mc_version, target.loader_version)
            return
        if loader in ("forge", "neoforge"):
            self.messageRequested.emit(
                "需要手动安装",
                "%s 的自动安装尚未实现。\n\n"
                "请先点击「常规版本」安装对应的原版 %s，然后使用 %s 官方安装器安装到\n%s\n"
                "安装完成后回到这里刷新列表即可看到该版本。"
                % (target.loader, target.mc_version, target.loader, self.root()),
                "info")
            return
        self.messageRequested.emit(
            "暂不支持",
            "「%s」是一个整合包条目，自动下载整合包需要社区资源支持（本次未实现）。\n"
            "你可以用「导入整合包」导入本地的 .zip 整合包。" % target.name,
            "info")

    def _on_install_done(self, version_id: str, task: Optional[Dict] = None) -> None:
        if task is not None:
            self._finish_task(task, "done", "已完成")
        self.reloadVersions()
        self.setStatus("安装完成: %s" % version_id)
        self.messageRequested.emit("安装完成", "版本 %s 已安装完成。" % version_id, "info")

    def _on_task_failed(self, message: str, task: Optional[Dict] = None) -> None:
        state = "cancelled" if "取消" in str(message) else "failed"
        if task is not None:
            self._finish_task(task, state, "已取消" if state == "cancelled" else "失败")
        self.setStatus("任务失败" if state == "failed" else "任务已取消")
        self.messageRequested.emit("任务失败" if state == "failed" else "已取消",
                                   str(message), "error" if state == "failed" else "info")

    @Slot(str)
    def appendLog(self, text: str) -> None:
        self._log_lines.append(str(text))
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        self.logAppended.emit(str(text))

    @Property("QVariantList", notify=launchStateChanged)
    def logLines(self) -> List[str]:
        return list(self._log_lines)

    @Slot()
    def openGameLog(self) -> None:
        self.windowRequested.emit("log")

    @Slot()
    def clearLog(self) -> None:
        self._log_lines = []
        self.logAppended.emit("")

    # ================================================================ 通用
    @Slot(str)
    def setStatus(self, text: str) -> None:
        self._status = str(text)
        self.statusChanged.emit()

    @Slot()
    def confirmPendingYes(self) -> None:
        action = self._pending_action
        self._pending_action = ""
        if not action:
            return
        if action.startswith("delete_version:"):
            self._delete_version(action.split(":", 1)[1])
        elif action == "batch_delete_mods":
            self._batch_delete_mods()
        elif action == "launch_anyway":
            self.doLaunch()

    @Slot()
    def confirmPendingNo(self) -> None:
        self._pending_action = ""

    def _delete_version(self, version_id: str) -> None:
        """删除版本(整个版本文件夹)。

        关键点(修 bug): 以前只要"找不到 VersionInfo"或"path 为空"就直接 return,
        结果既不发 versionDeleted 信号(界面不跳回启动页), 也不 reloadVersions
        (版本选择列表、下载页的"已安装"标记都不更新), 而文件夹还留在磁盘上
        (重启启动器后依然显示已安装)。现在:
          * 找不到就用 `versions/<id>` 兜底定位文件夹;
          * 文件夹本来就不存在 / 已经删掉, 也照样刷新并通知界面。
        """
        version_id = str(version_id or "").strip()
        if not version_id:
            return
        ver = None
        for item in list(self._versions) + list(self._installable):
            if item.id == version_id:
                ver = item
                break
        root = self.root()
        folder = (ver.path if ver is not None and ver.path
                  else os.path.join(root, "versions", version_id))

        removed = False
        if os.path.isdir(folder):
            import shutil
            try:
                shutil.rmtree(folder)
                removed = True
            except OSError as exc:
                self.messageRequested.emit("删除失败", "%s\n%s" % (folder, exc), "error")
                return

        if self.cfg.selected_version == version_id:
            self.cfg.set("selected_version", "")
        self.reloadVersions()
        self.toastRequested.emit("已删除版本 %s" % version_id if removed
                                 else "版本 %s 的文件夹已不存在，已刷新列表" % version_id)
        # 通知界面: 该版本已被删除(正看着它的设置页时要退回主页面)
        self.versionDeleted.emit(version_id)
