"""后台线程: 安装/下载、整合包导出、游戏进程输出读取。

这些线程只做阻塞的 IO 工作, 进度通过信号回传 GUI 线程。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal


class TaskWorker(QThread):
    """带取消能力的通用后台任务。"""

    progress = Signal(str, int)          # 文本, 百分比
    phase = Signal(str, int, str)        # 阶段 id, 阶段内百分比, 文本
    succeeded = Signal(str)              # 成功提示
    failed = Signal(str)                 # 失败原因

    # 进度**推送**的最小间隔(秒)。
    #
    # 下载线程是"每个数据块/每个文件"都回调一次的: 整合包默认 8 个文件并行 × 每文件
    # 最多 8 段 = 峰值几十条连接。如果每一次回调都跨线程 emit, 主线程的事件队列会被
    # 彻底灌满(实测界面每秒只能处理 11 次左右, 队列越积越多, 界面变成"未响应")。
    # 因此:
    #   * 字节账本 ``add_bytes`` 照旧只做累加, **不发任何信号**;
    #   * 文本 / 百分比 / 阶段进度只**累积**在对象上, 由界面的 200ms 定时器调用
    #     ``take_ui_state()`` 统一 pull;
    #   * 为了不破坏"连接 progress / phase 信号"的既有写法, 仍按这个间隔补推一次;
    #     百分比首次到 100 时强制补推, 保证最后一帧不丢(进度不会停在 99%)。
    PUSH_INTERVAL = 0.1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()
        self._byte_lock = threading.Lock()
        self._bytes = 0
        # ---- 进度累积(供界面 pull / 定期 push)
        self._ui_lock = threading.Lock()
        self._ui_text = ""
        self._ui_percent = 0
        self._ui_phases: Dict[str, tuple] = {}     # 阶段 id -> (百分比, 文本)
        self._ui_dirty = False
        self._ui_pushed = 0.0                      # 上次推送时刻(单调时钟)

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _should_push(self, force: bool) -> bool:
        """该不该补推一次(必须已持有 ``_ui_lock``)。"""
        now = time.monotonic()
        if not force and (now - self._ui_pushed) < self.PUSH_INTERVAL:
            return False
        self._ui_pushed = now
        return True

    def report(self, text: str, percent: int) -> None:
        """累积任务进度(文本/百分比), 按 PUSH_INTERVAL 节流后推送。"""
        text = str(text)
        try:
            value = int(percent)
        except Exception:  # noqa: BLE001
            value = 0
        payload = None
        with self._ui_lock:
            crossed = value >= 100 and self._ui_percent < 100    # 首次到 100, 必须发
            if value > self._ui_percent:
                self._ui_percent = value
            if text:
                self._ui_text = text
            self._ui_dirty = True
            if self._should_push(crossed):
                payload = (self._ui_text, self._ui_percent)
        if payload is not None:
            self.progress.emit(str(payload[0]), int(payload[1]))

    def report_phase(self, phase_id: str, percent: int, text: str) -> None:
        """累积某个阶段的进度(同一阶段只保留"见过的最大值"), 节流后推送。"""
        key = str(phase_id)
        text = str(text)
        try:
            value = int(percent)
        except Exception:  # noqa: BLE001
            value = 0
        payload = None
        with self._ui_lock:
            old = self._ui_phases.get(key)
            crossed = value >= 100 and (old is None or int(old[0]) < 100)
            if old is None or value >= int(old[0]):
                self._ui_phases[key] = (value, text)
            self._ui_dirty = True
            if self._should_push(crossed):
                payload = (key, value, text)
        if payload is not None:
            self.phase.emit(str(payload[0]), int(payload[1]), str(payload[2]))

    def take_ui_state(self):
        """取走累积的进度(界面 200ms 定时器统一 pull), 取走后清空。

        返回 ``{"text": 文本, "percent": 百分比, "phases": {阶段id: (百分比, 文本)}}``;
        没有新进度时返回 ``None``。文本与百分比是"最新已知值"(不随 take 清掉),
        所以即使某一帧没被取走, 最终值也不会丢。
        """
        with self._ui_lock:
            if not self._ui_dirty and not self._ui_phases:
                return None
            state = {"text": self._ui_text, "percent": int(self._ui_percent),
                     "phases": dict(self._ui_phases)}
            self._ui_phases = {}
            self._ui_dirty = False
            return state

    def add_bytes(self, delta: int) -> None:
        """线程安全地累加已下载字节(不发信号 —— 速度由界面单点计算)。"""
        try:
            with self._byte_lock:
                self._bytes += int(delta)
        except Exception:  # noqa: BLE001
            pass

    def total_bytes(self) -> int:
        with self._byte_lock:
            return int(self._bytes)


class InstallWorker(TaskWorker):
    """安装原版 / Fabric 版本。mode: 'vanilla' | 'fabric'"""

    def __init__(self, mode: str, mc_version: str, root: str, cfg,
                 loader_version: str = "", target_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.mc_version = mc_version
        self.root = root
        self.cfg = cfg
        self.loader_version = loader_version
        self.target_name = target_name

    def run(self) -> None:  # noqa: D102
        from ..core import install
        try:
            mode = str(self.mode or "vanilla").lower()
            target = str(self.target_name or "").strip()
            if mode == "fabric":
                vid = install.install_fabric(
                    self.mc_version, self.loader_version, self.root, self.cfg,
                    progress_cb=self.report, cancel_cb=self.is_cancelled,
                    phase_cb=self.report_phase, bytes_cb=self.add_bytes)
                # 装完立刻自包含(合并父 json + 复制客户端 jar + 清 inheritsFrom):
                # 新装的加载器版本从此**不依赖原版**, 删/改原版都不影响它。
                install.make_self_contained(self.root, vid)
                if target and target != vid:
                    # 自定义命名: 复制一份独立版本(而不是把新装的搬走)
                    vid = install.copy_version_as(self.root, vid, target)
            elif mode == "quilt":
                vid = install.install_quilt(
                    self.mc_version, self.loader_version, self.root, self.cfg,
                    progress_cb=self.report, cancel_cb=self.is_cancelled,
                    phase_cb=self.report_phase, bytes_cb=self.add_bytes)
                install.make_self_contained(self.root, vid)
                if target and target != vid:
                    vid = install.copy_version_as(self.root, vid, target)
            elif mode in ("forge", "neoforge"):
                vid = install.install_forge_like(
                    mode, self.mc_version, self.loader_version, self.root, self.cfg,
                    progress_cb=self.report, cancel_cb=self.is_cancelled,
                    phase_cb=self.report_phase, bytes_cb=self.add_bytes)
                # 先统一成 PCL 风格命名(安装器自己给的名字比较乱)
                label = "Forge" if mode == "forge" else "NeoForge"
                auto_name = "%s-%s_%s" % (self.mc_version, label, self.loader_version)
                vid = install.rename_version(self.root, vid, auto_name)
                install.make_self_contained(self.root, vid)
                # 用户还额外指定了名字 → 再复制一份独立实例(保留统一命名的那份)
                if target and target != vid:
                    vid = install.copy_version_as(self.root, vid, target)
            else:
                vid = install.install_vanilla(
                    self.mc_version, self.root, self.cfg,
                    progress_cb=self.report, cancel_cb=self.is_cancelled,
                    phase_cb=self.report_phase, bytes_cb=self.add_bytes)
                # 自定义命名: **完整复制**一份独立版本(自己的 jar + json + 资源),
                # 而不是继承壳 —— 用户要的是两份互不依赖的实例。
                if target and target != vid:
                    vid = install.copy_version_as(self.root, vid, target)
            install.clear_installing(self.root, vid)
            self.succeeded.emit(str(vid))
        except Exception as exc:  # noqa: BLE001
            # ⑥-2: 安装失败 → 清掉"安装中"占位, 并清理没有用户数据的半成品版本目录
            for name in install.cleanup_unfinished(self.root):
                self.report("已清理未完成的版本 %s" % name, 0)
            self.failed.emit(str(exc) or "安装失败")


class ExportWorker(TaskWorker):
    """导出整合包。"""

    def __init__(self, root: str, version_id: str, out_path: str, options: Dict,
                 parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self.version_id = version_id
        self.out_path = out_path
        self.options = options

    def run(self) -> None:  # noqa: D102
        from ..core import packexport
        try:
            path = packexport.export_pack(
                self.root, self.version_id, self.out_path, self.options,
                progress_cb=self.report, cancel_cb=self.is_cancelled)
            self.succeeded.emit(str(path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc) or "导出失败")


class WindowTitleWorker(QThread):
    """在游戏启动后把它的窗口标题改成用户设置的名字(或追加自定义信息)。"""

    def __init__(self, pid: int, title: str, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        self.pid = int(pid)
        self.title = str(title)
        self.suffix = str(suffix)

    def run(self) -> None:  # noqa: D102
        try:
            from ..core import launch
            launch.set_window_title(self.pid, self.title, self.suffix)
        except Exception:  # noqa: BLE001
            pass


class VersionScanWorker(QThread):
    """后台扫描已安装版本(避免大目录扫描卡住界面)。"""

    scanned = Signal(object)

    def __init__(self, root: str, parent=None) -> None:
        super().__init__(parent)
        self.root = str(root)

    def run(self) -> None:  # noqa: D102
        try:
            from ..core import versions
            items = versions.scan_folder(self.root) if os.path.isdir(self.root) else []
        except Exception:  # noqa: BLE001
            import traceback
            print("[CraftPilot] 扫描版本失败:", traceback.format_exc())
            items = []
        if not items:
            print("[CraftPilot] 扫描版本: root=%r 结果为空" % self.root)
        self.scanned.emit(items)


class JavaScanWorker(QThread):
    """后台查找 Java(要跑多次 java -version, 不能放主线程)。"""

    found = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items = []

    def run(self) -> None:  # noqa: D102
        items = []
        try:
            from ..core import launch
            items = launch.find_javas()
        except Exception:  # noqa: BLE001
            import traceback
            print("[CraftPilot] 检测 Java 失败:", traceback.format_exc())
        self.items = items
        self.found.emit(items)


class ResourceDownloadWorker(TaskWorker):
    """社区资源下载 / 整合包安装(走和安装游戏一样的任务系统)。"""

    saved = Signal(str)          # 落盘路径(供界面提示/打开文件夹)

    def __init__(self, kind: str, url: str, filename: str, game_dir: str, root: str,
                 name: str, source: str = "official", parent=None) -> None:
        super().__init__(parent)
        self.kind = str(kind or "mod")
        self.url = url
        self.filename = filename
        self.game_dir = game_dir
        self.root = root
        self.name = name
        self.source = source

    def run(self) -> None:  # noqa: D102
        from ..core import resources as core_resources
        try:
            label = core_resources.KIND_LABELS.get(self.kind, "资源")
            if self.kind == "modpack":
                if self.url:
                    self.report_phase("prepare", 5, "下载整合包")
                    self.report("下载整合包 0/1（0%）", 3)
                    pack = {"last": 0}

                    def _bytes(done, total):
                        # 字节增量 → 速度显示
                        delta = int(done) - int(pack["last"])
                        if delta > 0:
                            pack["last"] = int(done)
                            try:
                                self.add_bytes(delta)
                            except Exception:  # noqa: BLE001
                                pass
                        ratio = (float(done) / float(total)) if total else 0.0
                        pct = int(3 + 37.0 * ratio)
                        text = "下载整合包 %d/1（%d%%）" % (1 if ratio >= 1 else 0,
                                                            int(ratio * 100))
                        self.report(text, pct)
                        self.report_phase("prepare", pct, "下载整合包")

                    from ..core import remote as core_remote
                    if not core_remote.download_file(self.url, self.game_dir,
                                                     source=self.source, progress_cb=_bytes,
                                                     cancel_cb=self.is_cancelled):
                        self.failed.emit("整合包下载失败")
                        return
                    self.report_phase("prepare", 100, "下载整合包")
                self.report_phase("files", 0, "下载整合包文件")
                self.report("下载整合包文件…", 40)
                # 8 个线程并发回调, 百分比必须取"见过的最大值"才单调 ——
                # 否则会在"文件A 80% → 文件B 5%"之间来回跳, 看起来像字节级响应失效
                guard = {"overall": 40, "files": 0}

                def _pack_progress(pct, text):
                    # 关键: 既更新任务总进度, 也更新"下载整合包文件"这一步的进度,
                    # 否则会出现"任务 96% 而步骤还停在 0%"的怪现象
                    pct = max(0, min(100, int(pct)))
                    files_pct = max(guard["files"], pct)
                    overall = int(40 + 57.0 * files_pct / 100.0)
                    overall = max(guard["overall"], min(97, overall))
                    guard["files"] = files_pct
                    guard["overall"] = overall
                    self.report(text, overall)
                    self.report_phase("files", files_pct, text)

                def _pack_phase(pid, pct, text):
                    name = "files" if pid == "files" else ("overrides" if pid == "overrides"
                                                           else pid)
                    self.report_phase(name, pct, text)
                    if name == "overrides":
                        self.report(text, int(97 + 1.0 * max(0, min(100, int(pct))) / 100.0))

                version_id = core_resources.install_modpack(
                    self.game_dir, self.root, self.name, cancel_cb=self.is_cancelled,
                    progress_cb=_pack_progress, phase_cb=_pack_phase,
                    bytes_cb=self.add_bytes)          # 字节增量 → 速度显示
                self.report_phase("files", 100, "下载整合包文件")
                self.report_phase("overrides", 100, "解压覆盖文件")
                self.report_phase("done", 100, "写入版本")
                self.succeeded.emit("整合包已安装为版本 %s" % version_id)
                return

            self.report_phase("prepare", 20, "准备下载")
            self.report("下载文件 0/1（0%）", 5)
            counter = {"last": 0}

            def _progress(done, total):
                # 记录字节增量 → 任务页的"下载速度"才能显示
                delta = int(done) - int(counter["last"])
                if delta > 0:
                    counter["last"] = int(done)
                    try:
                        self.add_bytes(delta)
                    except Exception:  # noqa: BLE001
                        pass
                ratio = (float(done) / float(total)) if total else 0.0
                pct = int(5 + 90.0 * ratio)
                # 文本带 done/total, 让"剩余文件"也能显示
                self.report("下载文件 %d/1（%d%%）" % (1 if ratio >= 1 else 0, int(ratio * 100)),
                            pct)
                self.report_phase("download", pct, "下载文件")

            path = core_resources.install_file(self.url, self.filename, self.game_dir,
                                               self.kind, self.source,
                                               progress_cb=_progress,
                                               cancel_cb=self.is_cancelled)
            self.report_phase("download", 100, "下载文件")
            self.report("下载文件 1/1（100%）", 100)
            self.saved.emit(path)
            self.succeeded.emit("%s 已下载到 %s" % (label, path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc) or "下载失败")


class ProcessReader(QThread):
    """等待游戏进程退出, 并在退出时通知界面。

    注意: 输出默认走日志文件(见 start_process), 这里不再从管道读取 —— 一旦读取线程
    出问题, 管道写满就会让游戏卡在启动阶段(表现为"进程在, 窗口不出来")。
    如果确实拿到的是管道, 也会做 str/bytes 兼容的读取兜底。
    """

    line = Signal(str)
    exited = Signal(int)

    def __init__(self, process: subprocess.Popen, parent=None) -> None:
        super().__init__(parent)
        self.process = process

    def run(self) -> None:  # noqa: D102
        stream = getattr(self.process, "stdout", None)
        if stream is not None:
            try:
                for raw in iter(stream.readline, ""):
                    if not raw:
                        break
                    if isinstance(raw, bytes):
                        text = raw.decode("utf-8", errors="ignore")
                    else:
                        text = str(raw)
                    text = text.rstrip("\r\n")
                    if text:
                        self.line.emit(text)
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
        try:
            code = self.process.wait()
        except Exception:  # noqa: BLE001
            code = -1
        # Windows 下 wait() 可能给出无符号值(4294967294), 必须转回 int32 再发信号,
        # 否则 Qt 的 int 参数会溢出。
        try:
            code = int(code)
        except Exception:  # noqa: BLE001
            code = -1
        if code > 0x7FFFFFFF:
            code -= 0x100000000
        if code < -0x80000000 or code > 0x7FFFFFFF:
            code = -1
        self.exited.emit(int(code))


class TailLogReader(QThread):
    """实时跟进游戏日志文件, 把新增行发给界面(不会阻塞游戏进程)。"""

    line = Signal(str)

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D102
        import os
        import time
        position = 0
        for _ in range(40):  # 最多等 2 秒, 等日志文件出现
            if self._stop.is_set() or os.path.exists(self.path):
                break
            time.sleep(0.05)
        while not self._stop.is_set():
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8", errors="ignore") as fh:
                        fh.seek(position)
                        for raw in fh:
                            self.line.emit(raw.rstrip("\r\n"))
                        position = fh.tell()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)
