"""Java 查找与启动命令构建。

build_launch() 负责合并 inheritsFrom 继承链、拼装 classpath、natives、
占位符替换与内存参数, 最终给出可直接 Popen 的命令行。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .accounts import offline_uuid
from .install import extract_natives, library_allowed, library_path, rule_allows
from .paths import ensure_dir
from .versions import parse_version_id

# 平台对应的 natives 分类键
_NATIVES_KEY = "windows" if os.name == "nt" else ("osx" if sys.platform == "darwin" else "linux")

# 默认主类
_DEFAULT_MAIN = "net.minecraft.client.main.Main"


# ---------------------------------------------------------------- Java
@dataclass
class JavaInfo:
    """一个可用的 Java 运行时。"""

    path: str
    version: str = ""
    arch: str = ""

    def label(self) -> str:
        """显示名, 例如 "Java 8 (8.0.481.0)"。"""
        major = java_major(self.version)
        shown = _display_version(self.version)
        if major and shown:
            return "Java %d (%s)" % (major, shown)
        if major:
            return "Java %d" % major
        if shown:
            return "Java (%s)" % shown
        return "Java"


def java_major(version: str) -> int:
    """从 Java 版本号取主版本(1.8.0_481 -> 8)。"""
    text = str(version or "").strip()
    match = re.match(r"^(\d+)(?:\.(\d+))?", text)
    if not match:
        return 0
    if match.group(1) == "1" and match.group(2):
        return int(match.group(2))
    return int(match.group(1))


def _display_version(version: str) -> str:
    """把内部版本号转成显示用版本号(1.8.0_481 -> 8.0.481.0)。"""
    text = str(version or "").split("+")[0].strip()
    if not text:
        return ""
    match = re.match(r"^1\.(\d+)\.(\d+)(?:[_\.](\d+))?", text)
    if match:
        return "%d.%d.%d.0" % (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    return text


def _java_version(path: str) -> Tuple[str, str]:
    """运行 java -version 解析 (版本号, 架构), 失败返回 ("", "")。"""
    try:
        kwargs = {"capture_output": True, "timeout": 5}  # type: Dict[str, Any]
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = subprocess.run([str(path), "-version"], **kwargs)
        raw = (proc.stderr or b"") + (proc.stdout or b"")
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
    except Exception:
        return "", ""
    version = ""
    match = re.search(r'version "([^"]+)"', text)
    if match:
        version = match.group(1)
    else:
        match = re.search(r"(?:openjdk|java)\s+(\d[\w.+\-]*)", text, re.I)
        if match:
            version = match.group(1)
    arch = ""
    if "64-Bit" in text:
        arch = "x64"
    elif "32-Bit" in text:
        arch = "x86"
    return version, arch


def _java_sort_key(info: JavaInfo) -> tuple:
    """Java 排序键: 主版本 + 版本数字元组。"""
    numbers = tuple(int(x) for x in re.findall(r"\d+", str(info.version or "")))
    return (java_major(info.version), numbers)


def find_javas() -> List[JavaInfo]:
    """查找系统里的 Java(PATH、JAVA_HOME、常见安装目录), 版本高的在前。"""
    found = []  # type: List[str]
    try:
        which = shutil.which("java")
        if which:
            found.append(str(which))
    except Exception:
        pass
    if os.name == "nt":
        try:
            kwargs = {"capture_output": True, "timeout": 5}  # type: Dict[str, Any]
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            proc = subprocess.run(["where", "java"], **kwargs)
            text = (proc.stdout or b"").decode("utf-8", "ignore")
            for line in text.splitlines():
                line = line.strip()
                if line.lower().endswith(".exe"):
                    found.append(line)
        except Exception:
            pass
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        for exe in ("javaw.exe", "java.exe"):
            candidate = os.path.join(java_home, "bin", exe)
            if os.path.isfile(candidate):
                found.append(candidate)
    patterns = [
        r"C:\Program Files\Java\*\bin\javaw.exe",
        r"C:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\javaw.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\javaw.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
        r"C:\Program Files (x86)\Java\*\bin\java.exe",
        r"C:\Program Files\Zulu\*\bin\javaw.exe",
        r"C:\Program Files\BellSoft\*\bin\javaw.exe",
    ]
    for pattern in patterns:
        try:
            for candidate in glob.glob(pattern):
                found.append(candidate)
        except Exception:
            continue

    # 去重: 同一个 bin 目录优先保留 javaw.exe
    unique = {}  # type: Dict[str, str]
    for candidate in found:
        try:
            key = os.path.normcase(os.path.dirname(os.path.abspath(candidate)))
        except Exception:
            continue
        old = unique.get(key)
        if old is None:
            unique[key] = candidate
            continue
        if os.path.basename(candidate).lower().startswith("javaw") and \
                not os.path.basename(old).lower().startswith("javaw"):
            unique[key] = candidate

    # 同一目录里存在 javaw.exe 时改用 javaw(避免多弹一个控制台窗口)
    for key, candidate in list(unique.items()):
        sibling = os.path.join(os.path.dirname(candidate), "javaw.exe")
        if os.path.isfile(sibling):
            unique[key] = sibling

    result = []  # type: List[JavaInfo]
    for candidate in unique.values():
        version, arch = _java_version(candidate)
        result.append(JavaInfo(path=candidate, version=version, arch=arch))
    try:
        result.sort(key=_java_sort_key, reverse=True)
    except Exception:
        pass
    return result


def required_java_major(mc_version: str) -> int:
    """按 MC 版本猜最低 Java 主版本。"""
    numbers = re.findall(r"\d+", str(mc_version or ""))
    if not numbers:
        return 8
    key = tuple(int(x) for x in numbers[:3])
    if key >= (1, 20, 5):
        return 21
    if key >= (1, 18):
        return 17
    return 8


def java_for_version(java_versions: List[JavaInfo], mc_version: str, configured: str = "auto") -> JavaInfo:
    """挑选合适的 Java: 显式配置优先, 否则按 MC 版本猜最低要求。"""
    items = list(java_versions or [])
    try:
        items.sort(key=_java_sort_key, reverse=True)
    except Exception:
        pass
    want = str(configured or "").strip()
    if want and want.lower() != "auto":
        try:
            want_norm = os.path.normcase(os.path.abspath(want))
            for item in items:
                if os.path.normcase(os.path.abspath(item.path)) == want_norm:
                    return item
        except Exception:
            pass
        if os.path.isfile(want):
            return JavaInfo(path=want, version="")
    if not items:
        return JavaInfo(path="java", version="")
    best, _ok = pick_java(items, required_java_major(mc_version))
    return best


def _is_shim(path: str) -> bool:
    """Oracle 的 javapath / java8path 是转发用的壳, 会另起进程导致拿不到输出与退出码。"""
    text = str(path or "").lower()
    return "javapath" in text or "java8path" in text


def _java_preference(info: "JavaInfo") -> tuple:
    """同一 Java 主版本下的偏好: 非壳程序优先, 其次 javaw.exe 优先。"""
    return (1 if _is_shim(info.path) else 0,
            0 if os.path.basename(info.path).lower().startswith("javaw") else 1)


def pick_java(java_versions: List[JavaInfo], required: int) -> Tuple[JavaInfo, bool]:
    """挑主版本 >= required 的最低那个(够用即可, 不要盲目用最高版本)。

    返回 (JavaInfo, 是否满足要求)。都不满足时退回已安装的最高版本, 并由调用方给出警告。
    """
    items = [j for j in (java_versions or []) if j and j.path]
    try:
        items.sort(key=_java_sort_key)
    except Exception:
        pass
    try:
        need = int(required or 0)
    except Exception:
        need = 0

    def _best_of(group: List[JavaInfo]) -> JavaInfo:
        group = sorted(group, key=_java_preference)
        real = [j for j in group if not _is_shim(j.path)]
        return (real or group)[0]

    fits = [j for j in items if java_major(j.version) >= need]
    if fits:
        lowest = java_major(fits[0].version)
        same_major = [j for j in fits if java_major(j.version) == lowest]
        return _best_of(same_major), True
    if items:
        top = java_major(items[-1].version)
        same_major = [j for j in items if java_major(j.version) == top]
        return _best_of(same_major), False
    return JavaInfo(path="java", version=""), False


def required_java_from_json(merged: dict, mc_version: str = "") -> int:
    """从版本 json 的 javaVersion.majorVersion 读取所需 Java 主版本。

    Minecraft 1.17 之后 json 里会写明需要的 Java 大版本(例如 26.3 需要 25),
    只按 MC 版本号猜是不够的, 必须以这个字段为准。
    """
    java_version = merged.get("javaVersion") if isinstance(merged, dict) else None
    if isinstance(java_version, dict):
        major = _int_of(java_version.get("majorVersion"), 0)
        if major > 0:
            return major
    return required_java_major(mc_version)


def required_java_for_version(root: str, version_id: str) -> int:
    """给定已安装版本, 返回它需要的 Java 主版本。"""
    merged = merge_version_json(root, version_id)
    mc_version = str(merged.get("inheritsFrom") or "") or \
        str(parse_version_id(version_id).get("mc_version") or version_id)
    return required_java_from_json(merged, mc_version)


# ---------------------------------------------------------------- 版本 json 合并
def _read_json(path: str) -> dict:
    """读 JSON, 失败返回 {}。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_two(parent: dict, child: dict) -> dict:
    """子版本 json 覆盖父版本, libraries/arguments 特殊合并。"""
    out = {}  # type: Dict[str, Any]
    for key, value in (parent or {}).items():
        out[key] = value
    for key, value in (child or {}).items():
        if key == "libraries":
            merged = []  # type: List[Any]
            seen = set()
            for lib in list(child.get("libraries") or []) + list(parent.get("libraries") or []):
                name = lib.get("name") if isinstance(lib, dict) else str(lib)
                if name in seen:
                    continue
                seen.add(name)
                merged.append(lib)
            out["libraries"] = merged
        elif key == "arguments":
            parent_args = parent.get("arguments") if isinstance(parent.get("arguments"), dict) else {}
            child_args = value if isinstance(value, dict) else {}
            merged_args = {}  # type: Dict[str, Any]
            for arg_key in ("game", "jvm"):
                merged_args[arg_key] = list(parent_args.get(arg_key) or []) + list(child_args.get(arg_key) or [])
            for arg_key, arg_value in parent_args.items():
                merged_args.setdefault(arg_key, arg_value)
            for arg_key, arg_value in child_args.items():
                if arg_key not in merged_args:
                    merged_args[arg_key] = arg_value
            out["arguments"] = merged_args
        else:
            # ⚠️ 空值("" / [] / {} / None)不算"覆盖"。
            # 否则子版本里一个空的 mainClass 就会把父版本(例如 Forge 的 BootstrapLauncher)
            # 清成空, 空的 libraries 又会把父版本的全部库清掉 —— 启动时就是
            # "ClassNotFoundException: net.minecraft.client.main.Main"(踩过这个坑)。
            if value is None or value == "" or value == [] or value == {}:
                if out.get(key) is None or out.get(key) == "" or out.get(key) == [] \
                        or out.get(key) == {}:
                    out[key] = value
                continue
            out[key] = value
    return out


