"""任务系统 mixin(从 ``launcher.py`` 原样搬出, 只搬家不改逻辑)。

``LauncherBackend`` 通过 ``class LauncherBackend(TaskMixin, QObject)`` 混入本类,
方法经 MRO 仍然挂在同一个对象上, QML 侧调用方式完全不变。

两个必须注意的坑(实测):
  * mixin 里**不要写 ``__init__``** —— 会顶掉 ``QObject.__init__`` 的调用链,
    实测直接 ``RuntimeError: '__init__' method of object's base class not called``。
  * ``tasksChanged`` 信号只在**本类**声明一次: 若 ``LauncherBackend`` 再声明一遍,
    子类那份会 shadow 掉这里的, 而 ``@Property(notify=tasksChanged)`` 绑的是这里的,
    QML 绑定就会**静默不再刷新**。
"""
from __future__ import annotations

import re
from typing import Dict

from PySide6.QtCore import Property, QObject, Signal, Slot


class TaskMixin:
    # 任务事件信号(原来在 LauncherBackend 里; 见模块头注释的 shadow 坑)
    tasksChanged = Signal()

    # ================================================================ 任务管理
    @Property(QObject, constant=True)
    def taskModel(self):  # noqa: N802
        return self._task_model

    @Property(int, notify=tasksChanged)
    def taskCount(self) -> int:
        return len(self._tasks)

    @Property(bool, notify=tasksChanged)
    def hasRunningTask(self) -> bool:  # noqa: N802
        return any(t.get("state") == "running" for t in self._tasks)

    @Property(int, notify=tasksChanged)
    def overallPercent(self) -> int:  # noqa: N802
        """所有进行中任务的总进度(没有任务时按 100)。"""
        running = [t for t in self._tasks if t.get("state") == "running"]
        if not running:
            return 100
        return int(sum(float(t.get("percent") or 0) for t in running) / len(running))

    @Property(str, notify=tasksChanged)
    def speedText(self) -> str:  # noqa: N802
        # 左栏显示的是**全局单点速度**(不再是各任务速度相加 —— 那样多任务会重复累加)。
        if not any(t.get("state") == "running" for t in self._tasks):
            return "--"
        return self._format_speed(self._speed)

    @Property(str, notify=tasksChanged)
    def remainingText(self) -> str:  # noqa: N802
        counts = [int(t.get("remaining") or 0) for t in self._tasks
                  if t.get("state") == "running" and int(t.get("remaining") or 0) > 0]
        if not counts:
            return "--"
        return str(sum(counts))

    def _new_task(self, title: str, kind: str, steps, worker) -> Dict:
        self._task_seq += 1
        task = {
            "taskId": "task-%d" % self._task_seq,
            "title": str(title),
            "kind": str(kind),
            "state": "running",
            "stateText": "进行中",
            "percent": 0,
            "speed": 0.0,
            "speedText": "--",
            "remaining": -1,
            "remainingText": "--",
            "steps": [{"id": sid, "name": name, "state": "wait", "percent": 0}
                      for sid, name in steps],
            "worker": worker,
            "bytes": 0,
            "lastBytes": 0,
        }
        self._tasks.append(task)
        self._rebuild_tasks()
        return task

    def _task_index(self, task: Dict) -> int:
        try:
            return self._tasks.index(task)
        except ValueError:
            return -1

    def _task_row(self, task: Dict) -> Dict:
        return {
            "taskId": task.get("taskId", ""),
            "title": task.get("title", ""),
            "kind": task.get("kind", ""),
            "state": task.get("state", "running"),
            "stateText": task.get("stateText", ""),
            "percent": int(task.get("percent") or 0),
            "speedText": task.get("speedText", "--"),
            "remainingText": task.get("remainingText", "--"),
            "steps": [dict(step) for step in (task.get("steps") or [])],
            "canCancel": task.get("state") == "running",
            "canClear": task.get("state") != "running",
        }

    def _rebuild_tasks(self) -> None:
        self._task_model.set_rows([self._task_row(t) for t in self._tasks])
        self.tasksChanged.emit()

    def _update_task(self, task: Dict) -> None:
        index = self._task_index(task)
        if index < 0:
            return
        self._task_model.update_row(index, self._task_row(task))
        self.tasksChanged.emit()

    def _apply_progress(self, task: Dict, text: str, percent: int) -> None:
        """把一帧进度写进任务字典(**不**刷模型 —— 由调用方决定刷几次)。"""
        task["percent"] = max(int(task.get("percent") or 0), int(percent))
        if text:
            task["text"] = text
            match = re.search(r"(\d+)\s*/\s*(\d+)", str(text))
            if match:
                done, total = int(match.group(1)), int(match.group(2))
                task["remaining"] = max(0, total - done)
                task["remainingText"] = str(task["remaining"])

    def _apply_phase(self, task: Dict, phase_id: str, percent: int, text: str) -> None:
        """把一帧阶段进度写进任务字典(**不**刷模型)。"""
        steps = task.get("steps") or []
        hit = -1
        for index, step in enumerate(steps):
            if step.get("id") == phase_id:
                hit = index
                break
        if hit >= 0:
            for index, step in enumerate(steps):
                if index < hit:
                    step["state"] = "done"
                    step["percent"] = 100
                elif index == hit:
                    step["state"] = "done" if int(percent) >= 100 else "running"
                    step["percent"] = int(percent)
                    if text:
                        step["name"] = text
        if phase_id == "done":
            for step in steps:
                step["state"] = "done"
                step["percent"] = 100

    def _on_task_progress(self, task: Dict, text: str, percent: int) -> None:
        self._apply_progress(task, text, percent)
        self._update_task(task)

    def _on_task_phase(self, task: Dict, phase_id: str, percent: int, text: str) -> None:
        self._apply_phase(task, phase_id, percent, text)
        self._update_task(task)

    def _pull_task(self, task: Dict) -> bool:
        """从 worker 对象上取回累积的进度(不刷模型), 有新进度返回 True。

        下载线程每个数据块都回调, 但它们**只累积**在 worker 的普通变量上
        (见 workers.TaskWorker.report / report_phase), 界面在这里按 200ms 的节拍
        统一 pull 一次 —— 这样几十条连接也不会把主线程的信号队列灌满。
        """
        worker = task.get("worker")
        taker = getattr(worker, "take_ui_state", None)
        if not callable(taker):
            return False
        try:
            state = taker()
        except Exception:  # noqa: BLE001
            return False
        if not state:
            return False
        text = str(state.get("text") or "")
        try:
            percent = int(state.get("percent") or 0)
        except Exception:  # noqa: BLE001
            percent = 0
        if text or percent > 0:
            self._apply_progress(task, text, percent)
        for phase_id, item in (state.get("phases") or {}).items():
            try:
                self._apply_phase(task, str(phase_id), int(item[0]), str(item[1]))
            except Exception:  # noqa: BLE001
                continue
        return True

    def _tick_speed(self) -> None:
        """单点计算下载速度 + 统一刷新任务界面(每 200ms 一拍)。

        与 PCL2 一致(引擎侧单点算速度, 界面只读这个值):
          * 采样间隔 200ms
          * 窗口 ≈3 秒(15 个采样), **越新的采样权重越大**
        没有任何任务在跑时清空窗口, 速度归零。

        本方法同时是任务界面的**唯一刷新点**: 每个运行中的任务先 pull 一次 worker
        上累积的进度, 再连同速度一起发**一次**模型更新(以前是每个进度回调各刷一次,
        任务页委托里的 12 行步骤每次都被重建, 高并发时直接把主线程占满)。
        """
        total = 0
        for task in self._tasks:
            if task.get("state") != "running":
                continue
            worker = task.get("worker")
            if worker is None or not hasattr(worker, "total_bytes"):
                continue
            try:
                total += int(worker.total_bytes())
            except Exception:  # noqa: BLE001
                continue
        if not any(t.get("state") == "running" for t in self._tasks):
            self._bytes_global = 0
            self._speed_window = []
            self._speed = 0.0
            return
        delta = max(0, total - int(self._bytes_global))
        self._bytes_global = max(total, int(self._bytes_global))
        self._speed_window.append(delta / 0.2)
        if len(self._speed_window) > 15:
            del self._speed_window[:len(self._speed_window) - 15]
        weight_sum = 0.0
        value = 0.0
        for index, sample in enumerate(self._speed_window):
            weight = float(index + 1)
            value += sample * weight
            weight_sum += weight
        self._speed = (value / weight_sum) if weight_sum else 0.0
        text = self._format_speed(self._speed)
        for task in self._tasks:
            if task.get("state") != "running":
                continue
            self._pull_task(task)
            task["speed"] = self._speed
            task["speedText"] = text
            worker = task.get("worker")
            if worker is not None and hasattr(worker, "total_bytes"):
                try:
                    task["bytes"] = int(worker.total_bytes())
                except Exception:  # noqa: BLE001
                    pass
            self._update_task(task)

    @staticmethod
    def _format_speed(value: float) -> str:
        if value <= 0:
            return "--"
        if value >= 1024 * 1024:
            return "%.1f M/s" % (value / (1024.0 * 1024.0))
        if value >= 1024:
            return "%.0f K/s" % (value / 1024.0)
        return "%.0f B/s" % value

    def _finish_task(self, task: Dict, state: str, state_text: str) -> None:
        # 结束前先把 worker 上还没被 pull 走的最后一帧收干净:
        # 任务变 done 后 _tick_speed 不会再拉它, 不在这里收就会"停在 99%/旧文案"。
        self._pull_task(task)
        task["state"] = state
        task["stateText"] = state_text
        task["speed"] = 0.0
        task["speedText"] = "--"
        task["remaining"] = -1
        task["remainingText"] = "--"
        if state == "done":
            task["percent"] = 100
            for step in (task.get("steps") or []):
                step["state"] = "done"
                step["percent"] = 100
        self._update_task(task)

    @Slot(int)
    def cancelTaskAt(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._tasks):
            worker = self._tasks[index].get("worker")
            if worker is not None and worker.isRunning():
                worker.cancel()
                self._tasks[index]["stateText"] = "正在取消…"
                self._update_task(self._tasks[index])

    @Slot(int)
    def removeTaskAt(self, index: int) -> None:  # noqa: N802
        """移除一条已结束的任务(进行中的不允许移除)。"""
        if 0 <= index < len(self._tasks):
            if self._tasks[index].get("state") == "running":
                return
            del self._tasks[index]
            self._rebuild_tasks()

    @Slot()
    def clearFinishedTasks(self) -> None:  # noqa: N802
        self._tasks = [t for t in self._tasks if t.get("state") == "running"]
        self._rebuild_tasks()
