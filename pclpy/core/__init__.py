"""PCLPy 纯 Python 核心层(不依赖 Qt)。

包含: 路径工具、配置、账号、版本扫描、模组管理、网络下载、安装、
启动命令构建、整合包导入导出与内置资源目录。

上层 Qt 界面直接 `from pclpy.core import versions, config, ...` 使用即可。
"""
from __future__ import annotations

from . import accounts, catalog, config, install, launch, mods, packexport, paths, remote, versions

__all__ = [
    "paths",
    "config",
    "accounts",
    "versions",
    "mods",
    "remote",
    "install",
    "launch",
    "packexport",
    "catalog",
]