def merge_version_json(root: str, version_id: str) -> dict:
    """读取并合并 inheritsFrom 继承链(子覆盖父)。"""
    path = os.path.join(str(root), "versions", str(version_id), str(version_id) + ".json")
    data = _read_json(path)
    if not data:
        return {}
    parent_id = str(data.get("inheritsFrom") or "")
    if parent_id:
        parent = merge_version_json(root, parent_id)
        if parent:
            return _merge_two(parent, data)
        data = dict(data)
        data.pop("inheritsFrom", None)
    return data


# ---------------------------------------------------------------- 启动计划
@dataclass
class LaunchPlan:
    """一次启动的完整计划。"""

    command: List[str]
    cwd: str
    java: str
    version_id: str
    main_class: str = ""
    warnings: List[str] = field(default_factory=list)


_ARG_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_VERSION_NUM_RE = re.compile(r"\d+")


def _version_sort_key(version: str) -> tuple:
    """把库版本号变成可比较的元组(9.6 < 9.9, 1.0.22 > 1.0.9)。"""
    numbers = tuple(int(x) for x in _VERSION_NUM_RE.findall(str(version or ""))[:6])
    return (numbers, str(version or ""))


def _library_identity(lib: dict) -> Tuple[str, str]:
    """返回 (group:artifact:classifier, 版本号)。"""
    parts = str(lib.get("name") or "").split(":")
    if len(parts) < 3:
        return "", ""
    classifier = parts[3] if len(parts) > 3 else ""
    return "%s:%s:%s" % (parts[0], parts[1], classifier), parts[2]


