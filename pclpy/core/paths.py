"""路径与文件系统工具: 应用目录、系统目录、大小格式化、资源管理器打开。

本模块只依赖标准库, 导入时不会创建任何目录, 所有写盘操作失败都静默降级(不抛异常)。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Union

# 应用根目录: 环境变量 PCLPY_HOME 优先, 否则 ~/.pclpy。
# 注意: 导入时不创建目录。
APP_HOME = Path(os.environ.get("PCLPY_HOME") or os.path.join(os.path.expanduser("~"), ".pclpy"))

# Windows 文件名非法字符
_ILLEGAL_CHARS = '<>:"/\\|?*'


def app_home() -> Path:
    """返回应用根目录(每次调用都重新读取环境变量, 便于测试切换)。"""
    env = os.environ.get("PCLPY_HOME")
    if env:
        try:
            return Path(env)
        except Exception:
            return APP_HOME
    return APP_HOME


def ensure_dir(path: Union[str, Path]) -> Path:
    """创建目录(含父级)并返回 Path; 失败也不抛异常, 返回原 Path。"""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def assets_dir() -> Path:
    """资产/游戏数据目录: <APP_HOME>/assets。"""
    return app_home() / "assets"


def cache_dir() -> Path:
    """缓存目录: <APP_HOME>/cache。"""
    return app_home() / "cache"


def downloads_dir() -> Path:
    """下载目录: <APP_HOME>/downloads。"""
    return app_home() / "downloads"


def ensure_app_dirs() -> None:
    """一次性创建应用所需的基础目录, 失败静默忽略。"""
    for d in (app_home(), assets_dir(), cache_dir(), downloads_dir()):
        ensure_dir(d)


def bundled_data_path(name: str) -> str:
    """返回包内数据文件 <pclpy>/data/<name> 的绝对路径。"""
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg_dir, "data", str(name))


def official_minecraft_dir() -> str:
    """官方启动器的游戏目录: %APPDATA%\\.minecraft, 取不到则用 ~/.minecraft。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, ".minecraft")
    return os.path.join(os.path.expanduser("~"), ".minecraft")


def desktop_dir() -> str:
    """桌面目录。"""
    profile = os.environ.get("USERPROFILE")
    if profile:
        d = os.path.join(profile, "Desktop")
        if os.path.isdir(d):
            return d
    for key in ("OneDrive", "OneDriveConsumer"):
        od = os.environ.get(key)
        if od:
            d = os.path.join(od, "Desktop")
            if os.path.isdir(d):
                return d
    home = os.path.expanduser("~")
    for name in ("Desktop", "桌面"):
        d = os.path.join(home, name)
        if os.path.isdir(d):
            return d
    return os.path.join(home, "Desktop")


def human_size(num_bytes) -> str:
    """把字节数格式化成人读字符串, 例如 "1.2 MB"、"832 KB"、"1.4 GB"。

    小于 1KB 时显示 "x B"; 其余保留 1 位小数(整数则省略 .0)。
    """
    try:
        size = float(num_bytes)
    except Exception:
        return "0 B"
    if size != size or size <= 0:  # NaN 或非正数
        return "0 B"
    if size < 1024:
        return "%d B" % int(size)
    units = ["KB", "MB", "GB", "TB", "PB"]
    value = size / 1024.0
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    text = "%.1f" % value
    if text.endswith(".0"):
        text = text[:-2]
    return "%s %s" % (text, units[idx])


def open_in_explorer(path: str) -> bool:
    """在系统文件管理器中打开路径, 成功返回 True(失败返回 False, 不抛异常)。"""
    try:
        if not path:
            return False
        target = str(path)
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
            return True
        subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False


def launcher_dir() -> str:
    """启动器自身所在目录。

    * 打包成 exe 之后: exe 所在目录
    * 源码运行: 项目根目录(即 main.py 所在目录)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))          # pclpy/core
    return os.path.dirname(os.path.dirname(here))              # 项目根


# 社区资源在启动器目录下的存放文件夹(名字固定, 方便用户找)
DOWNLOAD_FOLDERS = {
    "mod": "Mods",
    "modpack": "ModPacks",
    "resourcepack": "ResourcePacks",
    "shader": "ShaderPacks",
    "datapack": "DataPacks",
}


def download_dir(kind: str = "") -> str:
    """社区资源下载目录: ``<启动器目录>/Download/<类型>``。

    未知类型(或空、或本来就叫 "Download"/"下载")时直接返回 ``Download`` 根,
    否则会生成 ``Download/Download/...`` 这种套娃目录(踩过这个坑)。
    """
    base = os.path.join(launcher_dir(), "Download")
    key = str(kind or "").strip().lower()
    if not key or key in ("download", "下载", "all", "全部"):
        ensure_dir(base)
        return base
    name = DOWNLOAD_FOLDERS.get(key, str(kind or "").strip())
    # 再兜一层: 子目录名不能为空, 也不能和 Download 本身同名
    if name and name.lower() != os.path.basename(base).lower():
        base = os.path.join(base, name)
    ensure_dir(base)
    return base


def safe_name(name: str) -> str:
    """去掉 Windows 文件名非法字符, 并清理首尾空白/结尾的点。"""
    raw = str(name or "")
    cleaned = []
    for ch in raw:
        if ch in _ILLEGAL_CHARS or ord(ch) < 32:
            continue
        cleaned.append(ch)
    out = "".join(cleaned).strip().rstrip(". ")
    return out or "unnamed"


# 第一个参数是文本的回调命名(兼容层用)
_TEXT_FIRST_NAMES = ("text", "msg", "message", "title", "label", "info", "desc", "description")


def adapt_progress_callback(callback):
    """兼容两种进度回调参数顺序: (percent, text) 与 (text, percent)。

    核心层统一使用 progress_cb(percent, text); 如果传入的可调用对象第一个参数
    名是 text/message 之类(Qt 后端常见的 report(text, percent) 写法), 这里会自动
    交换参数顺序, 避免进度回调因为参数错位而失效。
    """
    if callback is None:
        return None
    try:
        code = getattr(callback, "__code__", None)
        if code is None:
            code = getattr(getattr(callback, "__func__", None), "__code__", None)
        if code is None:
            return callback
        names = list(code.co_varnames[:code.co_argcount])
        if names and names[0] in ("self", "cls"):
            names = names[1:]
        if names and str(names[0]).lower() in _TEXT_FIRST_NAMES:
            def _swapped(percent, text):
                return callback(text, percent)

            return _swapped
    except Exception:
        pass
    return callback
