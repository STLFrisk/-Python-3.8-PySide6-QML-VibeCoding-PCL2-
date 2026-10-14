"""版本信息模型: 本地扫描、内置目录转换、分组排序与 id 解析。

版本 id 形如 "1.8.9-Forge_11.15.1.2318" / "1.21.1-NeoForge_21.1.233" / "1.20.1"。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from . import catalog as catalog_mod
from . import paths

# kind -> 中文名
KIND_TEXT = {
    "release": "正式版",
    "snapshot": "预览版",
    "old_beta": "远古版",
    "old_alpha": "远古版",
    "april": "愚人节版",
}

# loader 关键字 -> 规范写法
_LOADER_CANON = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "optifine": "OptiFine",
}

# loader -> 立方体图标
_LOADER_ICON = {
    "NeoForge": "cube_orange",
    "Forge": "cube_gray",
    "Fabric": "cube_sand",
}

_CATEGORIES = ("modded", "normal", "uncommon")


@dataclass
class VersionInfo:
    """一个可显示/可启动的版本条目。"""

    id: str
    name: str
    mc_version: str = ""
    loader: str = ""
    loader_version: str = ""
    path: str = ""
    installed: bool = False
    kind: str = "release"
    category: str = "normal"
    release_time: str = ""
    favorite: bool = False
    description: str = ""
    source: str = "local"
    size_bytes: int = 0
    icon: str = "cube_grass"
    note: str = ""

    def subtitle(self) -> str:
        """副标题: 有加载器时 "正式版 1.8.9, Forge 11.15.1.2318"。"""
        kind_text = KIND_TEXT.get(str(self.kind or "release"), "正式版")
        mc = str(self.mc_version or self.id or "")
        loader = str(self.loader or "")
        if loader:
            ver = str(self.loader_version or "")
            if ver:
                return "%s %s, %s %s" % (kind_text, mc, loader, ver)
            return "%s %s, %s" % (kind_text, mc, loader)
        return "%s %s" % (kind_text, mc)

    def to_dict(self) -> dict:
        """转字典(用于列表模型/序列化)。"""
        try:
            return asdict(self)
        except Exception:
            return {
                "id": self.id, "name": self.name, "mc_version": self.mc_version,
                "loader": self.loader, "loader_version": self.loader_version,
                "path": self.path, "installed": self.installed, "kind": self.kind,
                "category": self.category, "release_time": self.release_time,
                "favorite": self.favorite, "description": self.description,
                "source": self.source, "size_bytes": self.size_bytes,
                "icon": self.icon, "note": self.note,
            }

    def matches(self, text: str) -> bool:
        """忽略大小写匹配 id/name/mc_version/loader。"""
        needle = str(text or "").strip().lower()
        if not needle:
            return True
        haystack = " ".join([
            str(self.id or ""), str(self.name or ""),
            str(self.mc_version or ""), str(self.loader or ""),
        ]).lower()
        return needle in haystack

    def icon_name(self) -> str:
        """图标名: 显式指定优先, 否则按加载器推断。"""
        icon = str(self.icon or "")
        if icon and icon != "cube_grass":
            return icon
        loader = str(self.loader or "")
        for key, value in _LOADER_ICON.items():
            if key.lower() == loader.lower():
                return value
        return icon or "cube_grass"


def parse_version_id(vid: str) -> dict:
    """解析版本 id, 返回 {"mc_version","loader","loader_version"}。"""
    out = {"mc_version": "", "loader": "", "loader_version": ""}  # type: Dict[str, str]
    text = str(vid or "").strip()
    if not text:
        return out
    head = text
    match = re.search(r"(?:^|[-_ ])(fabric|neoforge|forge|optifine)[-_ ]*([^\s]*)$", text, re.I)
    if match:
        key = match.group(1).lower()
        out["loader"] = _LOADER_CANON.get(key, match.group(1))
        out["loader_version"] = match.group(2) or ""
        head = text[:match.start()].strip(" -_")
    ver_match = re.match(r"^\d+(?:\.\d+)*", head)
    if ver_match:
        out["mc_version"] = ver_match.group(0)
    else:
        out["mc_version"] = head or text
    return out


def version_key(mc_version: str) -> tuple:
    """把 "1.21.4" 变成可比较元组 (1, 21, 4), 非数字部分忽略。"""
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(mc_version or "")))
    except Exception:
        return ()


def dir_size(path: str) -> int:
    """递归求目录总大小, 异常忽略。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(str(path)):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except Exception:
                    continue
    except Exception:
        return total
    return total