def dedupe_libraries(libraries: List[Any]) -> List[Any]:
    """同一个 group:artifact:classifier 只保留版本最高的一个。

    加载器(Forge/NeoForge/Fabric)的版本 json 常常同时列着原版自带的旧库和加载器
    自己的新库(例如 asm 9.6 与 asm 9.9), 两个都进 classpath 会被 Fabric 判定为
    "duplicate ASM classes" 直接崩溃, 这里按 artifact 去重保留新版。
    """
    best = {}  # type: Dict[str, Any]
    versions = {}  # type: Dict[str, str]
    order = []  # type: List[str]
    for lib in (libraries or []):
        if not isinstance(lib, dict):
            continue
        key, version = _library_identity(lib)
        if not key:
            continue
        if key not in best:
            best[key] = lib
            versions[key] = version
            order.append(key)
            continue
        if _version_sort_key(version) > _version_sort_key(versions.get(key, "")):
            best[key] = lib
            versions[key] = version
    return [best[key] for key in order]


def _split_args(text) -> List[str]:
    """按空格拆分参数, 保留引号内的空格。"""
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        return [str(x) for x in text]
    result = []  # type: List[str]
    for match in _ARG_RE.finditer(str(text)):
        if match.group(1) is not None:
            result.append(match.group(1))
        elif match.group(2) is not None:
            result.append(match.group(2))
        else:
            result.append(match.group(3))
    return result


def _arg_values(item) -> List[str]:
    """取一个 arguments 条目展开后的字符串列表(不满足 rules 时返回 [])。"""
    if isinstance(item, str):
        return [item]
    if isinstance(item, dict):
        if not rule_allows(item.get("rules"), {"is_demo_user": False, "has_custom_resolution": False}):
            return []
        value = item.get("value")
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(x) for x in value]
    return []


def _total_memory_mb() -> int:
    """估算物理内存(MB), 失败返回 4096。"""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore[attr-defined]
        page_size = os.sysconf("SC_PAGE_SIZE")  # type: ignore[attr-defined]
        total = int(pages) * int(page_size) // (1024 * 1024)
        if total > 0:
            return total
    except Exception:
        pass
    try:
        import ctypes  # 只在需要时导入

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            total = int(status.ullTotalPhys) // (1024 * 1024)
            if total > 0:
                return total
    except Exception:
        pass
    return 4096


def _int_of(value, default: int) -> int:
    """安全取整数配置。"""
    try:
        return int(value)
    except Exception:
        return default


def _game_arg_value(merged: dict, name: str) -> str:
    """从版本 json 的 game 参数里取 --xxx 后面跟的值。"""
    arguments = merged.get("arguments") if isinstance(merged.get("arguments"), dict) else {}
    items = arguments.get("game") or []
    flat = []  # type: List[str]
    for item in items:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, list):
            flat.extend(str(x) for x in item)
    for index, value in enumerate(flat):
        if value == name and index + 1 < len(flat):
            return flat[index + 1]
    return ""


def is_modded_version(root: str, version_id: str, merged: Optional[dict] = None) -> bool:
    """这个版本是不是带 Mod 加载器(Fabric / Forge / NeoForge / Quilt / OptiFine 等)。"""
    try:
        data = merged if isinstance(merged, dict) else merge_version_json(root, version_id)
    except Exception:  # noqa: BLE001
        return False
    main_class = str(data.get("mainClass") or "").lower()
    for key in ("fabric", "forge", "neoforge", "quilt", "launchwrapper",
                "bootstraplauncher", "modlauncher", "liteloader", "optifine"):
        if key in main_class:
            return True
    for lib in (data.get("libraries") or []):
        name = str(lib.get("name") if isinstance(lib, dict) else "").lower()
        for key in ("fabric-loader", "net.minecraftforge:forge", "net.neoforged:neoforge",
                    "quilt-loader", "optifine", "liteloader"):
            if key in name:
                return True
    return False


