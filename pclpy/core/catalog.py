"""内置资源目录(catalog.json)读取与缓存。

catalog.json 提供三类数据: 可安装版本列表、示例已安装版本、原版回退版本列表。
文件缺失或损坏时返回空结构, 绝不抛异常。
"""
from __future__ import annotations

import json
from typing import Any, List

from .paths import bundled_data_path

# 缓存(进程内只读取一次)
_CACHE = None  # type: Any

_EMPTY = {
    "installable": [],
    "demo_installed": [],
    "vanilla_fallback": {"latest": {"release": "", "snapshot": ""}, "versions": []},
}


def _empty() -> dict:
    """返回一份空的目录结构(深拷贝, 避免被调用方修改)。"""
    try:
        return json.loads(json.dumps(_EMPTY))
    except Exception:
        return {"installable": [], "demo_installed": [],
                "vanilla_fallback": {"latest": {"release": "", "snapshot": ""}, "versions": []}}


def catalog() -> dict:
    """读取并缓存内置 catalog.json; 缺失/损坏时返回空结构。"""
    global _CACHE
    if isinstance(_CACHE, dict):
        return _CACHE
    data = None  # type: Any
    try:
        with open(bundled_data_path("catalog.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = None
    if not isinstance(data, dict):
        data = _empty()
    # 补齐缺失的键, 保证上层取值安全
    result = _empty()
    for key in ("installable", "demo_installed"):
        value = data.get(key)
        if isinstance(value, list):
            result[key] = value
    fallback = data.get("vanilla_fallback")
    if isinstance(fallback, dict):
        latest = fallback.get("latest")
        versions = fallback.get("versions")
        result["vanilla_fallback"] = {
            "latest": latest if isinstance(latest, dict) else {"release": "", "snapshot": ""},
            "versions": versions if isinstance(versions, list) else [],
        }
    _CACHE = result
    return _CACHE


def installable() -> List[dict]:
    """可安装(下载)版本列表。"""
    items = catalog().get("installable")
    return list(items) if isinstance(items, list) else []


def demo_installed() -> List[dict]:
    """示例已安装版本列表(设计稿数据)。"""
    items = catalog().get("demo_installed")
    return list(items) if isinstance(items, list) else []


def vanilla_fallback() -> dict:
    """无网络时的原版版本列表回退数据。"""
    data = catalog().get("vanilla_fallback")
    if not isinstance(data, dict):
        return {"latest": {"release": "", "snapshot": ""}, "versions": []}
    return data
