"""下载页(原版游戏)后端: 版本列表 + 安装。"""
from __future__ import annotations

import os
from typing import Dict, List

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from ..core import remote as core_remote
from .models import DictListModel

VANILLA_ROLES = ["versionId", "subtitle", "time", "kind", "icon", "installed", "search"]


def _format_time(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:  # noqa: BLE001
        return text[:16].replace("T", " ")


class ManifestWorker(QThread):
    loaded = Signal(object)

    def __init__(self, cfg, force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.force = force

    def run(self) -> None:  # noqa: D102
        try:
            manifest = core_remote.get_manifest(self.cfg, force=self.force)
        except Exception:  # noqa: BLE001
            manifest = {}
        self.loaded.emit(manifest or {})


class LoaderQueryWorker(QThread):
    """后台查询某个 MC 版本可用的模组加载器版本(Forge/Fabric/NeoForge/Quilt)。"""

    done = Signal(str, object)          # mc 版本, {loader: [版本...]}

    def __init__(self, mc_version: str, parent=None) -> None:
        super().__init__(parent)
        self.mc_version = str(mc_version)

    def run(self) -> None:  # noqa: D102
        from ..core import remote
        result = {}  # type: Dict[str, List[str]]
        for key in ("forge", "fabric", "neoforge", "quilt", "optifine"):
            try:
                if key == "forge":
                    result[key] = remote.forge_versions(self.mc_version)[:60]
                elif key == "fabric":
                    result[key] = [v["version"] for v in
                                   remote.fabric_loader_versions(self.mc_version)][:60]
                elif key == "neoforge":
                    result[key] = remote.neoforge_versions(self.mc_version)[:60]
                elif key == "optifine":
                    result[key] = remote.optifine_versions(self.mc_version)[:60]
                else:
                    result[key] = [v["version"] for v in
                                   remote.quilt_loader_versions(self.mc_version)][:60]
            except Exception:  # noqa: BLE001
                result[key] = []
        self.done.emit(self.mc_version, result)


class DownloadBackend(QObject):
    changed = Signal()
    loadingChanged = Signal()
    loaderChanged = Signal()

    def __init__(self, cfg, launcher, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.launcher = launcher
        self._release_model = DictListModel(VANILLA_ROLES, self)
        self._snapshot_model = DictListModel(VANILLA_ROLES, self)
        self._old_model = DictListModel(VANILLA_ROLES, self)
        self._april_model = DictListModel(VANILLA_ROLES, self)
        self._latest_release: Dict = {}
        self._latest_snapshot: Dict = {}
        self._entries: Dict = {}
        self._loading = False
        self._worker = None  # type: ignore[assignment]
        # ---- 加载器(安装版本时选择 Forge/Fabric/NeoForge/Quilt)
        self._loader_worker = None
        self._loader_mc = ""
        self._loader_rows: List[Dict] = []

    # ================================================================ 加载器
    @Property("QVariantList", notify=loaderChanged)
    def loaderRows(self):  # noqa: N802
        """当前查询的 MC 版本对应的加载器行。"""
        return self._loader_rows

    @Property(str, notify=loaderChanged)
    def loaderVersion(self) -> str:
        """正在查询的 MC 版本。"""
        return self._loader_mc

    @Slot(str)
    def queryLoaders(self, mc_version: str) -> None:  # noqa: N802
        """查询某个 MC 版本可用的 Forge/Fabric/NeoForge/Quilt 版本。"""
        mc = str(mc_version or "").strip()
        if not mc:
            return
        # 已经有结果就不用重查(避免每次进页面都等一遍网络)
        if mc == self._loader_mc and self._loader_rows and all(
                str(r.get("state")) != "获取中..." for r in self._loader_rows):
            return
        self._loader_mc = mc
        self._loader_rows = [
            {"key": "forge", "name": "Forge", "state": "获取中...", "selected": False,
             "versions": [], "index": 0, "current": ""},
            {"key": "fabric", "name": "Fabric", "state": "获取中...", "selected": False,
             "versions": [], "index": 0, "current": ""},
            {"key": "neoforge", "name": "NeoForge", "state": "获取中...", "selected": False,
             "versions": [], "index": 0, "current": ""},
            {"key": "quilt", "name": "Quilt", "state": "获取中...", "selected": False,
             "versions": [], "index": 0, "current": ""},
            {"key": "optifine", "name": "OptiFine", "state": "需要手动安装", "selected": False,
             "versions": [], "index": 0, "current": ""},
        ]
        self.loaderChanged.emit()
        # 每次查询都用新的 worker: 旧 worker 还在跑时也不能把新请求丢掉,
        # 否则界面会一直停在「获取中...」。结果里带 mc 版本, 过期的直接忽略。
        worker = LoaderQueryWorker(mc, self)
        worker.done.connect(self._on_loaders)
        self._loader_worker = worker
        worker.start()

    @Slot(str, object)
    def _on_loaders(self, mc: str, data) -> None:
        if str(mc) != str(self._loader_mc):
            return          # 过期的查询结果, 丢掉
        if not isinstance(data, dict):
            data = {}
        rows = []
        for row in self._loader_rows:
            row = dict(row)
            key = str(row.get("key"))
            versions = [str(v) for v in (data.get(key) or [])]
            if versions:
                row["versions"] = versions
                row["state"] = "可以添加"
                row["current"] = versions[0]
                row["index"] = 0
            elif key == "optifine":
                row["state"] = "需要手动安装"
            else:
                row["state"] = "该版本不支持"
            rows.append(row)
        self._loader_rows = rows
        self.loaderChanged.emit()

    @Slot(str, int)
    def setLoaderVersion(self, key: str, index: int) -> None:  # noqa: N802
        """选择某个加载器的具体版本。"""
        rows = []
        for row in self._loader_rows:
            row = dict(row)
            if str(row.get("key")) == str(key):
                versions = row.get("versions") or []
                if 0 <= int(index) < len(versions):
                    row["index"] = int(index)
                    row["current"] = versions[int(index)]
            rows.append(row)
        self._loader_rows = rows
        self.loaderChanged.emit()

    @Slot(str, str, str)
    def installWithLoader(self, key: str, mc_version: str, target_name: str = "") -> None:
        """按选定加载器安装版本(原版会由安装器/流程自动装好)。

        ``target_name`` 是用户确认过的版本名(重命名); 留空则用默认命名。
        """
        loader = str(key or "").lower()
        mc = str(mc_version or "").strip()
        target = str(target_name or "").strip()
        if not mc:
            self.launcher.toastRequested.emit("请先填写要安装的版本")
            return
        if loader == "optifine":
            # OptiFine 只能单独安装: 下载它的安装器并启动(它自带 GUI, 点一次 Install 即可)
            version = ""
            for row in self._loader_rows:
                if str(row.get("key")) == "optifine":
                    version = str(row.get("current") or "")
            if not version:
                self.launcher.toastRequested.emit("请先获取 OptiFine 版本列表")
                return
            self.launcher.installOptifine(mc, version)
            return
        if loader == "vanilla":
            self.launcher.startInstall("vanilla", mc, "", target)
            self.launcher.toastRequested.emit("已开始安装原版 %s" % (target or mc))
            return
        version = ""
        for row in self._loader_rows:
            if str(row.get("key")) == loader:
                version = str(row.get("current") or "")
        if not version:
            self.launcher.toastRequested.emit("这个加载器还没有可用的版本，请先点「获取」")
            return
        mode = loader if loader in ("forge", "fabric", "neoforge", "quilt") else "fabric"
        self.launcher.startInstall(mode, mc, version, target)
        self.launcher.toastRequested.emit("已开始安装 %s %s" % (loader.title(), version))

    @Slot(str)
    def toggleLoader(self, key: str) -> None:  # noqa: N802
        """勾选/取消勾选某个加载器 —— **单选**: 勾上新的会自动取消旧的。

        用户要求加载器"同一时间只能选中一个"(单选语义): Forge / Fabric / NeoForge /
        Quilt / OptiFine 之间两两互斥(OptiFine 同样参与互斥)。再点一次已勾选的那个 =
        取消勾选(回到"一个都不选"); 取消时其它加载器保持原样, 不会被顺手勾上。
        """
        target = str(key or "")
        was_selected = False
        for row in self._loader_rows:
            if str(row.get("key")) == target:
                was_selected = bool(row.get("selected"))
                break
        rows = []
        for row in self._loader_rows:
            row = dict(row)
            if str(row.get("key")) == target:
                row["selected"] = not was_selected      # 再点一次 = 取消勾选
            elif not was_selected:
                row["selected"] = False                 # 选了新的 → 旧的自动取消
            rows.append(row)
        self._loader_rows = rows
        self.loaderChanged.emit()

    @Property("QVariantList", notify=loaderChanged)
    def selectedLoaders(self):  # noqa: N802
        """已勾选(且有可用版本)的加载器列表。"""
        result = []
        for row in self._loader_rows:
            if row.get("selected") and (row.get("versions") or []):
                result.append({"key": row.get("key"), "name": row.get("name"),
                               "version": row.get("current") or ""})
        return result

    @Slot(str, str, result=str)
    def defaultVersionName(self, key: str, mc_version: str) -> str:  # noqa: N802
        """按加载器给出默认版本名(用于安装前的重命名输入框)。

        默认名若已被占用(最常见: 重复安装同一个原版版本)会自动加后缀避让成 ``26.2-2``,
        否则对话框一打开默认名就是"已存在同名版本", 用户会以为改名功能坏了。
        """
        loader = str(key or "").lower()
        mc = str(mc_version or "").strip()
        label = {"forge": "Forge", "neoforge": "NeoForge", "fabric": "Fabric",
                 "quilt": "Quilt"}.get(loader, "")
        if not label:
            base = mc
        else:
            version = ""
            for row in self._loader_rows:
                if str(row.get("key")) == loader:
                    version = str(row.get("current") or "")
            if not version:
                base = "%s-%s" % (mc, label)
            else:
                base = "%s-%s_%s" % (mc, label, version)
        if not base:
            return base
        if self.validateVersionName(base) == "":
            return base
        for index in range(2, 100):
            candidate = "%s-%d" % (base, index)
            if self.validateVersionName(candidate) == "":
                return candidate
        return base

    def _version_name_taken(self, text: str) -> bool:  # noqa: N802
        """版本名是否已被占用(磁盘上的 versions/<名字> 目录)。

        ⚠️ 这里曾经一直失效: 本模块当时**没有 import os**, `os.path.isdir` 直接抛
        NameError, 又被 `except Exception: pass` 吞掉 → 重名检测形同虚设。
        现在: 补上 import os, 并且不再静默吞异常(出错要能在日志里看到)。
        """
        name = str(text or "")
        if not name:
            return False
        try:
            folder = os.path.join(str(self.launcher.root()), "versions", name)
            return bool(os.path.isdir(folder))
        except Exception as exc:  # noqa: BLE001
            print("[download] 版本重名检查失败:", type(exc).__name__, exc, flush=True)
            return False

    @Slot(str, result=str)
    def validateVersionName(self, name: str) -> str:  # noqa: N802
        """校验版本名: 返回空串表示没问题, 否则返回错误提示。"""
        text = str(name or "").strip()
        if not text:
            return "名称不能为空"
        bad = [ch for ch in '\\/:*?"<>|' if ch in text]
        if bad:
            return "名称不能包含 \\ / : * ? \" < > | 这些符号"
        if text in (".", ".."):
            return "名称不合法"
        if text.endswith("."):
            return "名称不能以点结尾"
        if self._version_name_taken(text):
            return "已经存在同名版本，请换一个名字"
        return ""

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    # ------------------------------------------------------------ QML 列表模型
    @Property(QObject, constant=True)
    def releaseModel(self):  # noqa: N802
        return self._release_model

    @Property(QObject, constant=True)
    def snapshotModel(self):  # noqa: N802
        return self._snapshot_model

    @Property(QObject, constant=True)
    def oldModel(self):  # noqa: N802
        return self._old_model

    @Property(QObject, constant=True)
    def aprilModel(self):  # noqa: N802
        return self._april_model

    @Property("QVariantMap", notify=changed)
    def latestRelease(self) -> Dict:
        return self._latest_release

    @Property("QVariantMap", notify=changed)
    def latestSnapshot(self) -> Dict:
        return self._latest_snapshot

    @Property(str, notify=changed)
    def sourceHint(self) -> str:
        source = self.cfg.get("download.list_source", "official")
        return "官方源" if source == "official" else "镜像源 (BMCLAPI)"

    # ------------------------------------------------------------ 加载列表
    @Slot()
    def refresh(self) -> None:
        self.refresh_manifest(force=False)

    @Slot(bool)
    def refreshForce(self, force: bool) -> None:
        self.refresh_manifest(force=force)

    def refresh_manifest(self, force: bool) -> None:
        if self._loading:
            return
        self._loading = True
        self.loadingChanged.emit()
        self._worker = ManifestWorker(self.cfg, force, self)
        self._worker.loaded.connect(self._on_manifest)
        self._worker.start()

    @Slot(object)
    def _on_manifest(self, manifest) -> None:
        self._loading = False
        self.loadingChanged.emit()
        if not isinstance(manifest, dict) or not manifest:
            self.launcher.setStatus("版本列表加载失败(可能没有网络)")
            return
        self._entries = core_remote.vanilla_entries(manifest)
        self._rebuild()
        self.launcher.setStatus("版本列表已更新 (%d 个正式版)" % self._release_model.count)

    @Slot()
    def refreshInstalled(self) -> None:
        """版本列表不变, 只重算「已安装」标记(安装完成后调用)。"""
        if not self._entries:
            return
        self._rebuild()

    def _installed_ids(self) -> set:
        ids = set()
        for ver in getattr(self.launcher, "_versions", []):
            ids.add(ver.id)
            if getattr(ver, "installed", False) and getattr(ver, "path", ""):
                ids.add(ver.id)
        return ids

    def _rebuild(self) -> None:
        installed = self._installed_ids()
        entries = self._entries or {}
        for name in ("release", "snapshot", "old", "april"):
            model = {"release": self._release_model, "snapshot": self._snapshot_model,
                     "old": self._old_model, "april": self._april_model}[name]
            model.set_rows([self._row(item, installed) for item in entries.get(name, [])])

        latest = entries.get("latest", {}) or {}
        self._latest_release = self._latest_row(latest.get("release"), "最新正式版", installed)
        self._latest_snapshot = self._latest_row(latest.get("snapshot"), "最新预览版", installed)
        self.changed.emit()

    def _row(self, item: Dict, installed: set) -> Dict:
        vid = item.get("id", "")
        kind = item.get("type", "release")
        label = {"release": "正式版", "snapshot": "预览版", "old_beta": "远古版",
                 "old_alpha": "远古版", "april": "愚人节版"}.get(kind, "正式版")
        time_text = _format_time(item.get("time", ""))
        subtitle = "%s, 发布于 %s" % (label, time_text) if time_text else label
        if vid in installed:
            subtitle = "已安装 · " + subtitle
        return {"versionId": vid, "subtitle": subtitle, "time": time_text, "kind": kind,
                "icon": "cube_grass" if kind == "release" else "cube_sand",
                "installed": vid in installed,
                "search": vid}

    def _latest_row(self, item, label: str, installed: set) -> Dict:
        if not item:
            return {}
        vid = item.get("id", "")
        time_text = _format_time(item.get("time", ""))
        subtitle = "%s, 发布于 %s" % (label, time_text) if time_text else label
        if vid in installed:
            subtitle = "已安装 · " + subtitle
        return {"versionId": vid, "subtitle": subtitle, "time": time_text,
                "kind": item.get("type", ""), "installed": vid in installed}

    # ------------------------------------------------------------ 安装
    @Slot(str)
    def installVersion(self, version_id: str) -> None:
        if not version_id:
            return
        self.launcher.startInstall("vanilla", version_id)

    @Slot(str)
    def installLatest(self, which: str) -> None:
        row = self._latest_release if which == "release" else self._latest_snapshot
        vid = row.get("versionId", "") if row else ""
        if vid:
            self.installVersion(vid)