def _pcl_global_isolation(root: str) -> str:
    """读 PCL2 的**全局**隔离档位 ``PCL\\Setup.ini!LaunchArgumentIndieV2``(0..4)。

    PCL2 语义: 0 关闭 / 1 仅隔离可装 Mod 的版本 / 2 仅隔离非正式版 /
    3 非正式版+可装 Mod / 4 隔离所有版本。返回我们自己的 "close"/"mod"/"open"/""。
    """
    path = os.path.join(str(root), "PCL", "Setup.ini")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return ""
    value = ""
    for line in text.splitlines():
        if ":" in line:
            key, _, raw = line.partition(":")
            if key.strip().lower() in ("launchargumentindiev2", "launchargumentindie"):
                value = raw.strip()
    if not value:
        return ""
    try:
        level = int(float(value))
    except ValueError:
        return ""
    if level <= 0:
        return "close"
    if level == 1:
        return "mod"
    return "open"          # 2 / 3 / 4 → 都按"隔离"处理(我们只有三态)


def _per_version_isolation(root: str, version_id: str) -> str:
    """读**单版本**隔离标记(优先级最高, 存在即最终答案)。

    顺序(与 PCL2 一致): ``versions\\<id>\\PCL\\Setup.ini`` 里的
    ``VersionArgumentIndieV2``(布尔) > 遗留 ``VersionArgumentIndie``(>0 开 / 2 关)。
    返回 "open"/"close"/""。
    """
    path = os.path.join(str(root), "versions", version_id, "PCL", "Setup.ini")
    if not os.path.isfile(path):
        return ""
    values = {}  # type: Dict[str, str]
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if ":" in line:
                    key, _, value = line.partition(":")
                    values[key.strip().lower()] = value.strip()
    except OSError:
        return ""
    v2 = values.get("versionargumentindiev2", "").strip().lower()
    if v2:
        if v2 in ("true", "1"):
            return "open"
        if v2 in ("false", "0"):
            return "close"
    v1 = values.get("versionargumentindie", "").strip().lower()
    if v1 in ("1", "true"):
        return "open"
    if v1 in ("2", "false"):
        return "close"
    return ""


def _has_version_userdata(root: str, version_id: str) -> bool:
    """版本目录里是否已有用户数据(``mods`` 有文件 或 ``saves`` 有子目录)。

    这是 PCL2 的启发式: 已有 mods/saves 的版本**强制隔离**, 否则那些数据会
    突然"看不见"(存档跑到根目录去了)。
    """
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


def game_dir_for(cfg, root: str, version_id: str, merged: Optional[dict] = None) -> str:
    """算出某个版本的游戏目录(版本隔离规则), 供启动与资源安装共用。

    决策顺序(与 PCL2 对齐, 越靠前优先级越高):
      1. 配置里**显式**写死的 ``launch.isolation``(open/mod/close);
      2. **单版本**标记 ``versions/<id>/PCL/Setup.ini``(存在即最终答案 ——
         PCL2 也是这样, 否则同一个实例两个启动器会给出不同目录);
      3. 迁移兼容: 旧版我们写在版本 json 里的 ``pclpy:isolate``;
      4. 版本目录里已有 ``mods``/``saves``(PCL2 启发式) → 强制隔离;
      5. PCL2 的全局档位 ``LaunchArgumentIndieV2``(0..4);
      6. 我们的兜底: 带 Mod 加载器就隔离;
      7. 都没有 → **关闭**(PCL2 对"有旧配置的升级用户"用的就是旧默认 0=关闭;
         全新用户才是 4=隔离所有 —— 这一步由 migrate_isolation_default() 写死, 见下)。
    """
    vid = str(version_id or "")
    if merged is None:
        try:
            merged = merge_version_json(str(root), vid)
        except Exception:  # noqa: BLE001
            merged = None

    # ⚠️ 顺序很重要: **PCL2 写在版本目录里的单版本标记最权威**,
    # 我们自己的全局默认(launch.isolation)只能在没有单版本标记时兜底。
    # 之前把全局值排在最前面, 结果它把单版本标记整个短路掉了 ——
    # 于是 PCL2 隔离安装的整合包被当成"不隔离", versions/<id>/mods 里的模组
    # 一个都加载不到(实测就是这个问题)。
    isolation = ""
    # 1) 单版本标记(PCL2 的"版本设置 → 版本隔离", 存在即最终答案)
    isolation = _per_version_isolation(str(root), vid)
    # 2) 迁移兼容: 旧版写在 json 里的标记(今后不再写入, 只读)
    if not isolation and isinstance(merged, dict) and merged.get("pclpy:isolate"):
        isolation = "open"
    # 3) 版本目录里已有 mods/saves → 强制隔离
    if not isolation and _has_version_userdata(str(root), vid):
        isolation = "open"
    # 4) 我们自己的全局默认(设置在"启动"页里的那一项)
    if not isolation and cfg is not None:
        value = str(cfg.get("launch.isolation", "") or "").strip().lower()
        isolation = "" if value == "follow" else value
    # 5) PCL2 全局档位 → 6) 我们的兜底
    if not isolation:
        isolation = _pcl_global_isolation(str(root))
    if not isolation:
        isolation = "mod" if is_modded_version(str(root), vid, merged) else "close"

    if isolation == "open" or (isolation == "mod" and is_modded_version(str(root), vid, merged)):
        return os.path.join(str(root), "versions", vid)
    return str(root)


def migrate_isolation_default(cfg, root: str) -> str:
    """首次运行时把隔离档位**写死**进配置(PCL2 的 Decide & Freeze 思路)。

    PCL2 对"已有旧配置的升级用户"用旧默认 0=关闭, 只有全新用户才用 4=隔离所有
    (FormMain.xaml.vb:279-291)。照搬这个语义可以避免升级后原版存档"看似消失"。
    返回最终写入的值。
    """
    if cfg is None:
        return ""
    current = str(cfg.get("launch.isolation", "") or "").strip().lower()
    if current in ("open", "mod", "close"):
        return current
    # 有 PCL2 的全局档位就沿用它的语义
    level = _pcl_global_isolation(str(root))
    value = level if level in ("open", "mod", "close") else "close"
    try:
        cfg.set("launch.isolation", value, autosave=True)
    except Exception:  # noqa: BLE001
        pass
    return value


