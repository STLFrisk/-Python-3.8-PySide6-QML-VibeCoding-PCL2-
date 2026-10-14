"""模组目录管理: 列出模组、启用/禁用(重命名)、安装与删除。

模组以文件/文件夹形式存在, 禁用时使用 .disabled / .off 后缀。
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .paths import ensure_dir, human_size

# 需要剥离的后缀(按长度从长到短匹配)
_SUFFIXES = [".jar.disabled", ".jar.off", ".jar", ".disabled", ".off"]

# 名字与版本的分界: "分隔符 + 数字开头" 的第一次出现(按规格的正则)
_NAME_VERSION_RE = re.compile(r"[-_ ]v?(\d[\w.\-+]*)$")


@dataclass
class ModInfo:
    """一个模组文件或模组文件夹。"""

    file_name: str
    path: str
    name: str
    version: str = ""
    enabled: bool = True
    size_bytes: int = 0
    is_dir: bool = False

    def subtitle(self) -> str:
        """副标题: "文件名 · 1.2 MB"。"""
        if self.is_dir:
            return "%s · 文件夹" % self.file_name
        return "%s · %s" % (self.file_name, human_size(self.size_bytes))


def _split_suffix(file_name: str) -> Tuple[str, str]:
    """拆出 (主体名, 后缀), 后缀保持原大小写。"""
    name = str(file_name or "")
    low = name.lower()
    for suffix in _SUFFIXES:
        if low.endswith(suffix):
            return name[:-len(suffix)], name[-len(suffix):]
    return name, ""


def parse_mod_name(filename: str) -> Tuple[str, str]:
    """从文件名解析 (模组名, 版本号); 解析不出时版本为空串。"""
    stem, _suffix = _split_suffix(os.path.basename(str(filename or "")))
    if not stem:
        return str(filename or ""), ""
    match = _NAME_VERSION_RE.search(stem)
    if match and match.start() > 0:
        name = stem[:match.start()].strip("-_ ")
        if name:
            return name, match.group(1)
    return stem, ""


def _is_disabled_name(name: str) -> bool:
    low = str(name or "").lower()
    return low.endswith(".disabled") or low.endswith(".off")


def _make_mod(path: str, is_dir: bool = False) -> ModInfo:
    """由磁盘路径构造 ModInfo。"""
    file_name = os.path.basename(str(path).rstrip("\\/"))
    name, version = parse_mod_name(file_name)
    size = 0
    try:
        if is_dir:
            size = 0
        else:
            size = os.path.getsize(path)
    except Exception:
        size = 0
    return ModInfo(
        file_name=file_name,
        path=str(path),
        name=name or file_name,
        version=version,
        enabled=not _is_disabled_name(file_name),
        size_bytes=size,
        is_dir=is_dir,
    )


def list_mods(mods_dir: str) -> List[ModInfo]:
    """列出模组目录中的模组文件与子目录(目录不存在返回 [])。"""
    result = []  # type: List[ModInfo]
    folder = str(mods_dir or "")
    if not folder or not os.path.isdir(folder):
        return result
    try:
        names = os.listdir(folder)
    except Exception:
        return result
    for entry in names:
        full = os.path.join(folder, entry)
        try:
            if os.path.isdir(full):
                if entry.startswith("."):
                    continue
                result.append(_make_mod(full, is_dir=True))
                continue
            low = entry.lower()
            if not (low.endswith(".jar") or low.endswith(".disabled") or low.endswith(".off")):
                continue
            result.append(_make_mod(full, is_dir=False))
        except Exception:
            continue
    try:
        result.sort(key=lambda m: str(m.name).lower())
    except Exception:
        pass
    return result


def set_enabled(mod: ModInfo, enabled: bool) -> bool:
    """通过重命名文件实现模组启停, 成功返回 True。"""
    if mod is None:
        return False
    path = str(getattr(mod, "path", "") or "")
    if not path or not os.path.exists(path):
        return False
    currently_disabled = _is_disabled_name(os.path.basename(path))
    try:
        if enabled:
            if not currently_disabled:
                mod.enabled = True
                return True
            low = path.lower()
            for suffix in (".disabled", ".off"):
                if low.endswith(suffix):
                    new_path = path[:-len(suffix)]
                    break
            else:
                mod.enabled = True
                return True
        else:
            if currently_disabled:
                mod.enabled = False
                return True
            new_path = path + ".disabled"
        os.rename(path, new_path)
        mod.path = new_path
        mod.file_name = os.path.basename(new_path)
        mod.enabled = bool(enabled)
        return True
    except Exception:
        return False


def install_mod(src: str, mods_dir: str) -> Optional[ModInfo]:
    """把模组文件复制进模组目录(重名加 " (2)"), 返回新的 ModInfo。"""
    source = str(src or "")
    if not source or not os.path.isfile(source):
        return None
    try:
        ensure_dir(mods_dir)
        base = os.path.basename(source)
        stem, suffix = _split_suffix(base)
        dest = os.path.join(str(mods_dir), base)
        index = 2
        while os.path.exists(dest):
            dest = os.path.join(str(mods_dir), "%s (%d)%s" % (stem, index, suffix))
            index += 1
            if index > 999:
                return None
        shutil.copy2(source, dest)
        return _make_mod(dest, is_dir=False)
    except Exception:
        return None


def delete_mod(mod: ModInfo) -> bool:
    """删除模组文件或文件夹, 成功返回 True。"""
    if mod is None:
        return False
    path = str(getattr(mod, "path", "") or "")
    if not path or not os.path.exists(path):
        return False
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    except Exception:
        return False


def mods_dir_for(version_dir: str, root: str, isolated: bool) -> str:
    """返回模组目录: 隔离时 <version_dir>/mods, 否则 <root>/mods。"""
    if isolated:
        return os.path.join(str(version_dir or ""), "mods")
    return os.path.join(str(root or ""), "mods")
