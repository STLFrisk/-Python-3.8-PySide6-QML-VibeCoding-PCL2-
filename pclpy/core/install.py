"""安装流程: 原版版本、Fabric 版本下载安装与 natives 解压。

约定: 所有安装函数的 progress_cb(percent, text) 回报进度(percent 0-100),
cancel_cb() 返回 True 时中止; 取消或失败统一抛 RuntimeError(中文消息)。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from typing import List, Optional, Tuple

from . import remote
from .paths import adapt_progress_callback, cache_dir, ensure_dir

# 当前平台对应的 natives 分类键
_NATIVES_KEY = "windows" if os.name == "nt" else ("osx" if sys.platform == "darwin" else "linux")

# 官方库站
_LIBRARY_BASE = "https://libraries.minecraft.net/"


# ---------------------------------------------------------------- 通用工具
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


def _phase(phase_cb, phase_id: str, percent: int, text: str = "") -> None:
    """回报"当前阶段"(供任务管理页显示分步进度)。"""
    if phase_cb is None:
        return
    try:
        phase_cb(str(phase_id), int(percent), str(text))
    except Exception:
        pass


def _check_cancel(cancel_cb) -> None:
    """已取消时抛 RuntimeError。"""
    if _cancelled(cancel_cb):
        raise RuntimeError("已取消")


def _to_int(value, default: int = 0) -> int:
    """安全转 int。"""
    try:
        return int(value)
    except Exception:
        return default


def _source_of(cfg) -> str:
    """从配置读取下载源。"""
    source = "official"
    if cfg is not None:
        try:
            source = str(cfg.get("download.source") or "official")
        except Exception:
            source = "official"
    return source or "official"


def _arch_name() -> str:
    """当前 CPU 架构名(Minecraft 清单里的写法)。"""
    env = str(os.environ.get("PROCESSOR_ARCHITECTURE") or "").lower()
    if "arm64" in env or "aarch64" in env:
        return "arm64"
    if env:
        if "x86" in env and sys.maxsize <= 2 ** 32:
            return "x86"
        return "amd64"
    try:
        machine = os.uname().machine.lower()  # type: ignore[attr-defined]
    except Exception:
        machine = ""
    if "arm" in machine or "aarch" in machine:
        return "arm64" if "64" in machine else "arm"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("i386", "i686", "x86"):
        return "x86"
    return machine or "amd64"


_OS_NAME = "windows" if os.name == "nt" else ("osx" if sys.platform == "darwin" else "linux")


def _os_version() -> str:
    """当前系统版本字符串(Windows 用主.次.构建号, 其它平台返回空串)。"""
    try:
        info = sys.getwindowsversion()  # type: ignore[attr-defined]
        return "%d.%d.%d" % (info.major, info.minor, info.build)
    except Exception:
        return ""


def _rule_matches(rule: dict, features: Optional[dict]) -> bool:
    """单条 rule 是否满足。"""
    if not isinstance(rule, dict):
        return False
    os_rule = rule.get("os")
    if isinstance(os_rule, dict):
        name = os_rule.get("name")
        if name and str(name).lower() != _OS_NAME:
            return False
        arch = os_rule.get("arch")
        if arch and str(arch).lower() != _arch_name():
            return False
        version = os_rule.get("version")
        if version:
            try:
                if not re.search(str(version), _os_version()):
                    return False
            except Exception:
                return False
    feat_rule = rule.get("features")
    if isinstance(feat_rule, dict):
        for key, value in feat_rule.items():
            if bool((features or {}).get(key, False)) != bool(value):
                return False
    return True


def rule_allows(rules: Optional[list], features: Optional[dict] = None) -> bool:
    """Minecraft 库/参数 rules 求值(最后一条命中的规则决定结果)。"""
    if not rules:
        return True
    if not isinstance(rules, list):
        return True
    allowed = False
    for rule in rules:
        if _rule_matches(rule, features):
            allowed = str(rule.get("action") or "allow").lower() == "allow"
    return allowed


def library_allowed(lib: dict) -> bool:
    """库是否适用于当前平台。"""
    if not isinstance(lib, dict):
        return False
    return rule_allows(lib.get("rules"))


def library_path(lib: dict) -> Optional[str]:
    """库在 libraries/ 下的相对路径(正斜杠)。"""
    if not isinstance(lib, dict):
        return None
    downloads = lib.get("downloads")
    if isinstance(downloads, dict):
        artifact = downloads.get("artifact")
        if isinstance(artifact, dict) and artifact.get("path"):
            return str(artifact["path"])
    name = lib.get("name")
    if not name:
        return None
    parts = str(name).split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 and parts[3] else ""
    file_name = "%s-%s%s.jar" % (artifact, version, ("-" + classifier) if classifier else "")
    return "/".join([group.replace(".", "/"), artifact, version, file_name])


def is_installed(root: str, version_id: str) -> bool:
    """版本是否已安装(json 存在且客户端 jar 或 inheritsFrom 存在)。"""
    try:
        version_dir = os.path.join(str(root), "versions", str(version_id))
        json_path = os.path.join(version_dir, str(version_id) + ".json")
        if not os.path.isfile(json_path):
            return False
        if os.path.isfile(os.path.join(version_dir, str(version_id) + ".jar")):
            return True
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(isinstance(data, dict) and data.get("inheritsFrom"))
    except Exception:
        return False


def _artifact_url(lib: dict) -> Tuple[str, int]:
    """库的下载地址与期望大小。"""
    if not isinstance(lib, dict):
        return "", 0
    downloads = lib.get("downloads")
    if isinstance(downloads, dict):
        artifact = downloads.get("artifact")
        if isinstance(artifact, dict) and artifact.get("url"):
            return str(artifact["url"]), _to_int(artifact.get("size"), 0)
    path = library_path(lib)
    if path:
        return _LIBRARY_BASE + path, 0
    return "", 0


def _file_matches(path: str, size: int) -> bool:
    """文件存在且(不校验大小或大小一致)。"""
    try:
        if not os.path.isfile(path):
            return False
        if size and os.path.getsize(path) != size:
            return False
        return True
    except Exception:
        return False


def _download(url: str, dest: str, source: str, cancel_cb, expect_size: int = 0,
              progress_cb=None, base: int = 0, span: int = 0, text: str = "",
              bytes_cb=None) -> None:
    """下载单个文件, 失败/取消抛 RuntimeError。"""
    _check_cancel(cancel_cb)
    if expect_size and _file_matches(dest, expect_size):
        if bytes_cb is not None:
            try:
                bytes_cb(int(expect_size))
            except Exception:
                pass
        return
    if not url:
        raise RuntimeError("缺少下载地址: %s" % os.path.basename(str(dest)))
    progress_cb = adapt_progress_callback(progress_cb)
    counter = {"last": 0}

    def _cb(done, total):
        if bytes_cb is not None:
            delta = int(done) - counter["last"]
            if delta > 0:
                counter["last"] = int(done)
                try:
                    bytes_cb(delta)
                except Exception:
                    pass
        if progress_cb is None or span <= 0:
            return
        try:
            ratio = (float(done) / float(total)) if total else 0.0
            pct = base + int(span * min(1.0, max(0.0, ratio)))
            msg = text or ("下载 %s" % os.path.basename(str(dest)))
            progress_cb(int(pct), "%s %d%%" % (msg, int(min(100.0, ratio * 100.0))))
        except Exception:
            pass

    ok = remote.download_file(url, dest, source=source, progress_cb=_cb, cancel_cb=cancel_cb)
    if not ok:
        if _cancelled(cancel_cb):
            raise RuntimeError("已取消")
        raise RuntimeError("下载失败: %s" % url)


def _write_json(path: str, data: dict) -> None:
    """写 JSON 文件(先写临时文件再改名), 失败抛 RuntimeError。"""
    try:
        folder = os.path.dirname(os.path.abspath(path))
        ensure_dir(folder)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        raise RuntimeError("写入文件失败: %s (%s)" % (path, exc))


def _read_json(path: str) -> dict:
    """读 JSON 文件, 失败返回 {}。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _thread_count(cfg) -> int:
    """资源文件下载并发数(最多 8 个, 受 download.max_threads 限制)。"""
    limit = 8
    if cfg is not None:
        try:
            value = _to_int(cfg.get("download.max_threads"), 32)
            if value > 0:
                limit = min(8, value)
        except Exception:
            limit = 8
    return max(1, limit)


