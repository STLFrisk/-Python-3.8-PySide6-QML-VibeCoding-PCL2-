"""整合包导出/导入: 把游戏目录里的模组、配置、存档等打包成 zip。

导出使用 ZIP_DEFLATED, 包根目录写入 pclpy_pack.json 元数据;
导入时拒绝含 ".." 的成员, 防止目录穿越。
"""
from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from typing import List, Tuple

from .paths import adapt_progress_callback, app_home
from .versions import parse_version_id

# 支持的选项键
_OPTION_KEYS = (
    "pack_name", "pack_version", "mods", "mod_configs", "resourcepacks",
    "screenshots", "saves", "servers", "launcher_config", "game_settings",
)

_META_NAME = "pclpy_pack.json"
_LAUNCHER_CONFIG_NAME = "pclpy_launcher_config.json"


def _report(progress_cb, percent: int, text: str) -> None:
    """安全回报进度。"""
    if progress_cb is None:
        return
    try:
        progress_cb(int(percent), str(text))
    except Exception:
        pass


def _cancelled(cancel_cb) -> bool:
    """安全调用取消回调。"""
    if cancel_cb is None:
        return False
    try:
        return bool(cancel_cb())
    except Exception:
        return False


def _check_cancel(cancel_cb, out_path: str = "") -> None:
    """取消时清理半成品并抛 RuntimeError。"""
    if not _cancelled(cancel_cb):
        return
    if out_path:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
    raise RuntimeError("已取消")


def _bases(root: str, version_id: str) -> List[str]:
    """收集内容的候选根目录(版本隔离开启时优先版本目录)。"""
    bases = []  # type: List[str]
    if version_id:
        version_dir = os.path.join(str(root), "versions", str(version_id))
        if os.path.isdir(version_dir):
            bases.append(version_dir)
    bases.append(str(root))
    return bases


def _first_existing(bases: List[str], relative: str) -> str:
    """在候选根目录里找第一个存在的路径。"""
    for base in bases:
        candidate = os.path.join(base, relative.replace("/", os.sep))
        if os.path.exists(candidate):
            return candidate
    return ""


def _walk_files(path: str, relative: str) -> List[Tuple[str, str]]:
    """递归收集目录下的文件, 返回 [(绝对路径, 包内相对路径)]。"""
    result = []  # type: List[Tuple[str, str]]
    if not path or not os.path.isdir(path):
        return result
    for base, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(base, name)
            try:
                sub = os.path.relpath(full, path).replace(os.sep, "/")
            except Exception:
                continue
            result.append((full, relative.rstrip("/") + "/" + sub))
    return result


def _collect(root: str, version_id: str, options: dict) -> List[Tuple[str, str]]:
    """按选项收集 (绝对路径, 包内相对路径) 列表。"""
    bases = _bases(root, version_id)
    files = []  # type: List[Tuple[str, str]]
    seen = set()

    def _add(items):
        for full, arc in items:
            if arc in seen:
                continue
            seen.add(arc)
            files.append((full, arc))

    if options.get("mods"):
        for base in bases:
            mods_dir = os.path.join(base, "mods")
            if not os.path.isdir(mods_dir):
                continue
            for full, arc in _walk_files(mods_dir, "mods"):
                low = os.path.basename(full).lower()
                if ".jar" in low:
                    _add([(full, arc)])
            break
    if options.get("mod_configs"):
        path = _first_existing(bases, "config")
        if path:
            _add(_walk_files(path, "config"))
    for key, relative in (("resourcepacks", "resourcepacks"),
                          ("screenshots", "screenshots"),
                          ("saves", "saves")):
        if options.get(key):
            path = _first_existing(bases, relative)
            if path:
                _add(_walk_files(path, relative))
    if options.get("servers"):
        path = _first_existing(bases, "servers.dat")
        if path:
            _add([(path, "servers.dat")])
    if options.get("game_settings"):
        for name in ("options.txt", "optionsof.txt"):
            path = _first_existing(bases, name)
            if path:
                _add([(path, name)])
    if options.get("launcher_config"):
        path = os.path.join(str(app_home()), "config.json")
        if os.path.isfile(path):
            _add([(path, _LAUNCHER_CONFIG_NAME)])
    return files


