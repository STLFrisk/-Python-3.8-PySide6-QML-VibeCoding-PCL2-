"""Java 检测与游戏启动 mixin(从 ``launcher.py`` 原样搬出, 只搬家不改逻辑)。

``LauncherBackend`` 通过 ``class LauncherBackend(TaskMixin, LaunchMixin, QObject)``
混入本类, 方法经 MRO 仍然挂在同一个对象上, QML 侧调用方式完全不变。

本段**没有** ``@Property(notify=...)``, 所有信号都是 ``self.xxx.emit()`` 形式,
所以不需要像 ``launcher_tasks`` 那样把 Signal 声明一起搬过来。
注意 mixin 里不要写 ``__init__``(会顶掉 ``QObject.__init__`` 的调用链)。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Slot

from ..core import launch as core_launch
from .workers import JavaScanWorker, ProcessReader, TailLogReader, WindowTitleWorker


class LaunchMixin:
    # ================================================================ Java
    @Slot()
    def detectJava(self) -> None:
        """后台检测 Java(要跑多次 java -version, 放主线程会卡动画)。"""
        if self._java_worker is not None and self._java_worker.isRunning():
            return
        self._java_worker = JavaScanWorker(self)
        self._java_worker.found.connect(self._on_javas_found)
        self._java_worker.start()

    @Slot(object)
    def _on_javas_found(self, items) -> None:
        self._javas = list(items or [])
        rows = [{"label": j.label(), "path": j.path, "version": j.version}
                for j in self._javas]
        self._java_model.set_rows(rows)
        self.statusChanged.emit()

    def _ensure_javas(self) -> None:
        """保证 Java 列表可用(启动游戏前调用)。

        后台检测可能还没结束, 这时绝不能当成"没装 Java"而拦下启动 —— 先等它,
        实在没有结果就同步检测一次兜底。
        """
        if self._javas:
            return
        worker = self._java_worker
        if worker is not None and worker.isRunning():
            worker.wait(6000)
        if not self._javas and worker is not None and getattr(worker, "items", None):
            self._on_javas_found(worker.items)
        if not self._javas:
            self._on_javas_found(core_launch.find_javas())

    def required_java(self) -> int:
        """当前版本需要的 Java 主版本(优先读版本 json 的 javaVersion)。"""
        ver = self.current_version()
        if ver is None:
            return core_launch.required_java_major("1.20.4")
        if ver.path and os.path.isdir(ver.path):
            try:
                need = core_launch.required_java_for_version(self.root(), ver.id)
                if need:
                    return need
            except Exception:  # noqa: BLE001
                pass
        return core_launch.required_java_major(ver.mc_version or ver.id)

    def java_path(self) -> str:
        configured = self.cfg.get("launch.java_path", "auto")
        if configured and configured != "auto" and os.path.exists(configured):
            return configured
        picked, ok = core_launch.pick_java(self._javas, self.required_java())
        if not ok:
            self.appendLog("[警告] 该版本需要 Java %d, 系统里没有满足要求的 Java, 已退回 %s"
                           % (self.required_java(), picked.label()))
        return picked.path

    # ================================================================ 启动游戏
    @Slot()
    def launchGame(self) -> None:
        if self._product_running():
            self.messageRequested.emit("提示", "游戏已经在运行了。", "info")
            return
        ver = self.current_version()
        if ver is None:
            if self.scanning:
                self.messageRequested.emit("请稍候", "正在扫描已安装的游戏版本，请稍后再试。", "info")
            else:
                self.messageRequested.emit("无法启动", "请先选择一个游戏版本。", "warn")
            return
        if not ver.installed or not ver.path:
            self.messageRequested.emit(
                "无法启动",
                "版本 %s 目前只是示例数据（磁盘上没有对应的游戏文件）。\n\n"
                "请点击「下载 → 原版游戏」安装一个真实版本，或先在「版本选择」里\n"
                "添加你真实的 .minecraft 文件夹。" % ver.id, "warn")
            return

        # Java 版本不够时先提醒(Java 21 跑需要 Java 25 的版本会立刻退出, 退出码 1)
        self._ensure_javas()
        configured = str(self.cfg.get("launch.java_path", "auto") or "auto")
        if configured.strip().lower() == "auto":
            required = self.required_java()
            picked, fits = core_launch.pick_java(self._javas, required)
            if not fits:
                self._pending_action = "launch_anyway"
                self.confirmRequested.emit(
                    "Java 版本可能不够",
                    "版本 %s 需要 Java %d，但系统里没有检测到满足要求的 Java。\n\n"
                    "现在将使用 %s（%s），游戏很可能启动失败。\n"
                    "建议到「设置 → 启动 → 高级选项」里手动指定合适的 javaw.exe。\n\n"
                    "是否仍然尝试启动？"
                    % (ver.id, required, picked.label(), picked.path))
                return
        self.doLaunch()

    @Slot()
    def doLaunch(self) -> None:
        ver = self.current_version()
        if ver is None or not ver.installed or not ver.path:
            return
        account = self.current_account()
        try:
            plan = core_launch.build_launch(self.root(), ver.id, account, self.cfg,
                                            self.java_path())
        except Exception as exc:  # noqa: BLE001
            self.messageRequested.emit("启动失败", "构建启动参数时出错：\n%s" % exc, "error")
            return

        # 输出写日志文件而不是管道: 管道写满会让游戏卡在启动阶段(进程在、窗口不出)
        self._log_path = os.path.join(ver.path, "pclpy_launch.log")
        self._log_handle = core_launch.open_output_log(self._log_path)
        if self._log_handle is None:
            # 版本目录不可写(比如装在只读盘上)时, 退回到启动器自己的数据目录
            fallback = os.path.join(os.path.dirname(os.path.abspath(self.cfg.path)),
                                    "logs", "%s.log" % ver.id)
            self._log_handle = core_launch.open_output_log(fallback)
            if self._log_handle is not None:
                self._log_path = fallback
        self._log_tail = None
        try:
            process = core_launch.start_process(plan, stdout=self._log_handle)
        except Exception as exc:  # noqa: BLE001
            self._close_log()
            self.messageRequested.emit("启动失败", "无法启动游戏进程：\n%s" % exc, "error")
            return
        self._process = process
        self._set_launch_state("running")
        self.setStatus("游戏已启动 (PID %d)" % process.pid)
        self.appendLog("[启动器] 使用 Java: %s" % plan.java)
        self.appendLog("[启动器] 游戏目录: %s" % plan.cwd)
        if plan.warnings:
            self.appendLog("\n".join("[警告] " + w for w in plan.warnings))
        self.appendLog("[启动器] 输出日志: %s" % self._log_path)

        self._reader = ProcessReader(process, self)
        self._reader.line.connect(self.appendLog)
        self._reader.exited.connect(self._on_game_exit)
        self._reader.start()

        if self._log_path:
            self._log_tail = TailLogReader(self._log_path, self)
            self._log_tail.line.connect(self.appendLog)
            self._log_tail.start()

        # 自定义游戏窗口标题: 现代版本不支持 --title, 由启动器直接改窗口标题
        wanted = str(self.cfg.get("launch.window_title", "") or "").strip()
        suffix = ""
        if not wanted:
            # 没设窗口标题时, 「自定义信息」按 PCL2 的做法追加在游戏标题后面
            suffix = str(self.cfg.get("launch.custom_info", "") or "").strip()
        if wanted or suffix:
            self._title_worker = WindowTitleWorker(process.pid, wanted, suffix, self)
            self._title_worker.start()
            self.appendLog("[启动器] 窗口标题: %s"
                           % (wanted if wanted else ("<游戏标题> - " + suffix)))

        # 把关键启动参数写进日志, 出问题时能直接对照(加载器相关的三个属性)
        for value in plan.command:
            if value.startswith(("-DmergeModules", "-Dfml.modFolders", "-DignoreList",
                                 "-p", "--add-modules")):
                self.appendLog("[启动器] %s" % value[:400])

    def _close_log(self) -> None:
        handle = getattr(self, "_log_handle", None)
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
        self._log_handle = None

    def _tail_lines(self, count: int = 18) -> str:
        path = getattr(self, "_log_path", "")
        if not path or not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = [ln.rstrip() for ln in fh.readlines() if ln.strip()]
        except OSError:
            return ""
        return "\n".join(lines[-count:])

    def _product_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _on_game_exit(self, code: int) -> None:
        self._process = None
        tail = getattr(self, "_log_tail", None)
        if tail is not None:
            tail.stop()
            try:
                tail.wait(2000)
            except Exception:  # noqa: BLE001
                pass
            self._log_tail = None
        self._close_log()
        self._set_launch_state("idle")
        self.setStatus("游戏已退出 (代码 %s)" % code)
        self.appendLog("游戏进程已退出, 退出代码 %s" % code)
        if code != 0:
            detail = self._tail_lines(14)
            self.messageRequested.emit(
                "游戏异常退出",
                "游戏进程以退出代码 %s 结束。\n\n最后几行日志：\n%s\n\n"
                "完整日志: %s" % (code, detail or "(无输出)", getattr(self, "_log_path", "")),
                "error")

    def _set_launch_state(self, state: str) -> None:
        self._launch_state = state
        self.launchStateChanged.emit()