def _native_classifier_key(lib: dict) -> str:
    """库的 natives 分类键(含 ${arch} 替换)。"""
    natives = lib.get("natives")
    if not isinstance(natives, dict):
        return ""
    key = str(natives.get(_NATIVES_KEY) or "")
    if not key:
        return ""
    arch = "64" if sys.maxsize > 2 ** 32 else "32"
    return key.replace("${arch}", arch)


def _native_jar_path(lib: dict, key: str) -> str:
    """natives jar 在 libraries/ 下的相对路径。"""
    downloads = lib.get("downloads")
    if isinstance(downloads, dict):
        classifiers = downloads.get("classifiers")
        if isinstance(classifiers, dict):
            for candidate in (key, key.replace("-", "_"), key.replace("_", "-")):
                artifact = classifiers.get(candidate)
                if isinstance(artifact, dict) and artifact.get("path"):
                    return str(artifact["path"])
    name = lib.get("name")
    if name and key:
        parts = str(name).split(":")
        if len(parts) >= 3:
            return library_path({"name": ":".join(parts[:3]) + ":" + key}) or ""
    return ""


def extract_natives(jar_path: str, dest_dir: str, excludes: Optional[list] = None) -> int:
    """解压 natives jar(跳过 META-INF 与目录项), 返回解压文件数。"""
    count = 0
    try:
        if not jar_path or not os.path.isfile(jar_path):
            return 0
        ensure_dir(dest_dir)
        rules = ["META-INF/", "META-INF"]
        for item in (excludes or []):
            text = str(item or "")
            if text:
                rules.append(text)
        base = os.path.abspath(dest_dir)
        with zipfile.ZipFile(jar_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                if not name or name.endswith("/"):
                    continue
                if any(name == rule.rstrip("/") or name.startswith(rule) for rule in rules):
                    continue
                target = os.path.abspath(os.path.join(dest_dir, name.replace("/", os.sep)))
                if not target.startswith(base):
                    continue  # 防目录穿越
                try:
                    ensure_dir(os.path.dirname(target))
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
                except Exception:
                    continue
    except Exception:
        return count
    return count


# ---------------------------------------------------------------- 原版安装
def _find_manifest_entry(manifest: dict, version_id: str) -> Optional[dict]:
    """在清单里按 id 找版本条目。"""
    versions = manifest.get("versions") if isinstance(manifest, dict) else None
    for item in (versions or []):
        if isinstance(item, dict) and str(item.get("id") or "") == str(version_id):
            return item
    return None


def _download_objects(root: str, source: str, objects: dict, cfg, progress_cb, cancel_cb,
                      base_pct: int, span_pct: int, bytes_cb=None) -> None:
    """并发下载 asset objects(assets/objects/<前2位>/<hash>)。"""
    items = []  # type: List[Tuple[str, int]]
    for _name, obj in (objects or {}).items():
        if isinstance(obj, dict) and obj.get("hash"):
            items.append((str(obj["hash"]), _to_int(obj.get("size"), 0)))
    total = len(items)
    if total == 0:
        return
    progress_cb = adapt_progress_callback(progress_cb)
    threads_n = _thread_count(cfg)
    done = {"n": 0}
    failed = {"n": 0}
    lock = threading.Lock()
    stop = threading.Event()
    assets_base = remote.endpoint("assets", source).rstrip("/")

    def worker(chunk):
        last = {"n": 0}

        def file_progress(done, total):
            if bytes_cb is None:
                return
            delta = int(done) - last["n"]
            if delta > 0:
                last["n"] = int(done)
                try:
                    bytes_cb(delta)
                except Exception:
                    pass

        for hash_value, size in chunk:
            if stop.is_set():
                return
            if _cancelled(cancel_cb):
                stop.set()
                return
            sub = hash_value[:2]
            dest = os.path.join(root, "assets", "objects", sub, hash_value)
            ok = False
            try:
                if _file_matches(dest, size):
                    ok = True
                    if bytes_cb is not None and size:
                        try:
                            bytes_cb(int(size))
                        except Exception:
                            pass
                else:
                    last["n"] = 0
                    url = "%s/%s/%s" % (assets_base, sub, hash_value)
                    ok = remote.download_file(url, dest, source="official",
                                              cancel_cb=cancel_cb,
                                              progress_cb=file_progress)
            except Exception:
                ok = False
            with lock:
                done["n"] += 1
                if not ok:
                    failed["n"] += 1
                pct = base_pct + int(span_pct * done["n"] / float(total))
                _report(progress_cb, pct, "资源文件 %d/%d" % (done["n"], total))

    chunks = [items[i::threads_n] for i in range(threads_n)]
    threads = []
    for chunk in chunks:
        if not chunk:
            continue
        thread = threading.Thread(target=worker, args=(chunk,), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    if stop.is_set() or _cancelled(cancel_cb):
        raise RuntimeError("已取消")
    if failed["n"]:
        raise RuntimeError("资源文件下载失败 %d 个" % failed["n"])


def install_vanilla(mc_version: str, root: str, cfg=None, progress_cb=None, cancel_cb=None,
                    phase_cb=None, bytes_cb=None) -> str:
    """安装(或补全)一个原版版本, 返回版本 id。"""
    version_id = str(mc_version or "").strip()
    if not version_id:
        raise RuntimeError("版本号为空")
    root = str(root)
    # ⑥-2: 先写"安装中"占位 —— 中途失败时扫描器不会把它当正常版本列出来,
    # 之后由 cleanup_unfinished() 清理(仅当没有用户数据)。
    mark_installing(root, version_id)
    source = _source_of(cfg)
    progress_cb = adapt_progress_callback(progress_cb)
    _report(progress_cb, 0, "获取版本列表...")
    _phase(phase_cb, "prepare", 0, "获取版本列表")
    manifest = remote.get_manifest(cfg)
    entry = _find_manifest_entry(manifest, version_id)
    if entry is None:
        raise RuntimeError("版本列表中未找到 %s" % version_id)
    entry_url = str(entry.get("url") or "")
    if not entry_url:
        raise RuntimeError("版本 %s 缺少下载地址(可能来自离线回退列表)" % version_id)
    _check_cancel(cancel_cb)

    version_dir = os.path.join(root, "versions", version_id)
    ensure_dir(version_dir)
    json_path = os.path.join(version_dir, version_id + ".json")

    # 1) 版本 json
    _report(progress_cb, 2, "下载版本信息...")
    _phase(phase_cb, "json", 0, "下载原版 json 文件")
    version_json = remote.fetch_version_json(entry_url, source)
    if not isinstance(version_json, dict) or not version_json:
        raise RuntimeError("下载版本 JSON 失败: %s" % version_id)
    version_json.setdefault("id", version_id)
    _write_json(json_path, version_json)
    _phase(phase_cb, "json", 100, "下载原版 json 文件")

    # 2) 客户端 jar
    _report(progress_cb, 5, "下载客户端...")
    _phase(phase_cb, "client", 0, "下载客户端 jar")
    downloads = version_json.get("downloads") if isinstance(version_json.get("downloads"), dict) else {}
    client = downloads.get("client") if isinstance(downloads, dict) else None
    jar_path = os.path.join(version_dir, version_id + ".jar")
    if isinstance(client, dict) and client.get("url"):
        _download(str(client["url"]), jar_path, source, cancel_cb,
                  expect_size=_to_int(client.get("size"), 0),
                  progress_cb=progress_cb, base=5, span=20, text="下载客户端",
                  bytes_cb=bytes_cb)
    _phase(phase_cb, "client", 100, "下载客户端 jar")
    _check_cancel(cancel_cb)

    # 3) 依赖库
    libraries = version_json.get("libraries") or []
    libraries = libraries if isinstance(libraries, list) else []
    total_libs = len(libraries)
    _report(progress_cb, 25, "下载依赖库...")
    _phase(phase_cb, "libraries", 0, "下载原版支持库文件")
    for index, lib in enumerate(libraries):
        _check_cancel(cancel_cb)
        if not isinstance(lib, dict) or not library_allowed(lib):
            continue
        path = library_path(lib)
        if not path:
            continue
        url, size = _artifact_url(lib)
        if not url:
            continue
        dest = os.path.join(root, "libraries", path.replace("/", os.sep))
        if _file_matches(dest, size):
            continue
        pct = 25 + int(20 * (index + 1) / float(max(1, total_libs)))
        _report(progress_cb, pct, "下载依赖库 %d/%d" % (index + 1, total_libs))
        _phase(phase_cb, "libraries", int(100 * (index + 1) / float(max(1, total_libs))),
               "下载原版支持库文件")
        _download(url, dest, source, cancel_cb, expect_size=size, bytes_cb=bytes_cb)
    _phase(phase_cb, "libraries", 100, "下载原版支持库文件")

    # 4) 资源索引与资源文件
    asset_index = version_json.get("assetIndex") if isinstance(version_json.get("assetIndex"), dict) else {}
    index_id = str(asset_index.get("id") or version_json.get("assets") or "legacy")
    index_path = os.path.join(root, "assets", "indexes", index_id + ".json")
    _phase(phase_cb, "assets", 0, "下载原版资源文件")
    if isinstance(asset_index, dict) and asset_index.get("url"):
        _report(progress_cb, 45, "下载资源索引...")
        _download(str(asset_index["url"]), index_path, source, cancel_cb,
                  expect_size=_to_int(asset_index.get("size"), 0), bytes_cb=bytes_cb)
        index_data = _read_json(index_path)
        objects = index_data.get("objects") if isinstance(index_data.get("objects"), dict) else {}
        if objects:
            _report(progress_cb, 46, "资源文件 0/%d" % len(objects))
            _download_objects(root, source, objects, cfg, progress_cb, cancel_cb, 46, 48,
                              bytes_cb=bytes_cb)
    _phase(phase_cb, "assets", 100, "下载原版资源文件")
    _check_cancel(cancel_cb)

    # 5) natives
    _report(progress_cb, 95, "解压本地库...")
    _phase(phase_cb, "natives", 0, "解压本地库")
    natives_dir = os.path.join(version_dir, "natives")
    ensure_dir(natives_dir)
    for lib in libraries:
        if not isinstance(lib, dict) or not library_allowed(lib):
            continue
        key = _native_classifier_key(lib)
        if not key:
            continue
        path = _native_jar_path(lib, key)
        if not path:
            continue
        jar = os.path.join(root, "libraries", path.replace("/", os.sep))
        if not os.path.isfile(jar):
            classifiers = (lib.get("downloads") or {}).get("classifiers") if isinstance(lib.get("downloads"), dict) else None
            artifact = classifiers.get(key) if isinstance(classifiers, dict) else None
            if isinstance(artifact, dict) and artifact.get("url"):
                try:
                    remote.download_file(str(artifact["url"]), jar, source=source,
                                         cancel_cb=cancel_cb)
                except Exception:
                    pass
        if os.path.isfile(jar):
            extract = lib.get("extract") if isinstance(lib.get("extract"), dict) else {}
            extract_natives(jar, natives_dir, extract.get("exclude") if isinstance(extract, dict) else None)

    _report(progress_cb, 100, "安装完成")
    _phase(phase_cb, "done", 100, "安装游戏")
    return version_id


# ---------------------------------------------------------------- Fabric 安装
def install_quilt(mc_version: str, loader_version: str, root: str, cfg=None,
                  progress_cb=None, cancel_cb=None, phase_cb=None, bytes_cb=None) -> str:
    """安装 Quilt 版本(inheritsFrom 原版), 返回新版本 id。"""
    mc = str(mc_version or "").strip()
    loader = str(loader_version or "").strip()
    if not mc or not loader:
        raise RuntimeError("Quilt 安装需要 MC 版本与加载器版本")
    root = str(root)
    source = _source_of(cfg)
    version_id = "%s-Quilt_%s" % (mc, loader)
    mark_installing(root, version_id)
    progress_cb = adapt_progress_callback(progress_cb)

    _report(progress_cb, 2, "获取 Quilt 安装信息...")
    _phase(phase_cb, "prepare", 0, "获取 Quilt 安装信息")
    profile = remote.quilt_profile_json(mc, loader)
    if not isinstance(profile, dict) or not profile:
        raise RuntimeError("获取 Quilt 安装配置失败: %s" % version_id)
    _check_cancel(cancel_cb)

    profile["id"] = version_id
    profile["inheritsFrom"] = mc
    version_dir = os.path.join(root, "versions", version_id)
    ensure_dir(version_dir)
    _write_json(os.path.join(version_dir, version_id + ".json"), profile)
    _phase(phase_cb, "json", 100, "写入 Quilt 版本 json")

    libraries = profile.get("libraries") if isinstance(profile.get("libraries"), list) else []
    total = len(libraries)
    _phase(phase_cb, "libraries", 0, "下载 Quilt 依赖")
    for index, lib in enumerate(libraries):
        _check_cancel(cancel_cb)
        if not isinstance(lib, dict):
            continue
        path = library_path(lib)
        if not path:
            continue
        base = str(lib.get("url") or "").strip() or "https://maven.quiltmc.org/repository/release/"
        if not base.endswith("/"):
            base += "/"
        dest = os.path.join(root, "libraries", path.replace("/", os.sep))
        _report(progress_cb, 10 + int(85 * (index + 1) / float(max(1, total))),
                "下载 Quilt 依赖 %d/%d" % (index + 1, total))
        _phase(phase_cb, "libraries", int(100 * (index + 1) / float(max(1, total))), "下载 Quilt 依赖")
        if _file_matches(dest, 0):
            continue
        _download(base + path, dest, source, cancel_cb, bytes_cb=bytes_cb)

    _report(progress_cb, 100, "安装完成")
    _phase(phase_cb, "done", 100, "安装完成")
    return version_id


def find_java_for(cfg, mc_version: str = "") -> str:
    """挑一个合适的 Java 来跑安装器(按 MC 版本要求, 取不到就用最新的)。

    这里延迟 import launch, 因为 launch 会 import 本模块(避免循环导入)。
    """
    try:
        from . import launch as launch_mod
        required = int(launch_mod.required_java_for_version("", mc_version) or 8)
    except Exception:  # noqa: BLE001
        required = 8
    try:
        from . import launch as launch_mod
        picked, _fits = launch_mod.pick_java(launch_mod.find_javas(), required)
        if picked and getattr(picked, "path", ""):
            return str(picked.path)
    except Exception:  # noqa: BLE001
        pass
    return "java"


_COORD_RE = re.compile(r"^[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-+]+(?::[A-Za-z0-9_.\-]+)?$")

_LIBRARY_MIRRORS = (
    "https://bmclapi2.bangbang93.com/maven",
    "https://maven.minecraftforge.net",
    "https://maven.neoforged.net/releases",
    "https://repo1.maven.org/maven2",
    "https://libraries.minecraft.net",
)


def library_rel_path(coordinate: str) -> str:
    """``group:artifact:version[:classifier]`` → maven 相对路径。"""
    parts = str(coordinate or "").strip().split(":")
    if len(parts) < 3:
        return ""
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else ""
    name = "%s-%s%s.jar" % (artifact, version, ("-" + classifier) if classifier else "")
    return "%s/%s/%s/%s" % (group.replace(".", "/"), artifact, version, name)


def fetch_library(root: str, coordinate: str, source: str = "official") -> bool:
    """按坐标把库文件下到 ``libraries/``(安装器自己下不动时用它兜底)。"""
    rel = library_rel_path(coordinate)
    if not rel:
        return False
    dest = os.path.join(str(root), "libraries", rel.replace("/", os.sep))
    if _file_matches(dest, 0):
        return True
    ensure_dir(os.path.dirname(dest))
    for base in _LIBRARY_MIRRORS:
        try:
            if _download(base.rstrip("/") + "/" + rel, dest, source, None):
                return True
        except Exception:  # noqa: BLE001    换下一个镜像
            continue
    return False


def _failed_libraries(log_path: str) -> List[str]:
    """从安装器日志里挑出下载失败的库坐标。"""
    found = []  # type: List[str]
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = [ln.strip() for ln in handle]
    except OSError:
        return found
    for index, line in enumerate(lines):
        if "failed to download" in line.lower():
            for extra in lines[index + 1:index + 40]:
                if _COORD_RE.match(extra):
                    found.append(extra)
                elif extra and not extra.startswith(("net.", "com.", "org.", "trove")):
                    break
    for line in lines:
        if line.lower().startswith("considering library "):
            coord = line.split(" ", 2)[-1].strip()
            if _COORD_RE.match(coord):
                found.append(coord)
    # 去重并保持顺序
    seen = set()
    result = []  # type: List[str]
    for coord in found:
        if coord not in seen:
            seen.add(coord)
            result.append(coord)
    return result


def install_forge_like(loader: str, mc_version: str, loader_version: str, root: str,
                       cfg=None, java_path: str = "", progress_cb=None, cancel_cb=None,
                       phase_cb=None, bytes_cb=None) -> str:
    """用官方安装器安装 Forge / NeoForge, 返回安装出来的版本 id。

    步骤: 装好原版 → 准备好 launcher_profiles.json → 下载安装器 jar →
    在游戏目录里跑 ``--installClient`` → 找到新生成的版本目录。
    """
    kind = str(loader or "").strip().lower()
    mc = str(mc_version or "").strip()
    ver = str(loader_version or "").strip()
    if kind not in ("forge", "neoforge") or not mc or not ver:
        raise RuntimeError("安装参数不完整")
    root = str(root)
    source = _source_of(cfg)
    progress_cb = adapt_progress_callback(progress_cb)

    # 1) 原版必须先装好(安装器要在 versions/<mc>/ 里找到它)
    #    注意: 原版安装会报 0→100%, 直接透传的话任务总进度会先冲到 100%,
    #    所以这里把它压缩到 2%~25% 这一段。
    _report(progress_cb, 2, "检查原版 %s..." % mc)
    if not is_installed(root, mc):
        install_vanilla(mc, root, cfg,
                        lambda pct, text: _report(progress_cb, 2 + int(23 * pct / 100.0), text),
                        cancel_cb, phase_cb)
    _check_cancel(cancel_cb)

    # 2) 安装器需要一个 launcher_profiles.json 才认可这是启动器目录
    profiles = os.path.join(root, "launcher_profiles.json")
    if not os.path.isfile(profiles):
        _write_json(profiles, {"profiles": {}, "settings": {}, "version": 3})

    # 3) 下载安装器(多个候选地址, 官方 maven 在国内可能连不上)
    if kind == "forge":
        urls = remote.forge_installer_urls(mc, ver)
        name = "forge-%s-%s-installer.jar" % (mc, ver)
    else:
        urls = remote.neoforge_installer_urls(ver)
        name = "neoforge-%s-installer.jar" % ver
    dest = os.path.join(cache_dir(), "installers", name)
    ensure_dir(os.path.dirname(dest))
    _report(progress_cb, 6, "下载 %s 安装器..." % kind)
    _phase(phase_cb, "prepare", 10, "下载安装器")
    if not _file_matches(dest, 0):
        ok = False
        for url in urls:
            _check_cancel(cancel_cb)
            try:
                _download(url, dest, source, cancel_cb)
                ok = True
                break
            except Exception:  # noqa: BLE001   换下一个镜像
                continue
        if not ok:
            raise RuntimeError("下载 %s 安装器失败: %s" % (kind, urls[0]))
    _check_cancel(cancel_cb)

    # 4) 跑安装器(工作目录必须是游戏目录); 安装器自己下载失败时用镜像补下再重试
    java = str(java_path or "").strip() or find_java_for(cfg, mc)
    log_path = os.path.join(cache_dir(), "installers", name + ".log")
    ensure_dir(os.path.dirname(log_path))
    versions_root = os.path.join(root, "versions")
    before = set(os.listdir(versions_root)) if os.path.isdir(versions_root) else set()
    libraries_root = os.path.join(root, "libraries")
    _phase(phase_cb, "libraries", 5, "运行安装器")

    code = 1
    created = []  # type: List[str]
    for attempt in range(3):
        _report(progress_cb, 25 + attempt * 8,
                "运行 %s 安装器(需要下载依赖, 可能要几分钟)..." % kind)
        _phase(phase_cb, "libraries", 5 + attempt * 5, "运行安装器")
        try:
            with open(log_path, "w", encoding="utf-8", errors="ignore") as handle:
                proc = subprocess.Popen([java, "-jar", dest, "--installClient"], cwd=root,
                                        stdout=handle, stderr=subprocess.STDOUT,
                                        creationflags=_no_window_flag())
                # 安装器只在它自己下载时才有进度, 这里用 libraries 目录大小的增量
                # 来喂给启动器的速度统计(否则界面上速度/剩余一直是 --)
                last_size = _dir_bytes(libraries_root)
                idle = 0.0
                while proc.poll() is None:
                    if _cancelled(cancel_cb):
                        try:
                            proc.terminate()
                        except Exception:  # noqa: BLE001
                            pass
                        raise _Cancelled()
                    time.sleep(0.5)
                    idle += 0.5
                    if bytes_cb is not None and idle >= 1.0:
                        idle = 0.0
                        size = _dir_bytes(libraries_root)
                        if size > last_size:
                            try:
                                bytes_cb(size - last_size)
                            except Exception:  # noqa: BLE001
                                pass
                            last_size = size
            code = proc.returncode
        except _Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("运行 %s 安装器失败: %s" % (kind, exc))

        after = set(os.listdir(versions_root)) if os.path.isdir(versions_root) else set()
        created = sorted(after - before)
        if code == 0 and created:
            break
        # 安装器失败了: 看它有哪些库没下下来, 用镜像补上再重试一次
        missing = _failed_libraries(log_path)
        if not missing or attempt >= 2:
            break
        _report(progress_cb, 30 + attempt * 8,
                "安装器有 %d 个库下载失败, 正在用镜像补下..." % len(missing))
        fixed = 0
        for coord in missing:
            _check_cancel(cancel_cb)
            if fetch_library(root, coord, source):
                fixed += 1
        if fixed == 0:
            break
        _report(progress_cb, 34 + attempt * 8, "已补齐 %d 个库, 重试安装器..." % fixed)

    # 5) 找出新装出来的版本目录
    after = set(os.listdir(versions_root)) if os.path.isdir(versions_root) else set()
    if not created:
        created = sorted(after - before)
    version_id = ""
    for name_ in created:
        if kind == "forge" and "forge" in name_.lower():
            version_id = name_
        elif kind == "neoforge" and "neoforge" in name_.lower():
            version_id = name_
    if not version_id and created:
        version_id = created[0]
    if not version_id or code != 0:
        tail = ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                tail = "".join(handle.readlines()[-8:])
        except OSError:
            pass
        raise RuntimeError("%s 安装器退出码 %s, 未能完成安装。\n%s" % (kind, code, tail))

    _report(progress_cb, 100, "%s 安装完成" % kind)
    _phase(phase_cb, "done", 100, "安装完成")
    return version_id


def _download_direct(url: str, dest: str, timeout: int = 60) -> bool:
    """直连下载(有些镜像不带 Content-Length, 走通用下载器会失败)。"""
    try:
        import urllib.request
        ensure_dir(os.path.dirname(os.path.abspath(dest)))
        request = remote._request(url)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with open(dest, "wb") as out:
                shutil.copyfileobj(response, out, 64 * 1024)
        return os.path.getsize(dest) > 1024 * 200      # 太小的多半是网页
    except Exception:  # noqa: BLE001
        return False


def run_optifine_installer(mc_version: str, version: str, root: str, cfg=None,
                           java_path: str = "", progress_cb=None) -> str:
    """下载并启动 OptiFine 官方安装器(它自带 GUI, 用户点一次 Install 即可)。

    OptiFine 没有提供静默安装的参数, 所以这里做到"下载 + 启动 + 说明"这一步;
    装好后启动器会自动识别出 `<mc>-OptiFine_<ver>` 版本。
    """
    mc = str(mc_version or "").strip()
    ver = str(version or "").strip()
    if not mc or not ver:
        raise RuntimeError("OptiFine 安装参数不完整")
    source = _source_of(cfg)
    name = "OptiFine_%s_%s.jar" % (mc, ver)
    dest = os.path.join(cache_dir(), "installers", name.replace("_", "-", 1))
    ensure_dir(os.path.dirname(dest))
    _report(progress_cb, 5, "下载 OptiFine %s 安装器..." % ver)
    ok = False
    last_error = ""
    for url in remote.optifine_installer_urls(mc, ver):
        try:
            if _file_matches(dest, 0):
                ok = True
                break
            if _download(url, dest, source, None):
                ok = True
                break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        # 通用下载器失败时改用直连(OptiFine 镜像通常没有 Content-Length)
        if not ok and _download_direct(url, dest):
            ok = True
            break
    if not ok:
        raise RuntimeError(
            "没能自动下载 OptiFine 安装器（官网有防盗链）。\n"
            "请到 https://optifine.net/downloads 手动下载 %s，\n"
            "运行它点一次 Install，本启动器会自动识别装好的版本。%s"
            % (name, ("\n" + last_error) if last_error else ""))
    java = str(java_path or "").strip() or find_java_for(cfg, mc)
    _report(progress_cb, 90, "启动 OptiFine 安装器…")
    try:
        subprocess.Popen([java, "-jar", dest], cwd=str(root), close_fds=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("启动 OptiFine 安装器失败: %s" % exc)
    return dest


def _dir_bytes(path: str) -> int:
    """目录总大小(用来估算安装器下载进度)。"""
    total = 0
    try:
        for base, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                except OSError:
                    continue
    except OSError:
        return total
    return total


_INSTALL_MARK = ".pclpy_installing"


def mark_installing(root: str, version_id: str) -> None:
    """在版本目录写"安装中"占位文件(扫描器会跳过带它的目录)。"""
    vid = str(version_id or "")
    if not vid:
        return
    try:
        folder = os.path.join(str(root), "versions", vid)
        ensure_dir(folder)
        with open(os.path.join(folder, _INSTALL_MARK), "w", encoding="utf-8") as handle:
            handle.write("installing")
    except Exception:  # noqa: BLE001
        pass


def clear_installing(root: str, version_id: str) -> None:
    """删除"安装中"占位文件(安装成功后调用)。"""
    vid = str(version_id or "")
    if not vid:
        return
    try:
        os.remove(os.path.join(str(root), "versions", vid, _INSTALL_MARK))
    except Exception:  # noqa: BLE001
        pass


def _version_has_userdata(root: str, version_id: str) -> bool:
    """版本目录里是否已有用户数据(mods 有文件 / saves 有子目录)。"""
    base = os.path.join(str(root), "versions", version_id)
    try:
        mods = os.path.join(base, "mods")
        if os.path.isdir(mods) and any(os.scandir(mods)):
            return True
    except OSError:
        pass
    try:
        saves = os.path.join(base, "saves")
        if os.path.isdir(saves):
            for entry in os.scandir(saves):
                if entry.is_dir():
                    return True
    except OSError:
        pass
    return False


def cleanup_unfinished(root: str) -> List[str]:
    """清理**未完成**的安装: 带占位文件、且没有用户数据的版本目录。

    安全性(删除类操作必须谨慎): 只有同时满足下面两条才会删 ——
      1. 目录里有我们写的 ``.pclpy_installing`` 占位(说明是没装完的, 不是用户的正常版本)
      2. 目录里没有 mods 文件 / saves 存档(有的话一律保留, 学 PCL2 ModDownloadLib.vb:1815-1829)
    返回被清理掉的版本 id 列表。
    """
    import shutil as _shutil
    removed = []  # type: List[str]
    versions_root = os.path.join(str(root), "versions")
    try:
        names = os.listdir(versions_root)
    except OSError:
        return removed
    for name in names:
        folder = os.path.join(versions_root, name)
        try:
            if not os.path.isdir(folder):
                continue
            if not os.path.isfile(os.path.join(folder, _INSTALL_MARK)):
                continue
            if _version_has_userdata(str(root), name):
                continue
            _shutil.rmtree(folder)
            removed.append(name)
        except Exception:  # noqa: BLE001
            continue
    return removed


def _find_client_jar(root: str, version_id: str) -> str:
    """沿 inheritsFrom 链找第一个存在的 ``<版本>.jar``(启动器也是这样找客户端的)。"""
    seen = set()  # type: set
    current = str(version_id or "")
    while current and current not in seen:
        seen.add(current)
        path = os.path.join(str(root), "versions", current, current + ".jar")
        if os.path.isfile(path):
            return path
        parent = ""
        try:
            data = _read_json(os.path.join(str(root), "versions", current, current + ".json"))
            parent = str(data.get("inheritsFrom") or "") if isinstance(data, dict) else ""
        except Exception:  # noqa: BLE001
            parent = ""
        current = parent
    return ""


def make_self_contained(root: str, version_id: str) -> bool:
    """把版本变成**完全自包含**: 合并 inheritsFrom 链 + 补齐本地客户端 jar + 清掉 inheritsFrom。

    为什么必须"先合并再清"(PCL2 的铁律 `ModDownloadLib.vb:2110-2146`):
    json 里若只有加载器自己那部分 libraries/arguments, 原版库、natives、启动参数
    (Forge 的 --fml.* / minecraftArguments 等)全在父版本那边 —— 直接清 inheritsFrom
    会让游戏启动失败。所以这里先做**链式合并**, 再删继承字段, 最后把客户端 jar
    复制到本版本目录(合并后启动器就只认自己的 jar 了)。

    失败时保持原样(仍可正常启动, 只是继续依赖父版本)。
    """
    from . import launch as launch_mod      # 局部导入, 避免模块级循环依赖

    vid = str(version_id or "")
    target_dir = os.path.join(str(root), "versions", vid)
    if not vid or not os.path.isdir(target_dir):
        return False
    try:
        merged = launch_mod.merge_version_json(str(root), vid)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(merged, dict) or not merged:
        return False
    jar_src = _find_client_jar(str(root), vid)
    jar_dst = os.path.join(target_dir, vid + ".jar")
    if jar_src and os.path.abspath(jar_src) != os.path.abspath(jar_dst):
        import shutil as _shutil
        try:
            _shutil.copy2(jar_src, jar_dst)
        except Exception:  # noqa: BLE001
            return False
    data = dict(merged)
    data["id"] = vid
    data["inheritsFrom"] = ""
    data.pop("jar", None)
    try:
        _write_json(os.path.join(target_dir, vid + ".json"), data)
    except Exception:  # noqa: BLE001
        return False
    return True


def copy_version_as(root: str, old_id: str, new_id: str) -> str:
    """把已安装的版本**完整复制**成一个独立的新版本(自定义命名时用)。

    与 rename_version 的区别: rename 是"搬走"(原版本消失), 而复制会留下**两份互相独立的
    示例** —— 新目录里有自己的 `<新名字>.jar`、`<新名字>.json`、自己的 natives/downloads/
    资源包等, 可以直接单独启动、单独删除, 不依赖原版本。

    细节:
      * 复制整个 ``versions/<old_id>/`` 目录
      * json 改名为 ``<new_id>.json`` 且 ``id`` 改为新名字
      * 若目录里有 ``<old_id>.jar`` 客户端 → 改名为 ``<new_id>.jar``, 并**去掉 inheritsFrom**
        (这样它是完全自包含的独立实例)
      * 加载器版本目录里通常没有客户端 jar, 此时保留 inheritsFrom(仍能正常启动)
    """
    if not old_id or not new_id or old_id == new_id:
        return old_id
    versions_root = os.path.join(str(root), "versions")
    old_dir = os.path.join(versions_root, old_id)
    new_dir = os.path.join(versions_root, new_id)
    if not os.path.isdir(old_dir) or os.path.exists(new_dir):
        return old_id
    try:
        shutil.copytree(old_dir, new_dir,
                        ignore=shutil.ignore_patterns(_INSTALL_MARK))
    except Exception:  # noqa: BLE001
        return old_id
    try:
        # 1) json 改名 + 改 id
        old_json = os.path.join(new_dir, old_id + ".json")
        new_json = os.path.join(new_dir, new_id + ".json")
        data = {}  # type: dict
        if os.path.isfile(old_json):
            try:
                with open(old_json, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:  # noqa: BLE001
                data = {}
            os.replace(old_json, new_json)
        if not isinstance(data, dict):
            data = {}
        data["id"] = new_id
        # 2) 客户端 jar 改名; 有了自己的 jar 就不需要再继承别的版本
        old_jar = os.path.join(new_dir, old_id + ".jar")
        new_jar = os.path.join(new_dir, new_id + ".jar")
        if os.path.isfile(old_jar):
            os.replace(old_jar, new_jar)
            data["inheritsFrom"] = ""
        data["pclpy:description"] = data.get("pclpy:description") or ("复制自 %s" % old_id)
        _write_json(new_json, data)
    except Exception:  # noqa: BLE001
        return old_id
    # 关键: 复制完立刻"自包含化" —— 合并 inheritsFrom 链 + 复制客户端 jar + 清继承字段。
    # 这样副本与源版本**互不依赖**(源版本改名/删除都不影响它), 满足"两份独立实例"的要求。
    make_self_contained(root, new_id)
    # 隔离标记写进 versions/<id>/PCL/Setup.ini(与 PCL2 一致, 版本 json 保持纯净),
    # 并同时写 PCL 兼容键, 这样两个启动器互相认。
    write_isolation_flag(root, new_id, True)
    # 占位文件必须两边都清: 副本可能是从"安装中"的源复制来的(copytree 会连占位一起复制),
    # 源版本的占位也常常还没轮到清 —— 任一个残留都会让版本在列表里凭空消失。
    clear_installing(root, old_id)
    clear_installing(root, new_id)
    return new_id


def write_isolation_flag(root: str, version_id: str, isolate: bool) -> bool:
    """把"版本隔离"写进 ``versions\\<id>\\PCL\\Setup.ini``(PCL2 的存放位置)。

    同时写两份键:
      * 我们/PCL2 新版都认的 ``VersionArgumentIndieV2=True/False``
      * PCL2 遗留的 ``VersionArgumentIndie=1/2``
    这样版本 json 保持对 Mojang / 其它启动器纯净, 且与 PCL2 互认。
    """
    vid = str(version_id or "")
    if not vid:
        return False
    folder = os.path.join(str(root), "versions", vid, "PCL")
    path = os.path.join(folder, "Setup.ini")
    try:
        os.makedirs(folder, exist_ok=True)
        lines = []  # type: List[str]
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                lines = [line.rstrip("\n") for line in handle]
        wanted = {
            "versionargumentindiev2": "True" if isolate else "False",
            "versionargumentindie": "1" if isolate else "2",
        }
        out = []  # type: List[str]
        seen = set()  # type: set
        for line in lines:
            key = line.partition(":")[0].strip().lower() if ":" in line else ""
            if key in wanted:
                out.append("%s:%s" % (line.partition(":")[0].strip(), wanted[key]))
                seen.add(key)
            elif line.strip():
                out.append(line)
        for key, value in wanted.items():
            if key not in seen:
                out.append("%s:%s" % (key, value))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def rename_version(root: str, old_id: str, new_id: str) -> str:
    """把安装出来的版本改成统一命名(目录、json 文件名与 id 一起改), 返回新 id。"""
    if not old_id or not new_id or old_id == new_id:
        return old_id
    versions_root = os.path.join(root, "versions")
    old_dir = os.path.join(versions_root, old_id)
    new_dir = os.path.join(versions_root, new_id)
    if not os.path.isdir(old_dir) or os.path.exists(new_dir):
        return old_id
    try:
        os.rename(old_dir, new_dir)
        old_json = os.path.join(new_dir, old_id + ".json")
        new_json = os.path.join(new_dir, new_id + ".json")
        if os.path.isfile(old_json):
            os.rename(old_json, new_json)
        if os.path.isfile(new_json):
            data = _read_json(new_json)
            if isinstance(data, dict):
                data["id"] = new_id
                _write_json(new_json, data)
    except Exception:  # noqa: BLE001
        return old_id
    return new_id


def _no_window_flag() -> int:
    """Windows 上不弹出控制台窗口。"""
    return 0x08000000 if os.name == "nt" else 0


def install_fabric(mc_version: str, loader_version: str, root: str, cfg=None,
                   progress_cb=None, cancel_cb=None, phase_cb=None, bytes_cb=None) -> str:
    """安装 Fabric 版本(inheritsFrom 原版), 返回新版本 id。"""
    mc = str(mc_version or "").strip()
    loader = str(loader_version or "").strip()
    if not mc or not loader:
        raise RuntimeError("Fabric 安装需要 MC 版本与加载器版本")
    root = str(root)
    source = _source_of(cfg)
    version_id = "%s-Fabric_%s" % (mc, loader)
    mark_installing(root, version_id)
    progress_cb = adapt_progress_callback(progress_cb)

    _report(progress_cb, 2, "获取 Fabric 安装信息...")
    _phase(phase_cb, "prepare", 0, "获取 Fabric 安装信息")
    profile = remote.fabric_profile_json(mc, loader)
    if not isinstance(profile, dict) or not profile:
        raise RuntimeError("获取 Fabric 安装配置失败: %s" % version_id)
    _check_cancel(cancel_cb)

    profile["id"] = version_id
    profile["inheritsFrom"] = mc
    version_dir = os.path.join(root, "versions", version_id)
    ensure_dir(version_dir)
    json_path = os.path.join(version_dir, version_id + ".json")
    _write_json(json_path, profile)
    _phase(phase_cb, "json", 100, "写入 Fabric 版本 json")

    libraries = profile.get("libraries") if isinstance(profile.get("libraries"), list) else []
    total = len(libraries)
    _phase(phase_cb, "libraries", 0, "下载 Fabric 依赖")
    for index, lib in enumerate(libraries):
        _check_cancel(cancel_cb)
        if not isinstance(lib, dict):
            continue
        path = library_path(lib)
        if not path:
            continue
        base = str(lib.get("url") or "").strip() or "https://maven.fabricmc.net/"
        if not base.endswith("/"):
            base += "/"
        dest = os.path.join(root, "libraries", path.replace("/", os.sep))
        pct = 10 + int(85 * (index + 1) / float(max(1, total)))
        _report(progress_cb, pct, "下载 Fabric 依赖 %d/%d" % (index + 1, total))
        _phase(phase_cb, "libraries", int(100 * (index + 1) / float(max(1, total))),
               "下载 Fabric 依赖")
        if _file_matches(dest, 0):
            continue
        _download(base + path, dest, source, cancel_cb, bytes_cb=bytes_cb)

    _report(progress_cb, 100, "安装完成")
    _phase(phase_cb, "done", 100, "安装游戏")
    return version_id