def read_version_json(version_dir: str) -> dict:
    """读取版本目录内的 json(优先 <目录名>.json, 否则第一个 .json); 失败返回 {}。"""
    try:
        folder = str(version_dir)
        if not os.path.isdir(folder):
            return {}
        base = os.path.basename(os.path.normpath(folder))
        candidates = [os.path.join(folder, base + ".json")]
        try:
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".json"):
                    full = os.path.join(folder, name)
                    if full not in candidates:
                        candidates.append(full)
        except Exception:
            pass
        for full in candidates:
            try:
                if not os.path.isfile(full):
                    continue
                with open(full, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
            except Exception:
                continue
    except Exception:
        return {}
    return {}


def _version_from_json(folder_name: str, version_dir: str, data: dict, root: str) -> VersionInfo:
    """由版本 json 构造 VersionInfo(调用方保证 data 非空)。"""
    vid = str(data.get("id") or folder_name)
    parsed = parse_version_id(vid)
    inherits = str(data.get("inheritsFrom") or "")
    kind = str(data.get("type") or "release")
    mc_version = parsed.get("mc_version") or vid
    if inherits:
        mc_version = inherits
        parent = read_version_json(os.path.join(str(root), "versions", inherits))
        parent_type = str(parent.get("type") or "") if isinstance(parent, dict) else ""
        if parent_type:
            kind = parent_type
    description = str(data.get("pclpy:description") or data.get("description") or "")
    release_time = str(data.get("releaseTime") or data.get("time") or "")
    return VersionInfo(
        id=vid,
        name=vid,
        mc_version=mc_version,
        loader=str(parsed.get("loader") or ""),
        loader_version=str(parsed.get("loader_version") or ""),
        path=os.path.abspath(version_dir),
        installed=True,
        kind=kind,
        release_time=release_time,
        description=description,
        source="local",
        size_bytes=dir_size(version_dir),
    )


def version_category(loader: str, kind: str) -> str:
    """分类: 带加载器 → modded; 快照/远古 → uncommon; 其它 → normal。"""
    if str(loader or "").strip():
        return "modded"
    if str(kind or "").lower() in ("snapshot", "old_beta", "old_alpha", "alpha", "beta",
                                   "april_fools", "experiment"):
        return "uncommon"
    return "normal"


def _looks_installed(versions_root: str, version_id: str) -> bool:
    """带占位标记的版本是不是"其实已经装好了"(占位只是残留)。

    两个条件都要满足, 免得把真正的半成品当成正常版本:
      * 有可解析的 json 且有 mainClass
      * 有本版本的 ``<id>.jar``, 或者它继承的版本有 jar
    """
    folder = os.path.join(str(versions_root), version_id)
    data = read_version_json(folder)
    if not data or not str(data.get("mainClass") or ""):
        return False
    if os.path.isfile(os.path.join(folder, version_id + ".jar")):
        return True
    parent = str(data.get("inheritsFrom") or "")
    if not parent:
        return False
    parent_dir = os.path.join(str(versions_root), parent)
    return os.path.isfile(os.path.join(parent_dir, parent + ".jar"))


def scan_folder(root: str) -> List[VersionInfo]:
    """扫描 <root>/versions/*/, 返回本地已安装版本列表(损坏的条目跳过)。"""
    result = []  # type: List[VersionInfo]
    if not root:
        return result
    versions_root = os.path.join(str(root), "versions")
    try:
        names = sorted(os.listdir(versions_root))
    except Exception:
        return result
    for name in names:
        version_dir = os.path.join(versions_root, name)
        try:
            if not os.path.isdir(version_dir):
                continue
            # 未安装完的版本带占位文件, 不列出来(学 PCL2 的 .pclignore)。
            # 但占位可能是"残留": 安装其实早就成功了(有完整 json + 能用的客户端 jar),
            # 那种情况要把占位删掉并正常列出 —— 否则版本会凭空消失(踩过这个坑)。
            mark = os.path.join(version_dir, ".pclpy_installing")
            if os.path.isfile(mark):
                try:
                    if _looks_installed(versions_root, name):
                        os.remove(mark)
                    else:
                        continue
                except Exception:  # noqa: BLE001
                    continue
            data = read_version_json(version_dir)
            if not data:
                continue  # 缺少或损坏的 json: 视为无效版本
            info = _version_from_json(name, version_dir, data, str(root))
            # 分类要按加载器/版本类型来分, 否则 Fabric/Forge 版本会全挤进「常规版本」
            info.category = version_category(info.loader, info.kind)
            result.append(info)
        except Exception:
            continue
    return result


def catalog_installable() -> List[VersionInfo]:
    """由内置 catalog 生成可安装版本列表。"""
    result = []  # type: List[VersionInfo]
    for entry in catalog_mod.installable():
        if not isinstance(entry, dict):
            continue
        try:
            name = str(entry.get("name") or entry.get("id") or "")
            vid = str(entry.get("id") or name.replace(" ", "_"))
            mc_version = str(entry.get("mc_version") or "")
            loader = str(entry.get("loader") or "")
            loader_version = str(entry.get("loader_version") or "")
            if not mc_version or not loader:
                parsed = parse_version_id(vid)
                mc_version = mc_version or str(parsed.get("mc_version") or "")
                loader = loader or str(parsed.get("loader") or "")
                loader_version = loader_version or str(parsed.get("loader_version") or "")
            result.append(VersionInfo(
                id=vid,
                name=name or vid,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                installed=False,
                kind=str(entry.get("kind") or "release"),
                category=str(entry.get("category") or "modded"),
                release_time=str(entry.get("release_time") or ""),
                description=str(entry.get("description") or ""),
                source="catalog",
                size_bytes=int(entry.get("size_bytes") or 0),
                icon=str(entry.get("icon") or "cube_grass"),
                note=str(entry.get("note") or ""),
            ))
        except Exception:
            continue
    return result


def _demo_item(entry_id: str, entry: Optional[dict] = None) -> VersionInfo:
    """由示例 id 构造 VersionInfo。"""
    entry = entry if isinstance(entry, dict) else {}
    parsed = parse_version_id(entry_id)
    return VersionInfo(
        id=entry_id,
        name=str(entry.get("name") or entry_id),
        mc_version=str(parsed.get("mc_version") or entry_id),
        loader=str(parsed.get("loader") or ""),
        loader_version=str(parsed.get("loader_version") or ""),
        path="",
        installed=True,
        kind=str(entry.get("kind") or "release"),
        category=str(entry.get("category") or "normal"),
        description=str(entry.get("description") or ""),
        source="local",
        icon=str(entry.get("icon") or "cube_grass"),
        note=str(entry.get("note") or ""),
    )


def demo_installed(extra_ids: Optional[List[str]] = None) -> List[VersionInfo]:
    """由内置 catalog 生成示例已安装版本列表(path 为空表示示例数据)。"""
    result = []  # type: List[VersionInfo]
    seen = set()
    for entry in catalog_mod.demo_installed():
        if not isinstance(entry, dict):
            continue
        vid = str(entry.get("id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        result.append(_demo_item(vid, entry))
    for vid in (extra_ids or []):
        text = str(vid or "")
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(_demo_item(text, None))
    return result


def group_versions(items) -> dict:
    """按 category 分桶: modded 保持原顺序, normal/uncommon 按版本号从新到旧。"""
    buckets = {"modded": [], "normal": [], "uncommon": []}  # type: Dict[str, List[Any]]
    for item in (items or []):
        category = str(getattr(item, "category", "normal") or "normal").lower()
        if category not in buckets:
            category = "normal"
        buckets[category].append(item)
    for key in ("normal", "uncommon"):
        try:
            buckets[key].sort(
                key=lambda x: version_key(str(getattr(x, "mc_version", "") or "")),
                reverse=True,
            )
        except Exception:
            pass
    return buckets


def _folder_path(folder) -> str:
    """从文件夹配置(dict 或 str)中取出路径。"""
    if isinstance(folder, dict):
        return str(folder.get("path") or "")
    return str(folder or "")


def select_version(items, vid: str) -> Optional[VersionInfo]:
    """按 id 精确查找(退化为忽略大小写)。"""
    target = str(vid or "")
    if not target:
        return None
    for item in (items or []):
        if str(getattr(item, "id", "")) == target:
            return item
    low = target.lower()
    for item in (items or []):
        if str(getattr(item, "id", "")).lower() == low:
            return item
    return None
