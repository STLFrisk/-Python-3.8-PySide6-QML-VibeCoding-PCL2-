"""社区资源(Mod / 整合包 / 数据包 / 资源包 / 光影包)的搜索与下载后端。"""
from __future__ import annotations

import os
import re
import shutil
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from ..core import launch as core_launch
from ..core import paths as core_paths
from ..core import resources as core_resources
from .models import DictListModel

RESULT_ROLES = ["title", "summary", "meta", "downloads", "icon", "source", "id",
                "categories", "loaders", "updated"]
FILE_ROLES = ["name", "file", "size", "date", "downloads", "url", "loaders", "versions"]


def _version_key(text: str):
    """版本号排序键(1.20.10 要排在 1.20.1 前面)。"""
    parts = []
    for chunk in str(text or "").replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else -1)
    return parts


def human_count(value) -> str:
    """下载量 1234567 → 123.5 万。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if number >= 100000000:
        return "%.2f 亿" % (number / 100000000.0)
    if number >= 10000:
        return "%.1f 万" % (number / 10000.0)
    return "%d" % int(number)


def human_size(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return "%.1f %s" % (number, unit) if unit != "B" else "%d B" % int(number)
        number /= 1024.0
    return "%.1f GB" % number


# 跳转条文案里用的资源类型名(与 core_resources.KIND_LABELS 的口径一致, 只取跳转支持的两种)
_SWITCH_LABELS = {"mod": "Mod", "datapack": "数据包"}


def _switch_text(switch_to: str, first_is_server: bool) -> str:
    """给出跳转条的**整句**文案(与它所在的那个大类相符)。

    跳转条挂在一个大类上, 那句话必须同时说清两件事: 当前这一大类里放的是什么版本的
    文件、点下去会跳到哪一类。以前这两句话写死在界面里, 且只描述了"客户端那批文件",
    所以第一个大类是"服务端"时怎么说都是假话(B3/B3')。

    * 第一大类是**客户端** → 与改动前**逐字一致**的两句话(客户端是 Mod/数据包两页的
      常态, 文案不改, 避免无谓的界面变动);
    * 第一大类是**服务端** → 换成"当前显示的是该项目的「服务端」版本…"这句。
    """
    target = _SWITCH_LABELS.get(str(switch_to or "").lower(), str(switch_to or ""))
    if first_is_server:
        return "当前显示的是该项目的「服务端」版本，点击这里查看其「%s」版本。" % target
    if str(switch_to or "").lower() == "mod":
        return "以下是该项目的「数据包」版本，点击这里查看其「Mod」版本。"
    return "以下是该项目的「Mod」版本，点击这里查看其「数据包」版本。"


class SearchWorker(QThread):
    """后台搜索社区资源。

    done 会把**发起搜索时的完整条件**一起带回: 搜索是异步的, 用户很可能在结果
    回来之前又切了分类/改了条件, 那时这条结果就是陈旧的, 调用方必须丢弃它
    —— 否则会出现"选了整合包却显示数据包"这类分类错位。
    """

    done = Signal(str, str, str, str, str, object)   # kind, query, mc, loader, source, data

    def __init__(self, kind: str, query: str, mc: str, loader: str, source: str,
                 limit: int, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.query = query
        self.mc = mc
        self.loader = loader
        self.source = source
        self.limit = limit

    def run(self) -> None:  # noqa: D102
        try:
            data = core_resources.search(self.kind, self.query, self.mc, self.loader,
                                         self.source, self.limit)
        except Exception as exc:  # noqa: BLE001
            data = {"hits": [], "total": 0, "error": str(exc)}
        self.done.emit(self.kind, self.query, self.mc, self.loader, self.source, data)


class FilesWorker(QThread):
    """后台取某个资源可下载的文件列表。"""

    done = Signal(object)

    def __init__(self, project_id: str, kind: str, mc: str, loader: str, parent=None) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.kind = kind
        self.mc = mc
        self.loader = loader

    def run(self) -> None:  # noqa: D102
        try:
            files = core_resources.project_files(self.project_id, self.kind, self.mc, self.loader)
        except Exception:  # noqa: BLE001
            files = []
        self.done.emit(files)


class DownloadWorker(QThread):
    """后台下载资源文件 / 安装整合包。"""

    progress = Signal(str, int)
    finished = Signal(str, str)          # 结果说明, 目标路径或错误

    def __init__(self, kind: str, url: str, filename: str, game_dir: str, root: str,
                 name: str, source: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.url = url
        self.filename = filename
        self.game_dir = game_dir
        self.root = root
        self.name = name
        self.source = source

    def run(self) -> None:  # noqa: D102
        try:
            if self.kind == "modpack":
                # 先下载整合包文件(在后台线程), 再解包安装
                if self.url:
                    self.progress.emit("正在下载整合包…", 5)
                    if not remote_download(self.url, self.game_dir, self.source, self):
                        self.finished.emit("", "整合包下载失败")
                        return
                self.progress.emit("正在安装整合包…", 40)
                version_id = core_resources.install_modpack(
                    self.game_dir, self.root, self.name,
                    progress_cb=lambda pct, text: self.progress.emit(text, int(pct)))
                self.finished.emit("整合包已安装为版本 %s" % version_id, version_id)
                return
            self.progress.emit("正在下载…", 20)

            def _cb(done, total):
                if total:
                    self.progress.emit("正在下载 %d%%" % int(100.0 * done / total),
                                       int(20 + 70.0 * done / total))

            path = core_resources.install_file(self.url, self.filename, self.game_dir,
                                               self.kind, self.source, progress_cb=_cb)
            label = core_resources.KIND_LABELS.get(self.kind, "资源")
            self.finished.emit("%s 已下载到 %s" % (label, os.path.basename(path)), path)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit("", "下载失败: %s" % exc)


class ResourcesBackend(QObject):
    """下载页「社区资源」部分的数据与操作。"""

    changed = Signal()
    loadingChanged = Signal()
    detailChanged = Signal()
    statusChanged = Signal()
    # 资源页点「下载」整合包时先问名字: 参数是**预填的默认版本名**(后端已按安装时
    # 同一套规则算过: 非法字符清理 + 重名 -2 避让)。界面收到后弹命名框, 用户确认
    # 才 installPendingModpack()。普通资源(MOD/资源包/数据包/光影包)不发这个信号。
    modpackNameRequested = Signal(str)

    def __init__(self, cfg, launcher, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.launcher = launcher
        self._kind = "mod"
        self._query = ""
        self._mc = ""
        self._loader = ""
        self._source = "all"
        self._loading = False
        self._status = ""
        self._total = 0
        self._error = ""
        self._detail_title = ""
        self._detail_id = ""
        self._detail_icon = ""
        self._detail_groups = []  # type: List[Dict]
        self._detail_kind = "mod"
        self._detail_mc = ""
        self._detail_loader = ""
        self._pending_gamedir = ""
        # 资源页整合包: 用户点下载之后、在命名对话框里确认之前, 先在这里**快照**
        # 待安装条目(url / 文件名 / 来源分类)。用快照而不是"等确认时再按行号取",
        # 是因为文件列表是异步刷新的, 行号可能已经指向别的文件。
        self._pending_modpack = None  # type: Optional[Dict]
        self._results = DictListModel(RESULT_ROLES, self)
        self._files = DictListModel(FILE_ROLES, self)
        self._search_worker = None
        self._files_worker = None
        self._download_worker = None

    # ------------------------------------------------------------ 属性
    @Property(QObject, constant=True)
    def resultsModel(self):  # noqa: N802
        return self._results

    @Property(QObject, constant=True)
    def filesModel(self):  # noqa: N802
        return self._files

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=changed)
    def kind(self) -> str:
        return self._kind

    @Property(str, notify=changed)
    def kindLabel(self) -> str:  # noqa: N802
        return core_resources.KIND_LABELS.get(self._kind, "资源")

    @Slot(str, result=bool)
    def isModpackFile(self, path: str) -> bool:  # noqa: N802
        """这个本地文件是不是**真正的**整合包(.mrpack / 内含 modrinth.index.json)。

        界面在弹"安装本地整合包"命名框**之前**必须先问这里: 文件对话框里有"所有文件",
        用户选了普通 .zip/.jar 时, 以前照样会弹一个"给整合包起名"的框 —— 起完名才在
        安装时被判成普通资源, 框白弹一次, 还让人以为启动器认错了文件。
        判定规则只有一处定义: ``core.resources.is_modpack_file``(这里只调用, 不重写)。
        """
        try:
            return bool(core_resources.is_modpack_file(path))
        except Exception as exc:  # noqa: BLE001
            print("[resources] modpack check failed:", type(exc).__name__, exc, flush=True)
            return False

    @Slot(str, str)
    def installLocalModpack(self, path: str, name: str = "") -> None:  # noqa: N802
        """安装本地整合包文件(.mrpack)。

        如果选的其实是 Mod / 资源包之类的普通文件(没有 modrinth.index.json),
        就按普通资源放进启动器目录的 Download/<类型>, 而不是报
        "不是有效的 Modrinth 整合包(缺少 modrinth.index.json)" 这种让人迷惑的错。
        """
        if not path or not os.path.isfile(path):
            self._status = "找不到整合包文件"
            self.statusChanged.emit()
            return
        if not core_resources.is_modpack_file(path):
            base = os.path.basename(path)
            low = base.lower()
            kind = "mod" if low.endswith(".jar") else (
                "resourcepack" if low.endswith(".zip") else "mod")
            folder = core_paths.download_dir(kind)
            dest = os.path.join(folder, base)
            try:
                shutil.copy2(path, dest)
            except Exception as exc:  # noqa: BLE001
                self._status = "复制失败: %s" % exc
                self.statusChanged.emit()
                self.launcher.messageRequested.emit("不是整合包", str(exc), "warn")
                return
            label = {"mod": "Mod", "resourcepack": "资源包"}.get(kind, "资源")
            self._status = "这%s不是整合包，已放入 %s" % (label, folder)
            self.statusChanged.emit()
            self.launcher.resourceDownloaded.emit(
                "%s 已放入：\n%s\n\n（它没有 modrinth.index.json，不是整合包，"
                "已按%s处理）" % (base, dest, label), dest)
            return
        label = name or os.path.splitext(os.path.basename(path))[0]
        self._status = "已开始安装整合包 %s…" % label
        self.statusChanged.emit()
        self.launcher.startResourceDownload("modpack", "", os.path.basename(path), path, label)

    @Property(str, notify=changed)
    def query(self) -> str:
        return self._query

    @Property(str, notify=changed)
    def mcVersion(self) -> str:  # noqa: N802
        return self._mc

    @Property(str, notify=changed)
    def loader(self) -> str:
        return self._loader

    @Property(str, notify=changed)
    def source(self) -> str:
        return self._source

    @Property(str, notify=detailChanged)
    def detailTitle(self) -> str:  # noqa: N802
        return self._detail_title

    # 详情页「转到 Modrinth」要用: 当前详情项目的 id 与分类(mod/datapack/modpack/…)。
    # 只读, 不改任何既有行为 —— 由 openProjectById 里已经存下的 _detail_id/_detail_kind
    # 直接暴露出来(detailChanged 与它们同一次通知)。
    @Property(str, notify=detailChanged)
    def detailProjectId(self) -> str:  # noqa: N802
        return self._detail_id

    @Property(str, notify=detailChanged)
    def detailKind(self) -> str:  # noqa: N802
        return self._detail_kind

    @Property(str, notify=detailChanged)
    def detailIcon(self) -> str:  # noqa: N802
        return self._detail_icon

    @Property("QVariantList", notify=detailChanged)
    def detailGroups(self):  # noqa: N802
        """三级菜单用: 该资源按"适配游戏版本"分组的文件列表。"""
        return self._detail_groups

    @Property(str, notify=detailChanged)
    def downloadFolder(self) -> str:  # noqa: N802
        """这类资源的下载目录(显示给用户看)。"""
        try:
            return core_paths.download_dir(self._kind)
        except Exception:  # noqa: BLE001
            return ""

    @Property(int, notify=changed)
    def resultCount(self) -> int:  # noqa: N802
        return self._total

    # ------------------------------------------------------------ 过滤条件
    @Slot(str)
    def setKind(self, value: str) -> None:  # noqa: N802
        kind = str(value or "mod").lower()
        if kind == self._kind:
            return
        self._kind = kind
        self._results.set_rows([])
        self._files.set_rows([])
        self._total = 0
        self._status = ""
        self.changed.emit()
        self.statusChanged.emit()
        # 切换分类时沿用当前版本/加载器条件, 立刻重新搜索一次
        self.doSearch()

    @Slot(str)
    def setQuery(self, value: str) -> None:  # noqa: N802
        self._query = str(value or "")
        self.changed.emit()

    @Slot(str)
    def setVersion(self, value: str) -> None:  # noqa: N802
        self._mc = str(value or "")
        self.changed.emit()

    @Slot(str)
    def setLoader(self, value: str) -> None:  # noqa: N802
        self._loader = "" if str(value or "").strip() in ("", "全部") else str(value)
        self.changed.emit()

    @Slot(str)
    def setSource(self, value: str) -> None:  # noqa: N802
        self._source = str(value or "all")
        self.changed.emit()

    @Slot(str, str, str)
    def applyFilters(self, query: str, mc: str, loader: str) -> None:
        """从界面一次性接收搜索条件(名称/版本/加载器)。"""
        self._query = str(query or "")
        self._mc = str(mc or "")
        self._loader = "" if str(loader or "").strip() in ("", "全部") else str(loader)
        self.changed.emit()

    @Slot()
    def resetFilters(self) -> None:  # noqa: N802
        self._query = ""
        self._mc = ""
        self._loader = ""
        self._source = "all"
        self.changed.emit()
        self.doSearch()

    @Slot()
    def doSearch(self) -> None:  # noqa: N802
        """按当前条件搜索(后台线程)。

        注意: 这里**不能**在"上一个搜索还在跑"时直接 return —— 那会让用户在结果回来前
        切换分类时, 新分类的搜索被整个丢掉, 列表要么是旧分类要么是空的
        (表现就是"选了整合包却显示数据包")。正确做法是照常发起新搜索,
        由 _on_search_done 按条件标签丢弃陈旧结果。
        """
        self._loading = True
        self._status = "正在搜索 %s…" % core_resources.KIND_LABELS.get(self._kind, "资源")
        self._error = ""
        self.loadingChanged.emit()
        self.statusChanged.emit()
        self._search_worker = SearchWorker(self._kind, self._query, self._mc, self._loader,
                                           self._source, 30, self)
        self._search_worker.done.connect(self._on_search_done)
        self._search_worker.start()

    @Slot(object)
    def _on_search_done(self, kind, query, mc, loader, source, data) -> None:
        # 只接受"当前条件"的搜索结果。搜索是异步的, 用户可能在结果回来前又切了分类,
        # 陈旧结果一旦应用就会出现"选了整合包却显示数据包"的错位。
        if (str(kind) != self._kind or str(query) != self._query or str(mc) != self._mc
                or str(loader) != self._loader or str(source) != self._source):
            return
        self._loading = False
        if not isinstance(data, dict):
            data = {"hits": [], "total": 0, "error": "返回数据异常"}
        self._error = str(data.get("error") or "")
        self._total = int(data.get("total") or 0)
        rows = []  # type: List[Dict]
        for hit in (data.get("hits") or []):
            if not isinstance(hit, dict):
                continue
            loaders = "/".join(hit.get("loaders") or [])
            rows.append({
                "id": hit.get("id", ""),
                "title": hit.get("title", ""),
                "summary": hit.get("description", ""),
                "meta": " · ".join([x for x in [hit.get("author", ""),
                                                " ".join(hit.get("categories") or []),
                                                loaders] if x]),
                "downloads": "↓ " + human_count(hit.get("downloads")),
                "icon": hit.get("icon", ""),
                "source": hit.get("source", ""),
                "categories": " ".join(hit.get("categories") or []),
                "loaders": loaders,
                "updated": hit.get("updated", ""),
            })
        self._results.set_rows(rows)
        if self._error:
            self._status = self._error
        elif not rows:
            self._status = "没有找到匹配的资源（可以改改版本或加载器条件）"
        else:
            self._status = "共 %d 个结果%s" % (self._total,
                                              "，版本 " + self._mc if self._mc else "")
        self.loadingChanged.emit()
        self.statusChanged.emit()
        self.changed.emit()

    # ------------------------------------------------------------ 资源详情
    @Slot(int)
    def openProject(self, index: int) -> None:  # noqa: N802
        """按列表行打开资源详情(只取 id —— 行内容可能已经变了)。"""
        row = self._results.at(index)
        if not isinstance(row, dict):
            return
        self.openProjectById(str(row.get("id") or ""), str(row.get("title") or ""),
                             str(row.get("icon") or ""))

    @Slot(str)
    def jumpToKind(self, kind: str) -> None:  # noqa: N802
        """跳到**同一项目**的另一种资源类型(mod ⇄ datapack), 两类可以相互跳转。

        关键: 这里**不**改当前分类、也**不**重新检索列表 —— 只把详情页按目标类型重开。
        之前是"切分类 + 关详情"一起做, 结果列表还在异步搜索、详情页已经关闭,
        整页就空白了。而且 FilesWorker 是异步的, 分类必须用 _detail_kind 快照,
        不能被随后恢复的 _kind 覆盖(否则会出现"跳过去又跳回来")。
        """
        project_id = str(self._detail_id or "")
        target = str(kind or "").strip().lower()
        if not project_id or target not in ("mod", "datapack"):
            return
        saved_kind = self._kind
        self._kind = target           # 只用来决定 FilesWorker 取哪一类文件
        try:
            self.openProjectById(project_id, self._detail_title, self._detail_icon)
        finally:
            self._kind = saved_kind   # 列表分类保持不变(返回时还在原来的分类)

    @Slot()
    def jumpToModVersions(self) -> None:  # noqa: N802
        """从"数据包"详情跳到**同一项目**的 Mod 版本(两类资源可以相互跳转)。

        关键: 这里**不**改当前分类、也**不**重新检索列表 —— 只把详情页按 mod 重开。
        之前是"切分类 + 关详情"一起做, 结果列表还在异步搜索、详情页已经关闭,
        整页就空白了(踩过这个坑)。现在返回时列表还停在数据包分类, 符合预期。
        """
        project_id = str(self._detail_id or "")
        if not project_id:
            return
        saved_kind = self._kind
        self._kind = "mod"            # 只用来决定 FilesWorker 取哪一类文件
        try:
            self.openProjectById(project_id, self._detail_title, self._detail_icon)
        finally:
            self._kind = saved_kind   # 列表分类保持不变(返回时还在原来的分类)

    @Slot(str, str, str)
    def openProjectById(self, project_id: str, title: str = "", icon: str = "") -> None:  # noqa: N802
        """按项目 id 打开详情。

        注意: 必须用 id 而不是列表行号 —— 搜索是异步的, 行号随时可能变,
        用行号会取到别的项目(表现就是"点 Mod 却显示了别的资源")。
        分类/版本/加载器条件也一起快照, 保证"点哪个就是哪个"。
        """
        pid = str(project_id or "").strip()
        if not pid:
            return
        if title:
            self._detail_title = str(title)
        self._detail_id = pid
        self._detail_icon = str(icon or "")
        self._detail_kind = self._kind
        self._detail_mc = self._mc
        self._detail_loader = self._loader
        self._files.set_rows([])
        self._detail_groups = []
        self.detailChanged.emit()
        self._status = "正在获取「%s」的可用文件…" % self._detail_title
        self.statusChanged.emit()
        worker = FilesWorker(pid, self._detail_kind, self._detail_mc, self._detail_loader, self)
        worker.done.connect(self._on_files_done)
        self._files_worker = worker
        worker.start()

    @Slot(object)
    def _on_files_done(self, files) -> None:
        # 服务端专用的"服务器核心": 版本的 loaders 里只出现这些 → 属于服务端版本。
        server_cores = ("paper", "spigot", "purpur", "bukkit", "folia", "sponge",
                        "velocity", "waterfall", "bungeecord", "leaves", "pufferfish")
        rows = []  # type: List[Dict]
        meta = []  # type: List[Tuple[List[str], List[str]]]   与 rows 同序(加载器/游戏版本)
        for index, entry in enumerate(files or []):
            if not isinstance(entry, dict):
                continue
            loaders = [str(v) for v in (entry.get("loaders") or [])]
            versions = [str(v) for v in (entry.get("game_versions") or [])]
            rows.append({
                "index": index,
                "name": entry.get("version", ""),
                "file": entry.get("file", ""),
                "size": human_size(entry.get("size")),
                "date": entry.get("date", ""),
                "downloads": human_count(entry.get("downloads")),
                "url": entry.get("url", ""),
                "loaders": "/".join(loaders),
                "versions": " ".join(versions[:4]),
            })
            meta.append((loaders, versions))
        self._files.set_rows(rows)

        # 判断每个文件属于"客户端"还是"服务端"(只按加载器名字推断, 不改任何检索逻辑)
        def _side_of(loaders: List[str]) -> str:
            low = [x.strip().lower() for x in loaders if x.strip()]
            if low and all(x in server_cores for x in low):
                return "server"
            return "client"

        def _loader_order(name: str):
            order = {"fabric": 0, "forge": 1, "neoforge": 2, "quilt": 3}
            first = str(name).split("/")[0].strip().lower()
            return (order.get(first, 8), str(name))

        def _is_snapshot(version: str) -> bool:
            """判断游戏版本是不是快照/预览版(26.3-rc-1 / 25w46a / 1.20.5-pre1 …)。"""
            low = str(version or "").strip().lower()
            if not low:
                return False
            if "-pre" in low or "-rc" in low or "snapshot" in low or "beta" in low:
                return True
            return bool(re.search(r"\d{2}w\d{2}", low))

        def _loader_key(loaders) -> str:
            """把一组加载器名字并成一个分组名(fabric/forge/neoforge … / 通用·其它)。

            ⚠️ 这里以前是 ``"/".join(names[:2])``: 一个版本文件支持 3 个以上加载器时,
            组名只留前两个, 于是标签**不代表**这组文件实际支持的加载器(用户报的
            "多加载器标签显示不全", B5)。现在完整拼接 —— 组名 = 该组文件的加载器集合。
            """
            names = [str(x).strip() for x in (loaders or []) if str(x).strip()]
            return "/".join(names) if names else "通用 / 其它"

        def _game_version_files(items) -> List[Dict]:
            """游戏版本 → 文件(按游戏版本号倒序)。"""
            tree = {}  # type: Dict[str, List[Dict]]
            for row, (_loaders, versions) in items:
                tree.setdefault(versions[0] if versions else "未知版本", []).append(row)
            out = []  # type: List[Dict]
            for version_key in sorted(tree, key=_version_key, reverse=True):
                group_items = tree[version_key]
                out.append({"version": version_key, "count": len(group_items),
                            "files": group_items})
            return out

        def _build_loader_children(items) -> List[Dict]:
            """加载器种类 → 游戏版本 → 文件(客户端这一层的"子组", 不再和游戏版本挤在一行)。

            加载器下面仍然先分"正式版 / 快照"(游戏版本是不是快照), 只有确实同时存在
            快照版本时才拆这一层; 拆开时组标题写成 "fabric · 快照"。
            """
            tree = {}  # type: Dict[str, Dict[str, Dict[str, List[Dict]]]]
            for row, (loaders, versions) in items:
                loader_key = _loader_key(loaders)
                mc_key = versions[0] if versions else "未知版本"
                kind_key = "快照" if _is_snapshot(mc_key) else "正式版"
                tree.setdefault(loader_key, {}).setdefault(kind_key, {}).setdefault(
                    mc_key, []).append(row)
            out = []  # type: List[Dict]
            for loader_key in sorted(tree, key=_loader_order):
                kinds = tree[loader_key]
                split = len([k for k in kinds if k == "快照"]) > 0 and len(kinds) > 1
                for kind_key in ("正式版", "快照"):
                    if kind_key not in kinds:
                        continue
                    version_groups = []
                    for mc_key in sorted(kinds[kind_key], key=_version_key, reverse=True):
                        group_items = kinds[kind_key][mc_key]
                        version_groups.append({"version": mc_key, "count": len(group_items),
                                               "files": group_items})
                    title = ("%s · %s" % (loader_key, kind_key)) if split else loader_key
                    out.append({"loader": title, "label": "适配版本", "unit": "适配版本",
                                "count": sum(g["count"] for g in version_groups),
                                "versionCount": len(version_groups),
                                "versions": version_groups})
            return out

        def _build_game_children(items) -> List[Dict]:
            """游戏版本 → 文件(整合包 / 数据包 / 资源包: 不套加载器的"子组")。"""
            return _wrap_children(_game_version_files(items))

        def _wrap_children(version_groups: List[Dict]) -> List[Dict]:
            """把"游戏版本"列表包成一个加载器组(loader 为空 = 没有加载器层)。

            刻意保留一层(而不是直接摊平)有两个原因:
            1. 客户端大类下面永远是"加载器种类"这一层(Mods 没有加载器信息时, 就只有一个
               "通用 / 其它" 分组, 与 PCL2 一致) —— 不至于有的分类多一层、有的少一层;
            2. 整合包 / 资源包只有这一个分组, 它的 loader 为空 → 界面**不画标题栏**,
               展开后直接就是游戏版本列表(与之前一样, 不会突然多出一条标题)。
            """
            return [{"loader": "", "label": "适配版本", "unit": "适配版本",
                     "count": sum(g.get("count", 0) for g in version_groups),
                     "versionCount": len(version_groups), "versions": version_groups}]

        def _client_loader_children(items) -> List[Dict]:
            """客户端要展示的"加载器种类"子组: 没有加载器信息就退回一个空标题分组。"""
            if items:
                return _build_loader_children(items)
            return _wrap_children([])

        def _build_server_groups(items) -> List[Dict]:
            """服务端: 游戏版本 → 服务器核心(分区标题) → 资源版本。

            与需求一致: 顶层"服务端"大类展开后先列出**可用的游戏版本**,
            每个游戏版本里再按**服务器核心种类**分区(bukkit/paper、velocity …),
            分区里才是资源版本。
            """
            tree = {}  # type: Dict[str, Dict[str, List[Dict]]]
            for row, (loaders, versions) in items:
                mc_key = versions[0] if versions else "未知版本"
                # 核心分区的标题同样必须列**完整**的加载器集合(B5): 以前是 loaders[:2],
                # 支持 3 个以上核心的版本(如 bukkit/paper/spigot/purpur)标题里只剩两个,
                # 与紧随其下的文件行(文件行用的是完整 "/".join(loaders))自相矛盾。
                core_key = "/".join(loaders) if loaders else "通用 / 其它"
                tree.setdefault(mc_key, {}).setdefault(core_key, []).append(row)
            out = []  # type: List[Dict]
            for mc_key in sorted(tree, key=_version_key, reverse=True):
                files = []  # type: List[Dict]
                total = 0
                for core_key in sorted(tree[mc_key], key=_loader_order):
                    core_items = tree[mc_key][core_key]
                    total += len(core_items)
                    files.append({"sectionLabel": "核心：%s" % core_key, "index": -1, "name": "",
                                  "file": "", "size": "", "date": "", "downloads": "",
                                  "url": "", "loaders": "", "versions": ""})
                    files.extend(core_items)
                out.append({"version": mc_key, "count": total, "files": files})
            return out

        # 按侧别 + 分类分流
        client_items = [(r, m) for r, m in zip(rows, meta) if _side_of(m[0]) == "client"]
        server_items = [(r, m) for r, m in zip(rows, meta) if _side_of(m[0]) == "server"]
        # ⚠️ 必须用**详情页的快照** self._detail_kind, 不能读活的 self._kind:
        # FilesWorker 是异步的, 而"数据包→Mod 跳转"只是临时改了 self._kind, 等结果回来
        # 早就恢复了 —— 读活字段会按旧分类重新渲染, 表现就是"跳过去又跳回来"(踩过这个坑)。
        detail_kind = str(self._detail_kind or self._kind or "mod").lower()
        is_pack = detail_kind in ("modpack", "datapack", "resourcepack", "shader")

        client_groups = []  # type: List[Dict]     客户端大类内部的"加载器种类"子组列表
        switch_to = ""      # 该不该给"查看另一类版本"的跳转条, 取值 "mod" / "datapack"
        if detail_kind == "datapack":
            # 数据包: 只列"数据包"版式的文件(游戏版本 → 文件)。
            # 判定是 **loaders 里含 datapack**(它常和 fabric/neoforge 并列出现)。
            plain = [(r, m) for r, m in client_items
                     if any(x.lower() == "datapack" for x in m[0])]
            if plain:
                client_groups = _build_game_children(plain)
            else:
                # 这个项目其实没有数据包版式文件 → 照 Mod 版式显示, 但仍然给跳转条
                client_groups = _client_loader_children(client_items)
            # 数据包页**总是**给"查看其 Mod 版本"的入口(跳转是按项目 id 重开, 不依赖列表内容)
            switch_to = "mod"
        elif is_pack:
            # 整合包 / 资源包 / 光影包: 客户端大类里直接 游戏版本 → 文件, 不套加载器层
            client_groups = _build_game_children(client_items)
        else:
            # Mods 等分类: 把"数据包版式"的文件挑出去(它们属于数据包页),
            # 否则跳到 Mods 后会出现一个 datapack 分组, 两侧的内容混在一起。
            packs = [(r, m) for r, m in client_items
                     if any(x.lower() == "datapack" for x in m[0])]
            client_items = [(r, m) for r, m in client_items if (r, m) not in packs]
            client_groups = _client_loader_children(client_items)
            if packs:
                switch_to = "datapack"

        has_client = bool(client_items)
        has_server = bool(server_items)
        both_sides = has_client and has_server

        def _as_category(tag: str, children: List[Dict], force: bool = False) -> Dict:
            """把"子组列表"包成一个大类(客户端 / 服务端), 或原样返回一个"扁平的"子组。

            带 children 的组是**大类**(outer=True): 界面里它下面是"子组"
            (加载器种类 / 游戏版本), 不会再被当成游戏版本渲染;
            子组标题统一成 "客户端 · <加载器>" / "服务端 · <核心>"。

            唯一例外(``force=False``): 客户端只有一个**没有加载器名**的子组
            (整合包 / 资源包 / 光影包) —— 这时直接把那个子组交出去, 它在外层渲染成
            "标题栏 + 适配版本列表", 和改动前一模一样(不会凭空多一次点击)。

            ``force=True``: 即使只有一个"没有加载器名"的扁平子组, 也**必须**有大类标题
            (数据包页就是这种: 那一页顶部有"查看其 Mod 版本"的跳转条, 跳转条下面要先是
            "客户端"大类, 大类里才是游戏版本列表 —— 与"只有服务端时也显示服务端大类"
            对称)。这时把那个扁平子组**合并进大类**(大类直接持有 versions),
            不再多套一层同名子组, 否则界面上会出现 "客户端 → 客户端 → 适配版本"。
            """
            # 只有"客户端那一个没有加载器名的子组"才走直通(注意服务端子组连 loader
            # 这个键都没有 —— 它在界面上是"适配版本 N"，不能被当成扁平组放过去)。
            flat_single = (len(children) == 1 and "loader" in children[0]
                           and not str(children[0].get("loader") or "").strip())
            if flat_single and not force:
                return children[0]
            if flat_single:
                merged = dict(children[0])
                merged["loader"] = tag
                merged["outer"] = True
                merged.setdefault("label", "适配版本")
                merged.setdefault("unit", merged["label"])
                return merged
            prefixed = []  # type: List[Dict]
            for child in children:
                child = dict(child)
                child_title = str(child.get("loader") or "").strip()
                child["loader"] = ("%s · %s" % (tag, child_title)) if child_title else tag
                child.setdefault("label", "适配版本")
                child.setdefault("unit", child["label"])
                prefixed.append(child)
            # 子组列表为空(客户端一个加载器组都没有这种极端情况) → 补一个空子组,
            # 保证大类展开后还有一行可点, 不会出现"点开什么都没有"的死角。
            if not prefixed:
                prefixed.append({"loader": tag, "label": "适配版本", "unit": "适配版本",
                                 "count": 0, "versionCount": 0, "versions": []})
            return {"loader": tag, "label": "适配版本", "unit": "适配版本", "outer": True,
                    "count": sum(g.get("count", 0) for g in prefixed),
                    "versionCount": len(prefixed), "children": prefixed}

        groups = []  # type: List[Dict]
        # 数据包页要显式带"客户端"大类(与服务端大类对称, 跳转条也要挂在大类上);
        # 整合包 / 资源包 / 光影包的扁平直通保持不变(那是用户已确认过的样式)。
        want_category = detail_kind == "datapack"
        if server_items:
            if client_items:
                # 客户端 / 服务端两个大类对称: 都只有一层标题, 展开后才是各自的子组。
                # ⚠️ 大类里可以写 "客户端 · <加载器>" 这种名字, 但要保证**只有两条大类** ——
                # 不能再回到"客户端 · fabric / 客户端 · forge …"并列的样子(用户明确否决过)。
                groups.append(_as_category("客户端", client_groups, force=want_category))
                groups.append(_as_category("服务端", _build_server_groups(server_items)))
            else:
                # 只有服务端版本: 客户端本身没有版本 → 不硬造一个空的"客户端"大类,
                # 直接就是"服务端"一个大类, 里面照旧是 游戏版本 → 核心分区 → 资源版本。
                groups.append(_as_category("服务端", _build_server_groups(server_items)))
        elif client_items:
            # 只有客户端版本: 客户端 → 加载器种类 → 游戏版本 → 资源版本
            groups.append(_as_category("客户端", client_groups, force=want_category))
        else:
            # 一个可下载文件都没有: 给一个空的客户端大类, 界面显示"没有文件"而不是白屏
            groups.append(_as_category("客户端", client_groups, force=want_category))

        # 跳转条只挂在第一个大类**本身**上 —— 界面把它渲染在大类内容的最上面,
        # 展开该类第一眼就看到它(PCL2 的位置也是这样)。
        # ⚠️ 这里以前还额外往 children[0] 上写了一份, 结果 Mods 页同时出现两条一模一样的
        # "以下是该项目的「Mod」版本…"(客户端大类下一条、客户端 · fabric 子组下一条)。
        # 跳转条是**整页**的入口, 只属于最外面的大类, 有且只能有一个。
        #
        # ⚠️ 文案曾经是写死在界面里的两句话(qml/pages/ResourceDetailPage.qml):
        # switchTo == "mod" → "以下是该项目的「数据包」版本…", 其它 → "以下是该项目的
        # 「Mod」版本…"。两句说的都是**客户端那批文件**。可第一个大类**不一定**是客户端:
        # 项目只有服务端核心版本(例如只发布了 paper/spigot 的插件)时, 客户端一个文件都没有,
        # groups[0] 就是"服务端"大类 —— 文案却照旧宣称"以下是数据包版本", 与所在大类不符
        # (B3)。上一轮的做法是"这种情形干脆不挂跳转条", 但那样用户就没有入口了。
        #
        # B3': 现在由后端把**整句**文案(qml 优先读 switchText, 读不到才回退到那两句老文案)
        # 一起传下去 —— 谁带跳转条, 谁就负责说清楚"当前这一大类是什么、点了会跳到哪一类"。
        # 界面因此不再需要为"第一大类是服务端"猜文案, 跳转条在该情形下**恢复显示**。
        first_is_server = bool(server_items) and not bool(client_items)
        if switch_to and groups:
            groups[0]["switchTo"] = switch_to
            groups[0]["switchText"] = _switch_text(switch_to, first_is_server)

        # 折叠初始值交给界面("collapsed"), 由后端给 — 规则:
        # * 两个大类并列时(**用户自己选了要看客户端还是服务端**) → 默认全收起,
        #   和原来的逐组收起一致, 一进来先扫标题;
        # * 只有一类时 → 大类直接展开, 少点一次(但下面的加载器/游戏版本仍收起);
        # * 带跳转条的组**必须**展开 —— 它是这一页的主入口, 收起来等于没有
        #   (历史上就吃过"默认收起 + 没有展开入口"的亏)。
        for group in groups:
            group["collapsed"] = both_sides and not group.get("switchTo")
            for child in (group.get("children") or []):
                child["collapsed"] = not child.get("switchTo")

        # 统一补上"单位"(组标题里 "N 个适配版本" 用)
        for group in groups:
            group.setdefault("unit", group.get("label") or "适配版本")
            group.setdefault("label", group["unit"])
            for child in (group.get("children") or []):
                child.setdefault("unit", child.get("label") or "适配版本")
                child.setdefault("label", child["unit"])

        def _split_snapshot_files(files_list: List[Dict]) -> List[Dict]:
            """把**资源自身**的快照版本从正式版里分出来。

            与"游戏版本是不是快照"无关 —— 那是组标题上的"· 快照"(游戏快照);
            这里看的是资源自己的版本号: 0.9.2-beta / 1.0-alpha / nightly / rc …。
            分出来后在中间插一条分区标题行(sectionLabel), 由界面渲染成小标题。
            """
            def _is_snap(row: Dict) -> bool:
                low = (str(row.get("name") or "") + " " + str(row.get("file") or "")).lower()
                return any(tag in low for tag in ("-beta", "-alpha", "-rc", "-pre",
                                                  "-snapshot", "-nightly", "-dev",
                                                  "snapshot", "nightly"))

            snaps = [r for r in files_list if _is_snap(r)]
            if not snaps or len(snaps) == len(files_list):
                return files_list          # 没有快照, 或全是快照 → 不用分段
            if any(r.get("sectionLabel") for r in files_list):
                return files_list          # 已经有分区标题(服务端按核心分区) → 不再打乱它
            out = [r for r in files_list if not _is_snap(r)]
            out.append({"sectionLabel": "资源快照版本（测试版）", "index": -1, "name": "",
                        "file": "", "size": "", "date": "", "downloads": "", "url": "",
                        "loaders": "", "versions": ""})
            out.extend(snaps)
            return out

        for group in groups:
            for version in (group.get("versions") or []):
                if version.get("files"):
                    version["files"] = _split_snapshot_files(version["files"])

        self._detail_groups = groups
        if rows:
            loaders_count = len({str(x).lower() for _l, _v in meta for x in _l})
            self._status = ("「%s」共 %d 个文件，%d 种加载器、%d 个适配版本"
                            % (self._detail_title, len(rows), loaders_count,
                               len({v for _l, vs in meta for v in vs[:1]})))
        else:
            self._status = "「%s」没有匹配当前版本/加载器的文件" % self._detail_title
        self.statusChanged.emit()
        self.detailChanged.emit()

    @Slot()
    def closeDetail(self) -> None:  # noqa: N802
        self._files.set_rows([])
        self._detail_groups = []
        self._detail_title = ""
        self.detailChanged.emit()

    # ------------------------------------------------------------ 下载
    def _download_kind(self) -> str:
        """当前**文件列表**属于哪一类资源。

        必须用详情页的快照 ``_detail_kind`` —— ``_kind`` 是搜索列表的分类, 在
        "数据包 ⇄ Mod 跳转"时会被临时改掉(见 jumpToKind 的说明)。
        """
        return str(self._detail_kind or self._kind or "mod").strip().lower()

    def _default_modpack_name(self) -> str:
        """命名对话框里预填的默认版本名 = 整合包的名称(按安装时同一套规则定案)。

        规则只有一处定义: ``core_resources._resolve_modpack_name`` —— 就是
        ``install_modpack`` 真正用的那个函数, 非法字符清理 / 重名加 ``-2`` 都在里面。
        所以用户**看得见**那个 ``-2``, 也可以改掉; 这里只是把一个名字交给界面,
        绝不直接开装(确认过才走 installPendingModpack)。
        """
        title = str(self._detail_title or "").strip() or "ModPack"
        try:
            resolved, _renamed = core_resources._resolve_modpack_name(
                self.launcher.root(), title)
            return str(resolved or title)
        except Exception as exc:  # noqa: BLE001
            print("[resources] 整合包默认名解析失败:", type(exc).__name__, exc, flush=True)
            return title

    @Slot(int)
    def downloadFile(self, index: int) -> None:  # noqa: N802
        """点文件行/「下载」按钮。

        整合包: **不在这里开任务** —— 先把默认版本名报给界面, 由用户确认(可改名)之后
        走 installPendingModpack(); 取消就什么都不发生。
        其它资源(Mod/资源包/数据包/光影包): 保持原样直接下载, 不弹任何框。
        """
        row = self._files.at(index)
        if not isinstance(row, dict) or not row.get("url"):
            return
        if self._download_kind() == "modpack":
            self._pending_modpack = {
                "kind": "modpack",
                "url": str(row.get("url") or ""),
                "file": str(row.get("file") or ""),
            }
            self.modpackNameRequested.emit(self._default_modpack_name())
            return
        self.startDownload(self._kind, str(row.get("url") or ""), str(row.get("file") or ""),
                           self._detail_title)

    @Slot(str)
    def installPendingModpack(self, name: str) -> None:  # noqa: N802
        """用**用户确认过的名字**安装刚才点下载的那个整合包。

        名字一路传到 ``install_modpack(..., instance_name=name)``(经
        launcher.startResourceDownload → ResourceDownloadWorker), 不是摆设。
        """
        pending = self._pending_modpack if isinstance(self._pending_modpack, dict) else None
        self._pending_modpack = None
        if not pending or not pending.get("url"):
            return
        self.startDownload("modpack", str(pending.get("url") or ""),
                           str(pending.get("file") or ""), str(name or "").strip())

    @Slot()
    def cancelPendingModpack(self) -> None:  # noqa: N802
        """命名对话框被取消: 丢掉待安装快照, 什么都不装。"""
        self._pending_modpack = None

    @Slot(str, str, str, str)
    def startDownload(self, kind: str, url: str, filename: str, name: str) -> None:
        """下载资源文件; kind 为 modpack 时按整包安装。

        走启动器的任务系统(和安装游戏一样: 任务管理页 + 右下角圆标进度/速度)。
        """
        kind_key = str(kind or "mod")
        game_dir = self._current_game_dir()
        if kind_key == "modpack":
            # 整合包要先落到缓存目录再由后台线程解包安装
            cache = os.path.join(core_paths.cache_dir(), "modpacks")
            core_paths.ensure_dir(cache)
            local = os.path.join(cache, core_paths.safe_name(filename or "pack.mrpack"))
            pack_name = name or os.path.splitext(os.path.basename(local))[0]
            self._status = "已开始安装整合包 %s…" % pack_name
            self.statusChanged.emit()
            self.launcher.startResourceDownload("modpack", url, os.path.basename(local),
                                                local, pack_name)
            return
        label = core_resources.KIND_LABELS.get(kind_key, "资源")
        self._status = "已开始下载 %s（可在右下角查看进度）" % label
        self.statusChanged.emit()
        self.launcher.startResourceDownload(kind_key, url, filename, game_dir, name)

    @Slot(str, int)
    def _on_download_progress(self, text: str, percent: int) -> None:
        self._status = text
        self.statusChanged.emit()

    @Slot(str, str)
    def _on_download_finished(self, message: str, path: str) -> None:
        self._loading = False
        self._status = message or "下载结束"
        self.loadingChanged.emit()
        self.statusChanged.emit()
        if message:
            try:
                self.launcher.toastRequested.emit(message)
            except Exception:  # noqa: BLE001
                pass
        kind = self._download_worker.kind if self._download_worker is not None else ""
        if kind == "modpack":
            try:
                self.launcher.refreshVersions()
            except Exception:  # noqa: BLE001
                pass

    def _pending_kind(self) -> str:
        return self._download_worker.kind if self._download_worker is not None else ""

    def _current_game_dir(self) -> str:
        """资源装到当前选中版本的游戏目录(遵守版本隔离)。"""
        try:
            root = self.launcher.root()
            vid = str(self.cfg.selected_version or "")
            if not vid:
                return root
            return core_launch.game_dir_for(self.cfg, root, vid)
        except Exception:  # noqa: BLE001
            return self.launcher.root()


def remote_download(url: str, dest: str, source: str, backend) -> bool:
    """下载到指定路径(整合包用)。"""
    from ..core import remote as core_remote
    return core_remote.download_file(
        url, dest, source=source,
        progress_cb=lambda done, total: backend._on_download_progress(
            "正在下载整合包 %d%%" % (int(100.0 * done / total) if total else 0),
            int(10 + 60.0 * done / total) if total else 10))
