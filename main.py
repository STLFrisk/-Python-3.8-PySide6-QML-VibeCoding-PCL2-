#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PCL-Py: 基于 PySide6 + QML 的 Minecraft 启动器(仿 PCL2 界面)。

用法:
    python main.py                 启动启动器
    python main.py --home D:\\mc    指定配置目录(默认 ~/.pclpy)
    python main.py --shot shots    生成界面截图后退出(用于开发验证)
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="PCL-Py", description="基于 PySide6 + QML 的 Minecraft 启动器")
    parser.add_argument("--home", default="", help="配置目录(默认 ~/.pclpy)")
    parser.add_argument("--shot", default="", help="截图输出目录, 截图后退出")
    return parser.parse_known_args(argv)[0]


def _stop_background_threads(launcher, timeout_ms: int = 1500) -> None:
    """收尾时给仍在跑的后台 QThread 发停止信号(尽力而为, 失败也照样退出)。

    这些线程是版本列表刷新(ManifestWorker)、社区资源搜索/文件列表、版本扫描、
    Java 扫描等; 收尾那一刻它们可能刚好还在跑 —— 实测复现过: 第 1 次退出码
    0xC0000409(STATUS_STACK_BUFFER_OVERRUN), stderr 只有一行
    ``QThread: Destroyed while thread is still running``。

    这里对每个线程做两件事:

    * ``requestInterruption()``: worker 里若检查 ``isInterruptionRequested()``
      就能提前收工(``TailLogReader`` / 轮询循环靠这个退出);
    * ``quit()`` + ``wait(剩余预算)``: 有事件循环的线程会退出 ``exec()``。等待
      总时长有上限, 卡住的网络请求不会拖住退出。

    线程构造时都传了 parent(backend / download / resources ...), 所以用
    ``findChildren(QThread)`` 枚举; 取不到就跳过 —— 后面 ``os._exit()`` 不会再
    跑 Qt 析构, 所以就算一个都没停住也不会因此崩溃。
    """
    try:
        from PySide6.QtCore import QThread
    except Exception:  # noqa: BLE001
        return

    holders = [launcher]
    for name in ("backend", "download", "resources", "settings", "version_settings"):
        holders.append(getattr(launcher, name, None))

    threads = []
    for holder in holders:
        if holder is None:
            continue
        try:
            found = holder.findChildren(QThread)
        except Exception:  # noqa: BLE001
            continue
        for thread in found:
            if thread not in threads:
                threads.append(thread)
    if not threads:
        return

    for thread in threads:
        for call in ("requestInterruption", "quit"):
            try:
                getattr(thread, call)()
            except Exception:  # noqa: BLE001
                pass

    deadline = time.time() + max(0.0, timeout_ms / 1000.0)
    for thread in threads:
        remaining = int((deadline - time.time()) * 1000)
        if remaining <= 0:
            break
        try:
            thread.wait(remaining)
        except Exception:  # noqa: BLE001
            pass


def _exit_now(code, launcher=None):
    """收尾退出: 先停后台线程 / 落盘 / 冲刷输出, 然后跳过 Qt 与 Python 的析构。

    为什么必须跳过析构: 收尾那一刻后台 QThread 有可能仍在运行, 解释器析构它时
    Qt 会直接 abort —— 实测退出码 0xC0000409。它是**间歇性**的(取决于线程是否
    刚好跑完), 而且 abort 会吞掉已经写好的 stdout(截图路径的 ``saved:`` 列表)。

    ``os._exit()`` 会跳过**所有**清理, 包括 atexit / 缓冲刷新 / Qt 析构, 所以
    在它之前必须自己把该做的事做完:

    1. ``_stop_background_threads()``: 给下载 / 扫描线程发停止信号并短暂等待;
    2. ``config.save(force=True)``: 配置平时是"改一次写一次盘 + 600ms 防抖"
       (``LauncherBackend`` 里挂了 ``cfg.defer = self._save_timer.start``), 事件
       循环一停那个定时器就永远不会触发, 必须 force 立刻落盘 —— 否则跳过析构
       会丢最后一次设置改动;
    3. ``sys.stdout / sys.stderr.flush()``: 否则管道缓冲里的 ``saved:`` 输出丢失。
    """
    if launcher is not None:
        try:
            _stop_background_threads(launcher)
        except Exception:  # noqa: BLE001
            pass
        try:
            launcher.config.save(force=True)   # 兜住界面上还没落盘的防抖写入
        except Exception:  # noqa: BLE001
            pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(int(code))


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    args = parse_args(argv)
    # 必须在导入 pclpy.core 之前设置, 因为配置目录在导入时确定
    if args.home:
        os.environ["PCLPY_HOME"] = os.path.abspath(args.home)
    if args.shot:
        os.environ["QT_QUICK_BACKEND"] = os.environ.get("QT_QUICK_BACKEND", "software")

    from pclpy.app import LauncherApp

    launcher = LauncherApp(argv)
    if not launcher.ok:
        for err in launcher.qml_errors():
            sys.stderr.write(err + "\n")
        sys.stderr.write("QML 加载失败\n")
        _exit_now(1, launcher)

    if args.shot:
        from tools.shots import capture
        capture(launcher, args.shot)
        _exit_now(0, launcher)

    code = launcher.run()
    _exit_now(code, launcher)


if __name__ == "__main__":
    sys.exit(main())