def export_pack(root: str, version_id: str, out_path: str, options: dict,
                progress_cb=None, cancel_cb=None) -> str:
    """导出整合包 zip, 返回输出路径。"""
    options = options if isinstance(options, dict) else {}
    root = str(root)
    out = str(out_path)
    progress_cb = adapt_progress_callback(progress_cb)
    _check_cancel(cancel_cb)
    files = _collect(root, str(version_id or ""), options)
    parsed = parse_version_id(str(version_id or ""))
    meta = {
        "name": str(options.get("pack_name") or "未命名整合包"),
        "version": str(options.get("pack_version") or "1.0"),
        "mc_version": str(parsed.get("mc_version") or ""),
        "loader": str(parsed.get("loader") or ""),
        "loader_version": str(parsed.get("loader_version") or ""),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "files": len(files),
        "options": {key: bool(options.get(key)) for key in _OPTION_KEYS},
    }
    total = len(files) + 1
    done = 0
    cancelled = False
    try:
        folder = os.path.dirname(os.path.abspath(out))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_META_NAME, json.dumps(meta, indent=2, ensure_ascii=False))
            done += 1
            _report(progress_cb, int(100.0 * done / total), "正在打包: %s" % _META_NAME)
            for full, arc in files:
                # 注意: 压缩包还开着, Windows 上不能删除打开中的文件,
                # 所以这里只记录取消状态, 关闭后再清理半成品。
                if _cancelled(cancel_cb):
                    cancelled = True
                    break
                try:
                    zf.write(full, arc)
                except Exception:
                    done += 1
                    continue
                done += 1
                _report(progress_cb, int(100.0 * done / total), "正在打包: %s" % arc)
    except Exception as exc:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass
        raise RuntimeError("导出整合包失败: %s" % exc)
    if cancelled:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass
        raise RuntimeError("已取消")
    _report(progress_cb, 100, "导出完成")
    return out


def import_pack(zip_path: str, root: str, progress_cb=None, cancel_cb=None) -> str:
    """把整合包 zip 解压到 root, 返回包名。"""
    path = str(zip_path or "")
    dest_root = str(root or "")
    progress_cb = adapt_progress_callback(progress_cb)
    if not path or not os.path.isfile(path):
        raise RuntimeError("整合包文件不存在: %s" % path)
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        with zipfile.ZipFile(path, "r") as zf:
            members = []  # type: List[Tuple[zipfile.ZipInfo, str]]
            for info in zf.infolist():
                member = str(info.filename or "").replace("\\", "/")
                if not member or member.endswith("/"):
                    continue
                parts = [p for p in member.split("/") if p not in ("", ".")]
                if ".." in parts or os.path.isabs(member) or (len(member) > 1 and member[1] == ":"):
                    raise RuntimeError("整合包包含非法路径, 已拒绝导入: %s" % member)
                if member == _META_NAME:
                    try:
                        data = json.loads(zf.read(info).decode("utf-8", "replace"))
                        if isinstance(data, dict) and data.get("name"):
                            name = str(data["name"])
                    except Exception:
                        pass
                    continue
                members.append((info, member))
            total = max(1, len(members))
            for index, (info, member) in enumerate(members):
                if _cancelled(cancel_cb):
                    raise RuntimeError("已取消")
                target = os.path.join(dest_root, member.replace("/", os.sep))
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                except Exception:
                    continue
                _report(progress_cb, int(100.0 * (index + 1) / total), "正在解压: %s" % member)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("导入整合包失败: %s" % exc)
    _report(progress_cb, 100, "导入完成")
    return name
