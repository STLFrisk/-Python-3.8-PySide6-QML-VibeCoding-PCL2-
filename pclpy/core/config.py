"""启动器配置读写: 深合并默认值、点号路径取值/赋值、便捷访问器。

配置为纯 JSON, 所有读写都包了异常处理, 损坏或不可写时优雅降级。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .paths import app_home

DEFAULTS = {
    "accounts": [],
    "selected_account": "",
    "folders": [],
    "selected_folder": "",
    "selected_version": "",
    "favorites": [],
    "window_size": {"w": 1000, "h": 640},
    "use_demo_data": True,
    "launch": {
        "isolation": "follow",
        "java_path": "auto",
        "memory_mode": "auto",
        "memory_mb": 4096,
        "min_memory_mb": 512,
        "jvm_args": "",
        "game_args": "",
        "window_title": "",
        "custom_info": "PCL",
        "launcher_visibility": "keep",
        "process_priority": "normal",
        "window_size_mode": "default",
        "optimize_memory": True,
        "game_language_zh": True,
    },
    "download": {
        "source": "official",
        "list_source": "official",
        "max_threads": 32,
        "speed_limit_kb": 0,
        "verify_ssl": True,
        "keep_launcher_files": False,
        # 下载/分片调参(设置 → 其他 → 调试选项 → 下载分片调参)。
        # !! 下面 5 个数字必须与 pclpy/core/remote.py 顶部的代码默认值严格一致
        #    (MULTI_MAX_SEGMENTS / MULTI_START_SEGMENTS / MULTI_MAX_CONNECTIONS /
        #     MULTI_MIN_SIZE / MULTI_LOW_SPEED_BPS), 改一边就要改另一边。
        # 生效顺序: 环境变量 > 这里的设置项 > remote.py 里的代码默认值。
        "segments_enabled": True,
        "segments_max": 8,
        "segments_start": 4,
        "connections": 32,
        "min_size_mb": 1,
        "slow_kbps": 1024,
        "debug_log": False,
    },
    "ui": {
        "animation_speed": 1.0,
        "debug_mode": False,
        "add_delay": False,
        "anonymous_stats": True,
        "theme_color": "",
        "show_task_button": True,
    },
    "launcher": {"update_mode": "auto", "announce": "all", "cache_dir": ""},
    "update": {"release": True, "snapshot": False},
    "skin": {"model": "steve", "path": ""},
}

# 当前生效的配置对象(单例)。
#
# 下载层(pclpy/core/remote.py)在**每次下载开始前**要读一次设置项才能做到
# "改完设置下一次下载就生效", 而它拿不到任何界面对象 —— 所以由组装层显式登记
# 一次: ``pclpy/app.py`` 建好主配置后调用 :func:`set_current`。
# 这里刻意**不做**任何自动注册(不在 Config.__init__ 里偷偷设), 因为版本设置页
# 会为每个版本各建一个 Config, 自动注册会让"最后建的那个"顶掉主配置。
_current = None


def set_current(cfg) -> None:
    """登记"主配置"(供下载层读取设置项); 传 None 清除。"""
    global _current
    _current = cfg


def current():
    """取已登记的主配置; 没有(纯库调用/单元测试)时返回 None。"""
    return _current


def _clone(obj):
    """JSON 安全结构的深拷贝(只用标准库 json)。"""
    try:
        return json.loads(json.dumps(obj))
    except Exception:
        if isinstance(obj, dict):
            return dict(obj)
        if isinstance(obj, list):
            return list(obj)
        return obj


def _deep_merge(base: dict, override: Any) -> dict:
    """把 override 深合并进 base(返回新字典, base 不被修改)。"""
    out = _clone(base)
    if not isinstance(out, dict):
        out = {}
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = _clone(value)
    return out


class _StrValue(str):
    """既是字符串又可调用的值。

    兼容 `cfg.selected_version` 与 `cfg.selected_version()` 两种写法。
    """

    def __call__(self):
        return str(self)


class _ListValue(list):
    """既是列表又可调用的值, 兼容属性式与方法式两种写法。"""

    def __call__(self):
        return self


class Config:
    """启动器配置对象。"""

    def __init__(self, path: Optional[str] = None):
        if path:
            self.path = str(path)
        else:
            self.path = os.path.join(str(app_home()), "config.json")
        self._data = _clone(DEFAULTS)  # type: Dict[str, Any]
        self.load()

    # ------------------------------------------------------------ 读写
    def load(self) -> None:
        """读取配置文件并与 DEFAULTS 深合并; 解析失败则使用默认值。"""
        raw = None  # type: Any
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = None
        self._data = _deep_merge(DEFAULTS, raw if isinstance(raw, dict) else {})

    def save(self, force: bool = False) -> bool:
        """写盘(缩进 2、ensure_ascii=False), 成功返回 True。

        设置过 ``defer`` 回调时(界面层用来做防抖, 拖动滑块不会每次都写盘)
        改由回调安排稍后写入; ``force=True`` 时立即写。
        """
        defer = getattr(self, "defer", None)
        if defer is not None and not force:
            try:
                defer()
                return True
            except Exception:
                pass
        try:
            folder = os.path.dirname(os.path.abspath(self.path))
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 通用访问
    def get(self, key: str, default=None):
        """按点号路径取值, 例如 "launch.java_path"。"""
        if not key:
            return self._data
        cur = self._data  # type: Any
        try:
            for part in str(key).split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return default
        except Exception:
            return default
        return default if cur is None else cur

    def set(self, key: str, value, autosave: bool = True) -> None:
        """按点号路径赋值, 中间层级不存在时自动创建 dict。"""
        if not key:
            return
        try:
            parts = str(key).split(".")
            cur = self._data
            for part in parts[:-1]:
                nxt = cur.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[part] = nxt
                cur = nxt
            cur[parts[-1]] = value
        except Exception:
            return
        if autosave:
            self.save()

    def as_dict(self) -> dict:
        """返回配置的深拷贝。"""
        return _clone(self._data)

    # ------------------------------------------------------------ 便捷访问器
    @property
    def folders(self):
        """游戏文件夹列表 [{"name":..., "path":...}, ...]。"""
        items = self.get("folders", [])
        if not isinstance(items, list):
            items = []
        return _ListValue(items)

    def add_folder(self, name: str, path: str, autosave: bool = True) -> bool:
        """新增/更新游戏文件夹(按 path 去重)。"""
        path = str(path or "")
        if not path:
            return False
        items = [f for f in self.folders if isinstance(f, dict)]
        found = None  # type: Optional[dict]
        for item in items:
            if str(item.get("path") or "") == path:
                found = item
                break
        if found is not None:
            found["name"] = str(name or "")
        else:
            items.append({"name": str(name or ""), "path": path})
        self.set("folders", items, autosave=False)
        if not str(self.get("selected_folder") or ""):
            self.set("selected_folder", path, autosave=False)
        if autosave:
            self.save()
        return True

    @property
    def selected_folder(self):
        """当前选中的游戏文件夹路径。"""
        return _StrValue(str(self.get("selected_folder") or ""))

    @property
    def selected_version(self):
        """当前选中的版本 id。"""
        return _StrValue(str(self.get("selected_version") or ""))

    def is_favorite(self, vid: str) -> bool:
        """该版本是否被收藏。"""
        favs = self.get("favorites", [])
        if not isinstance(favs, list):
            return False
        return str(vid) in [str(x) for x in favs]

    def toggle_favorite(self, vid: str) -> bool:
        """切换收藏状态, 返回切换后的状态(True 表示已收藏)。"""
        favs = self.get("favorites", [])
        favs = [str(x) for x in favs] if isinstance(favs, list) else []
        target = str(vid)
        if target in favs:
            favs = [x for x in favs if x != target]
            now = False
        else:
            favs.append(target)
            now = True
        self.set("favorites", favs)
        return now

    @property
    def accounts(self):
        """账号字典列表。"""
        items = self.get("accounts", [])
        if not isinstance(items, list):
            items = []
        return _ListValue([x for x in items if isinstance(x, dict)])

    def add_account(self, account_dict) -> bool:
        """新增账号(同名覆盖)。"""
        if not isinstance(account_dict, dict):
            return False
        name = str(account_dict.get("name") or "")
        items = [dict(x) for x in self.accounts]
        found = False
        for idx, item in enumerate(items):
            if str(item.get("name") or "") == name:
                items[idx] = dict(account_dict)
                found = True
                break
        if not found:
            items.append(dict(account_dict))
        self.set("accounts", items, autosave=False)
        if not str(self.get("selected_account") or "") and name:
            self.set("selected_account", name, autosave=False)
        self.save()
        return True

    @property
    def selected_account(self):
        """当前选中的账号名。"""
        return _StrValue(str(self.get("selected_account") or ""))