def loader_support(root: str, merged: dict, classpath: List[str]) -> Tuple[List[str], List[str]]:
    """补上 Forge / NeoForge 加载器需要的 jar / ignoreList / -Dfml.modFolders。

    这类加载器的 json 常常只写引导库:
      * 真正的游戏本体 jar 是 libraries 里的 neoforge-<ver>-client.jar, json 没引用;
      * 加载器本体 neoforge-<ver>-universal.jar 也没引用, 而且只能通过
        -Dfml.modFolders=neoforge=<jar> 提供(这样才会有名为 neoforge 的模块)。
    另外两个 jar 的自动模块名都是 neoforge, 所以 client jar 必须像原版 jar 一样
    写进 -DignoreList, 否则会报 "reads more than one module named neoforge"。

    返回 (追加到 jvm 的参数, 追加到 ignoreList 的文件名)。
    """
    main_class = str(merged.get("mainClass") or "").lower()
    if "bootstraplauncher" not in main_class and "modlauncher" not in main_class:
        return [], []

    directories = []  # type: List[str]
    locator_name = ""
    neo_version = _game_arg_value(merged, "--fml.neoForgeVersion")
    forge_version = _game_arg_value(merged, "--fml.forgeVersion")
    mc_version = _game_arg_value(merged, "--fml.mcVersion")
    libraries = os.path.join(str(root), "libraries")

    if neo_version:
        directories.append(os.path.join(libraries, "net", "neoforged", "neoforge", neo_version))
        locator_name = "neoforge"
    if forge_version:
        folder = "%s-%s" % (mc_version, forge_version) if mc_version else forge_version
        directories.append(os.path.join(libraries, "net", "minecraftforge", "forge", folder))
        locator_name = locator_name or "forge"

    existing = {os.path.normcase(os.path.abspath(p)) for p in classpath}
    universal = ""
    client = ""
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            full = os.path.join(directory, name)
            if name.endswith("-universal.jar"):
                universal = universal or full
            elif name.endswith("-client.jar"):
                client = client or full

    # 说明: 官方安装里 net.neoforged:neoforge:<ver>:client 指向的其实是 NeoForm 的
    # srg 客户端 jar。但这个版本的 json 被启动器改写后**没有**任何加载器库条目,
    # 只能退回 libraries/net/neoforged/neoforge/<ver>/ 里的 <loader>-client.jar,
    # 并用 -DmergeModules 把它和 universal 合并成一个 neoforge 模块。
    # (把 srg jar 直接塞进 classpath 会和 FML 自己建的 minecraft 模块抢
    #  net.minecraft 包, 报 "Module minecraft contains package ...")

    # client(游戏本体, 带 net.minecraft 类)与 universal(加载器本体)都要在 classpath 上:
    # 少了 client 会 ClassNotFoundException: net.minecraft.client.gui.screens.LoadingOverlay。
    # 但两者自动模块名都是 neoforge, 必须用 -DmergeModules 合并成一个模块, 否则报
    # "reads more than one module named neoforge"。
    for full in (client, universal):
        if not full:
            continue
        key = os.path.normcase(os.path.abspath(full))
        if key in existing:
            continue
        existing.add(key)
        classpath.append(full)

    extra_args = []  # type: List[str]
    ignore_names = []  # type: List[str]
    if client and os.environ.get("PCLPY_IGNORE_CLIENT") == "1":
        ignore_names.append(os.path.basename(client))

    # 继承来的版本(inheritsFrom)自带一个原版 jar(如 versions/1.20/1.20.jar),
    # 而加载器 json 里的 ignoreList 只写了 ${version_name}.jar(替换成当前版本 id),
    # 于是原版 jar 没被忽略 → 它自己成为一个模块, 和加载器的 minecraft 模块抢
    # net.minecraft 包, 报 "Modules _1._20 and minecraft export package ..."。
    # 这里把父版本的原版 jar 也加进 ignoreList。
    parent_id = str(merged.get("inheritsFrom") or "").strip()
    if parent_id:
        ignore_names.append("%s.jar" % parent_id)

    # BootStrapLauncher 会用 -DmergeModules 把同一组 jar 合并成一个模块。
    # client 与 universal 的自动模块名都叫 neoforge, 不合并就会报
    # "reads more than one module named neoforge"; 合并后
    # NeoForgeLoadingOverlay 与 net.minecraft 才在同一个模块里。
    # BootStrapLauncher 用 -DmergeModules 把同一组 jar 合并成一个模块。只有加的是
    # <loader>-client.jar 时才需要(它的自动模块名也是 neoforge, 会和 universal 撞名);
    # 用 srg 游戏 jar 时模块名是 client/minecraft, 不能合并。
    if client and universal and os.path.basename(client).endswith("-client.jar"):
        already_merge = any(str(a).startswith("-DmergeModules")
                            for a in (merged.get("arguments") or {}).get("jvm", [])
                            if isinstance(a, str))
        if not already_merge:
            extra_args.append("-DmergeModules=%s,%s" % (os.path.basename(client),
                                                        os.path.basename(universal)))

    if universal and locator_name:
        already = any(str(a).startswith("-Dfml.modFolders")
                      for a in (merged.get("arguments") or {}).get("jvm", [])
                      if isinstance(a, str))
        if not already:
            extra_args.append("-Dfml.modFolders=%s=%s" % (locator_name, universal))
    return extra_args, ignore_names


def uses_bootstrap_launcher(merged: dict) -> bool:
    """是否是 Forge/NeoForge 那种用 BootStrapLauncher 的版本。"""
    main_class = str(merged.get("mainClass") or "").lower()
    return "bootstraplauncher" in main_class


def build_launch(root: str, version_id: str, account, cfg, java_path: Optional[str] = None) -> LaunchPlan:
    """构建启动命令。"""
    root = str(root)
    vid = str(version_id)
    warnings = []  # type: List[str]
    merged = merge_version_json(root, vid)
    if not merged:
        warnings.append("未找到版本 %s 的 JSON 文件" % vid)

    # ---- classpath
    classpath = []  # type: List[str]
    jar_path = os.path.join(root, "versions", vid, vid + ".jar")
    if os.path.isfile(jar_path):
        classpath.append(jar_path)
    else:
        parent_id = str(merged.get("inheritsFrom") or "")
        parent_jar = os.path.join(root, "versions", parent_id, parent_id + ".jar") if parent_id else ""
        if parent_jar and os.path.isfile(parent_jar):
            classpath.append(parent_jar)
        else:
            warnings.append("缺少客户端 jar: %s" % jar_path)
    libraries = merged.get("libraries") if isinstance(merged.get("libraries"), list) else []
    libraries = dedupe_libraries(libraries)
    missing_libs = 0
    for lib in libraries:
        if not isinstance(lib, dict) or not library_allowed(lib):
            continue
        path = library_path(lib)
        if not path:
            continue
        full = os.path.join(root, "libraries", path.replace("/", os.sep))
        if os.path.isfile(full):
            classpath.append(full)
        else:
            missing_libs += 1
    if missing_libs:
        warnings.append("缺少 %d 个依赖库文件" % missing_libs)
    if not classpath:
        warnings.append("没有可用的 classpath 内容")
    # Forge / NeoForge: json 里没写的加载器 jar 从 libraries 补进 classpath,
    # 并生成 -Dfml.modFolders / 追加 ignoreList(必须在拼 classpath 字符串之前做)
    loader_args, loader_ignore = loader_support(root, merged, classpath)
    classpath_str = os.pathsep.join(classpath)

    # ---- gameDir(版本隔离) —— 规则见 game_dir_for()
    game_dir = game_dir_for(cfg, root, vid, merged)
    ensure_dir(game_dir)

    # ---- natives
    natives_dir = os.path.join(root, "versions", vid, "natives")
    ensure_dir(natives_dir)
    for lib in libraries:
        if not isinstance(lib, dict) or not library_allowed(lib):
            continue
        natives = lib.get("natives")
        if not isinstance(natives, dict):
            continue
        key = str(natives.get(_NATIVES_KEY) or "").replace("${arch}", "64" if sys.maxsize > 2 ** 32 else "32")
        if not key:
            continue
        downloads = lib.get("downloads") if isinstance(lib.get("downloads"), dict) else {}
        classifiers = downloads.get("classifiers") if isinstance(downloads, dict) else None
        rel = ""
        if isinstance(classifiers, dict):
            for candidate in (key, key.replace("-", "_"), key.replace("_", "-")):
                artifact = classifiers.get(candidate)
                if isinstance(artifact, dict) and artifact.get("path"):
                    rel = str(artifact["path"])
                    break
        if not rel:
            name = str(lib.get("name") or "")
            parts = name.split(":")
            if len(parts) >= 3:
                rel = library_path({"name": ":".join(parts[:3]) + ":" + key}) or ""
        if not rel:
            continue
        jar = os.path.join(root, "libraries", rel.replace("/", os.sep))
        if os.path.isfile(jar):
            extract = lib.get("extract") if isinstance(lib.get("extract"), dict) else {}
            extract_natives(jar, natives_dir, extract.get("exclude") if isinstance(extract, dict) else None)

    # ---- 资产
    assets_root = os.path.join(root, "assets")
    asset_index = merged.get("assetIndex") if isinstance(merged.get("assetIndex"), dict) else {}
    index_id = str(asset_index.get("id") or merged.get("assets") or "legacy")
    # 游戏会因为 --assetsDir 不存在直接报错退出, 这里先确保目录在
    ensure_dir(assets_root)
    ensure_dir(os.path.join(assets_root, "indexes"))
    ensure_dir(os.path.join(assets_root, "objects"))

    # ---- 内存
    memory_mode = str(cfg.get("launch.memory_mode", "auto") or "auto").strip().lower()
    if memory_mode == "custom":
        memory_mb = max(256, _int_of(cfg.get("launch.memory_mb"), 4096))
        min_mb = max(128, _int_of(cfg.get("launch.min_memory_mb"), 512))
        memory_args = [
            "-Xmx%dM" % memory_mb,
            "-Xmn%dM" % max(128, memory_mb // 4),
            "-Xms%dM" % min_mb,
        ]
    else:
        total_mb = _total_memory_mb()
        xmx = max(512, total_mb // 4)
        memory_args = ["-Xmx%dM" % xmx, "-Xmn%dM" % max(128, xmx // 4)]

    # ---- 账号信息
    account_name = str(getattr(account, "name", "") or "Player")
    account_kind = str(getattr(account, "kind", "offline") or "offline")
    access_token = str(getattr(account, "token", "") or "")
    account_uuid = str(getattr(account, "uuid", "") or "") or offline_uuid(account_name)
    if not access_token:
        access_token = "0" if account_kind == "offline" else ""
    user_type = "msa" if account_kind == "microsoft" else "legacy"

    window_size = cfg.get("window_size", {}) if isinstance(cfg.get("window_size", {}), dict) else {}
    size_mode = str(cfg.get("launch.window_size_mode", "default") or "default").lower()
    if size_mode == "max":
        screen_w, screen_h = screen_size()
        width, height = screen_w, screen_h
    elif size_mode == "custom":
        width = int(window_size.get("w") or 1280)
        height = int(window_size.get("h") or 720)
    else:
        # 「默认」= 游戏自己的默认窗口大小; 用户填过的分辨率只在「自定义」时使用
        width, height = 854, 480
    library_dir = os.path.join(root, "libraries")
    placeholders = {
        "auth_player_name": account_name,
        "auth_uuid": account_uuid,
        "auth_access_token": access_token,
        "auth_session": "token:%s:%s" % (access_token, account_uuid),
        "user_type": user_type,
        "version_name": vid,
        "version_type": str(merged.get("type") or "release"),
        "game_directory": game_dir,
        "assets_root": assets_root,
        "assets_index_name": index_id,
        "resolution_width": str(width),
        "resolution_height": str(height),
        "user_properties": "{}",
        "clientid": "",
        "auth_xuid": "",
        "natives_directory": natives_dir,
        "classpath": classpath_str,
        "launcher_name": "PCLPy",
        "launcher_version": "1.0",
        # Forge / NeoForge 的模块化启动参数需要这两个占位符
        "library_directory": library_dir,
        "classpath_separator": os.pathsep,
        "primary_jar": jar_path if os.path.isfile(jar_path) else "",
        "primary_jar_name": os.path.basename(jar_path) if os.path.isfile(jar_path) else "",
    }

    # ---- jvm 参数
    arguments = merged.get("arguments") if isinstance(merged.get("arguments"), dict) else {}
    log_id = ""
    logging = merged.get("logging")
    if isinstance(logging, dict):
        client_log = logging.get("client")
        if isinstance(client_log, dict):
            file_info = client_log.get("file")
            if isinstance(file_info, dict):
                log_id = str(file_info.get("id") or "")
    if log_id:
        placeholders["path"] = os.path.join(assets_root, "log_configs", log_id)

    jvm_args = []  # type: List[str]
    jvm_args.extend(memory_args)
    jvm_args.append("-Djava.library.path=%s" % natives_dir)
    jvm_args.append("-Dminecraft.launcher.brand=PCLPy")
    jvm_args.append("-Dminecraft.launcher.version=1.0")
    ignore_seen = False
    for item in (arguments.get("jvm") or []):
        for value in _arg_values(item):
            if value == "-cp" or "${classpath}" in value:
                continue
            if value.startswith("-Djava.library.path"):
                continue
            if "${path}" in value and "path" not in placeholders:
                continue
            if value.startswith("-DignoreList="):
                ignore_seen = True
                if loader_ignore:
                    value = value + "," + ",".join(loader_ignore)
            jvm_args.append(value)
    if loader_ignore and not ignore_seen:
        jvm_args.append("-DignoreList=" + ",".join(loader_ignore))
    for extra in _split_args(cfg.get("launch.jvm_args", "")):
        jvm_args.append(extra)
    jvm_args.extend(loader_args)
    if uses_bootstrap_launcher(merged) and classpath_str:
        # Forge/NeoForge: 与官方启动配置一致, 完整 classpath 直接给 -cp
        # (BootstrapLauncher 会按 -DmergeModules 把 client/universal 合并成同一个模块)
        jvm_args.append("-cp")
        jvm_args.append(classpath_str)
    else:
        jvm_args.append("-cp")
        jvm_args.append(classpath_str)

    # ---- 游戏参数
    game_args = []  # type: List[str]
    legacy_args = merged.get("minecraftArguments")
    if isinstance(legacy_args, str) and legacy_args.strip():
        game_args.extend(_split_args(legacy_args))
    else:
        for item in (arguments.get("game") or []):
            game_args.extend(_arg_values(item))
    if "--username" not in game_args and not any("${auth_player_name}" in a for a in game_args):
        game_args = [
            "--username", "${auth_player_name}",
            "--version", "${version_name}",
            "--gameDir", "${game_directory}",
            "--assetsDir", "${assets_root}",
            "--assetIndex", "${assets_index_name}",
            "--uuid", "${auth_uuid}",
            "--accessToken", "${auth_access_token}",
            "--userType", "${user_type}",
            "--versionType", "${version_type}",
        ] + game_args
    if "--assetsDir" not in game_args:
        game_args.extend(["--assetsDir", "${assets_root}", "--assetIndex", "${assets_index_name}"])
    # 现代版本的 json 里没有 --width/--height, 不自己加上「窗口大小」设置就完全不生效
    if "--width" not in game_args:
        game_args.extend(["--width", str(width), "--height", str(height)])
    for extra in _split_args(cfg.get("launch.game_args", "")):
        game_args.append(extra)

    # ---- 窗口标题(只有老版本认 --title; 新版本由启动器改窗口标题, 见 set_window_title)
    title = str(cfg.get("launch.window_title", "") or "").strip()
    custom_info = str(cfg.get("launch.custom_info", "") or "").strip()
    if title and "launchwrapper" in str(merged.get("mainClass") or "").lower():
        game_args.extend(["--title", title])

    def _substitute(value: str) -> str:
        def _repl(match):
            key = match.group(1)
            if key in placeholders:
                return str(placeholders[key])
            return match.group(0)  # 未知占位符保留原样

        try:
            return _PLACEHOLDER_RE.sub(_repl, value)
        except Exception:
            return value

    jvm_args = [_substitute(a) for a in jvm_args]
    game_args = [_substitute(a) for a in game_args]

    # 现代版本(1.19+)的 jvm 参数会把 jna / lwjgl / netty 的临时目录指向 natives 的子目录,
    # 例如 -Djna.tmpdir=${natives_directory}/jna。这些目录不存在时 JNA 会直接
    # UnsatisfiedLinkError 崩溃(现象就是"启动立刻退出"或"进程在但窗口不出"), 必须提前建好。
    for argument in jvm_args:
        if not argument.startswith("-D") or "=" not in argument:
            continue
        value = argument.split("=", 1)[1]
        if not value or "${" in value:
            continue
        try:
            if os.path.isabs(value) and \
                    os.path.normcase(value).startswith(os.path.normcase(natives_dir)):
                ensure_dir(value)
        except Exception:  # noqa: BLE001
            continue

    # ---- Java
    java = ""
    mc_version = str(merged.get("inheritsFrom") or "") or \
        str(parse_version_id(vid).get("mc_version") or vid)
    required_java = required_java_from_json(merged, mc_version)
    if java_path and str(java_path).strip() and str(java_path).strip().lower() != "auto":
        java = str(java_path)
    else:
        configured = str(cfg.get("launch.java_path", "auto") or "auto")
        if configured.strip() and configured.strip().lower() != "auto" and os.path.isfile(configured):
            java = configured
        else:
            try:
                picked, ok = pick_java(find_javas(), required_java)
                java = picked.path
                if not ok:
                    warnings.append(
                        "该版本需要 Java %d, 但系统里没有满足要求的 Java, 已退回 %s(%s)"
                        % (required_java, java, picked.label()))
            except Exception:
                java = ""
        if not java:
            java = "java"
    if java != "java" and not os.path.isfile(java):
        warnings.append("Java 路径不存在: %s" % java)

    main_class = str(merged.get("mainClass") or _DEFAULT_MAIN)
    command = [java] + jvm_args + [main_class] + game_args
    return LaunchPlan(
        command=command,
        cwd=game_dir,
        java=java,
        version_id=vid,
        main_class=main_class,
        warnings=warnings,
    )


def screen_size() -> Tuple[int, int]:
    """主屏幕分辨率(给「窗口大小 = 最大化」用)。取不到就给个常见值。"""
    if os.name == "nt":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            if width > 0 and height > 0:
                return width, height
        except Exception:  # noqa: BLE001
            pass
    return 1280, 720


def process_alive(pid: int) -> bool:
    """进程是否还活着(用来决定还要不要继续盯着游戏窗口标题)。"""
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        import ctypes.wintypes as wt
    except Exception:  # noqa: BLE001
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wt.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == 259                            # STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(handle)


def set_window_title(pid: int, title: str = "", suffix: str = "",
                     timeout: float = 0.0, interval: float = 0.5) -> bool:
    """改游戏窗口标题(Win32 SetWindowTextW)。

    * ``title`` 非空 → 直接把标题设成它(对应设置里的「游戏窗口标题」);
    * ``title`` 为空但 ``suffix`` 非空 → 在游戏自己的标题后面追加 " - 后缀"
      (对应「自定义信息」, 和 PCL2 一致, 例如 "Minecraft 1.20.1 - PCL")。

    现代版本不支持 --title, 而且游戏在加载过程中(实测 1.21.4 约 27 秒时)**会把标题
    改回自己的默认值**, 所以这里默认一直盯着进程: 只要标题被改回去就再设一次,
    直到游戏进程退出(``timeout=0`` 表示跟着进程走)。返回是否至少成功设置过一次。
    """
    if os.name != "nt" or not pid or (not str(title).strip() and not str(suffix).strip()):
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        import time
    except Exception:  # noqa: BLE001
        return False

    title = str(title).strip()
    suffix = str(suffix).strip()
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    deadline = time.time() + float(timeout) if timeout and timeout > 0 else 0.0
    applied = False
    misses = 0
    last_write = 0.0
    # 加载期间游戏自己也会改标题, 与其"对刷"(看起来像标题在跳), 不如限制写入频率
    write_gap = 2.0

    while True:
        if deadline and time.time() > deadline:
            break
        if not process_alive(pid):
            break
        targets = []  # type: List[Tuple[int, str]]

        def _callback(hwnd, _lparam):
            window_pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            if class_name.value == "ConsoleWindowClass":
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value:
                targets.append((hwnd, buffer.value))
            return True

        try:
            user32.EnumWindows(enum_proc(_callback), 0)
        except Exception:  # noqa: BLE001
            return applied
        if targets:
            misses = 0
        else:
            misses += 1
            if misses > 120:      # 连续 60 秒没有窗口, 认为已经关了
                break
        for hwnd, current in targets:
            try:
                if title:
                    wanted = title
                elif current.endswith(suffix):
                    continue
                else:
                    wanted = "%s - %s" % (current, suffix)
                if current == wanted:
                    continue
                now = time.time()
                if now - last_write < write_gap:
                    continue
                user32.SetWindowTextW(hwnd, wanted)
                last_write = now
                applied = True
            except Exception:  # noqa: BLE001
                continue
        time.sleep(max(0.2, float(interval)))
    return applied


def open_output_log(path: str):
    """打开游戏输出日志文件(行缓冲)。失败返回 None。"""
    try:
        ensure_dir(os.path.dirname(os.path.abspath(path)))
        return open(path, "w", encoding="utf-8", errors="ignore", buffering=1)
    except Exception:
        return None


def start_process(plan: LaunchPlan, stdout=None, cwd: Optional[str] = None) -> subprocess.Popen:
    """启动游戏进程。

    ``stdout`` 传文件对象时游戏输出直接写文件(推荐, 管道写满会让游戏卡死);
    传 None 时退回管道(文本模式, 由 ProcessReader 读取)。
    不设置任何隐藏窗口的标志, 游戏窗口才能正常显示。
    """
    kwargs = {
        "cwd": cwd or plan.cwd,
        "stderr": subprocess.STDOUT,
    }  # type: Dict[str, Any]
    if stdout is None:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "ignore"
    else:
        kwargs["stdout"] = stdout
    # 隐藏控制台窗口: 即使配置的是 java.exe(带控制台)也不会闪出 cmd 窗口,
    # 游戏自己的窗口不受影响。
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.Popen(plan.command, **kwargs)
