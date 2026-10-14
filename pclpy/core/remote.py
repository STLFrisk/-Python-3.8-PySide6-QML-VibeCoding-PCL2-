"""网络访问层: 官方/镜像地址表、JSON 请求、流式下载、版本清单缓存。

所有网络函数都不会抛异常: 失败返回 None / False, 由上层决定回退策略。
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import catalog as catalog_mod
from . import config as config_mod
from .paths import cache_dir, ensure_dir

USER_AGENT = "PCLPy/1.0"

# 官方地址表
OFFICIAL = {
    "manifest": "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
    "version": "https://piston-meta.mojang.com",
    "assets": "https://resources.download.minecraft.net",
    "launcher": "https://launcher.mojang.com",
    "fabric": "https://meta.fabricmc.net",
    "quilt": "https://meta.quiltmc.org",
    "forge": "https://maven.minecraftforge.net",
    "neoforge": "https://maven.neoforged.net/releases",
    "modrinth": "https://api.modrinth.com/v2",
    "curseforge": "https://api.curseforge.com/v1",
}

# 镜像地址表(BMCLAPI)
MIRROR = {
    "manifest": "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
    "version": "https://bmclapi2.bangbang93.com",
    "assets": "https://bmclapi2.bangbang93.com/assets",
    "launcher": "https://bmclapi2.bangbang93.com",
    "fabric": "https://bmclapi2.bangbang93.com/fabric-meta",
    "quilt": "https://meta.quiltmc.org",
    "forge": "https://bmclapi2.bangbang93.com/maven",
    "neoforge": "https://maven.neoforged.net/releases",
    "modrinth": "https://api.modrinth.com/v2",
    "curseforge": "https://api.curseforge.com/v1",
}

# 下载源别名
_MIRROR_ALIASES = ("mirror", "bmcl", "bmclapi", "bmclapi2", "china", "cn")

# 清单缓存有效期(秒)
MANIFEST_TTL = 3600

_CHUNK = 64 * 1024

# Range 探测只取这么多字节: 探测的唯一目的是"读出总长度 + 确认服务端支持 Range",
# 绝不能把正文读进来。以前发的是 ``Range: bytes=0-``(= 请求整个文件), 服务端会开始
# 推整份文件, 只能靠 reset 打断 —— 改发 ``bytes=0-1`` 后探测的正文开销恒为 2 字节。
PROBE_PREFIX = 2

# ================================================================ 多连接分片下载
# 规格来自本项目 PCL2_ANALYSIS.md 对 PCL2 ModNet.vb 的实测分析(行号即该文件):
#   * 单文件按 HTTP Range 分段并发; 在"剩余量最大且 ≥256KB"的段上切走 40%  → ModNet.vb:857-862
#   * 文件大小未知, 或 FileSize < 1MB → 不分片                              → ModNet.vb:674-678
#   * bmclapi / github / optifine.net / momot.rs / pcl2-server / meloong
#     禁用多线程(大小写不敏感的子串匹配)                                   → ModNet.vb:853-854
#   * 416(不支持 Range)/502/403/429/合并后校验失败 → 禁用该源                → ModNet.vb:1079-1099
#   * 所有可多线程的源都废掉 → 全部源降级为单线程重试一次                    → ModNet.vb:1105-1120
#   * 失败回滚已计字节, 进度不许虚高                                        → ModNet.vb:1147-1156
#   * 只有**全局速度低于下限**才给进行中的文件加线程                          → ModNet.vb:1747
#
# ---- 为什么这几个默认值被调大(用户 A/B 实测: 无分片版比有分片版更慢) ----
# 实测结论: 上游 CDN 对**单条连接**限速, 单连接吞吐有天花板; 总吞吐 ≈ 连接数 ×
# 单连接上限。分片不是元凶, 反而在帮忙。所以三件事一起调高: 分片阈值 4MB→1MB
# (0.5-5MB 的 mod 也能分片)、单文件段数上限 4→8、全局 Range 连接预算 16→32。
# 自适应加段保留(见 MULTI_START_SEGMENTS / MULTI_LOW_SPEED_BPS 与 _expand):
# 起步只开一半段数, 实测慢才一段一段加, 不是一开下就拉满。
MULTI_MIN_SIZE = 1 * 1024 * 1024      # 1MB: mod 多为 0.5-5MB, 降到 1MB 让中等文件也能分片
MULTI_MIN_SEGMENT = 256 * 1024        # 256KB: 段的剩余量不足它就不再切
MULTI_SPLIT_RATIO = 0.40              # 切走最大段剩余量的 40%
# 单文件段数上限 8(起步 4, 见下): 每个线程就是一条阻塞 TCP 连接, 上限放宽到 8。
MULTI_MAX_SEGMENTS = 8
# 低速才加线程: 起步只开 4 段(上限的一半), 只有**实测总吞吐低于
# MULTI_LOW_SPEED_BPS 且连续 MULTI_LOW_SPEED_SAMPLES 次**才加一段。
# ⚠️ 光有"低了就加"是不够的 —— 慢连接会永远低于阈值, 于是无限加/回滚/空转
# (用户实测: 单连接被上游限到 ~1MB/s 时界面"未响应")。真正的刹车片见下面
# 的 MULTI_EXPAND_* 常量(冷却 / 看疗效 / 总次数上限)。
MULTI_START_SEGMENTS = 4
MULTI_LOW_SPEED_BPS = 1024 * 1024     # 1MB/s: 低于它才值得加连接
MULTI_LOW_SPEED_SAMPLES = 2           # 连续 2 次(≈1 秒)都低于下限才加, 防抖
MULTI_SPEED_SAMPLE_INTERVAL = 0.5     # 测速采样间隔(秒)
# 全局连接预算: 整个进程内同时进行的 Range 连接数上限。这是**唯一**能真正压住
# 并发的开关 —— 调用方想开多少线程都行, 超出预算的请求在信号量上排队。
# 32 = 整合包的 8 文件并行 × 单文件起步 4 段; 单文件涨到 8 段也只是排队, 不会超发。
MULTI_MAX_CONNECTIONS = 32
MULTI_SEGMENT_RESUMES = 2             # 单段"原地续传"次数(超过就回滚本段重下)
# 单段在一个"续传-回滚"周期内的请求次数硬上限(防死循环)。别调太小: 并发连接多、
# 服务端限速时, 短读/连接重置是常态, 每次读空都算一次尝试 —— 以前上限 6, 一次
# 拥塞就会把整段判死, 整份文件退回单流**从 0 重下**(本地实测多花 12-33% 字节)。
MULTI_SEGMENT_ATTEMPTS = 12
MULTI_RETRY_BACKOFF = 0.2             # 失败后的退避上限(秒), 逐次翻倍封顶
MULTI_SEGMENT_ACQUIRE_TIMEOUT = 120.0  # 等全局连接预算的最长时间(秒), 防死锁
PROGRESS_MIN_INTERVAL = 0.05          # 进度回调最小间隔(秒), 首次/完成时强制回调
MULTIPART_BLOCKED_TOKENS = ("bmclapi", "github", "optifine.net", "momot.rs",
                            "pcl2-server", "meloong")

# ---------------------------------------------------------------- 加段迟滞(关键)
# 下面 5 个常量全是"别再无限追"的刹车片。它们修的是一个实测到的**活锁**:
#   ① 段被自适应扩容切走尾巴时只置位 ``abort``, 而 ``_pipe_range`` 一进门就检查
#      ``abort`` 直接返回 0 字节 —— 于是被切的那条连接**再也没法重开**, worker 在
#      ``_segment_worker`` 的 while 里 0 字节空转(本机实测 840292 次 _pipe_range /
#      14 秒, 3 条空转线程), 直到 attempts 用尽整段判死 → 整份文件回退单流重下。
#   ② 加的段对吞吐毫无帮助时仍然一秒一次地继续加, 段越切越碎, 线程/连接反复建销。
# 现在: 切段改成"一次性的 abandon 标记 + 重连"(见 _PipeAbandon), 加段改成
# "冷却 + 看疗效 + 总次数上限 + 段不能再小就停"。
MULTI_POOL_SIZE = 8                    # 单文件分片工作线程池大小(段在池里排队, 线程复用)
MULTI_EXPAND_COOLDOWN = 3.0            # 两次加段之间至少隔这么久(秒), 防抖
MULTI_EXPAND_MIN_GAIN = 1.2            # 加了段之后本文件吞吐至少要到加段前的 1.2 倍才算有收益
MULTI_EXPAND_NO_GAIN = 2               # 连续几次"加了没收益"就彻底不再加段
MULTI_EXPAND_MAX = 3                   # 单文件整个生命周期内最多加几次段(硬上限, 绝不无限追)
MULTI_ZERO_BYTE_LIMIT = 12             # 同一段连续这么多次"0 字节且无异常"就判死该段

# 设了 PCLPY_DEBUG_DOWNLOAD 就打印分段/回滚账本(ASCII 标签, 便于证据留档)
DEBUG_ENV = "PCLPY_DEBUG_DOWNLOAD"
# 逃生开关/调参口(全部可选, 不设就用上面的默认值):
#   PCLPY_DOWNLOAD_SEGMENTS=0   → 彻底关掉分片, 所有下载回到单流(救命用)
#   PCLPY_DOWNLOAD_SEGMENTS=N   → 单文件段数上限 = N (1 等价于单流)
#   PCLPY_DOWNLOAD_CONNS=N      → 全局 Range 连接预算 = N (0 = 不限制)
#   PCLPY_DOWNLOAD_MIN_MB=N     → 分片阈值 = N MB (0 = 只要支持 Range 就切)
#   PCLPY_DOWNLOAD_START_SEGMENTS=N → 单文件**起步**段数(自适应加段的起点, 默认 4)
#   PCLPY_DOWNLOAD_SLOW_KBPS=N  → "低速阈值" KB/s(低于它才加连接, 默认 1024)
SEGMENTS_ENV = "PCLPY_DOWNLOAD_SEGMENTS"
CONNS_ENV = "PCLPY_DOWNLOAD_CONNS"
MIN_MB_ENV = "PCLPY_DOWNLOAD_MIN_MB"
START_SEGMENTS_ENV = "PCLPY_DOWNLOAD_START_SEGMENTS"
SLOW_KBPS_ENV = "PCLPY_DOWNLOAD_SLOW_KBPS"

# ---------------------------------------------------------------- 生效值来源
# 每个开关的取值顺序(优先级从高到低):
#   1. 环境变量(上面的 *_ENV)  —— 逃生/分发/测试用, 设了就一定赢;
#   2. 设置项(键名见下)        —— 设置 → 其他 → 调试选项 → 下载分片调参;
#   3. 本文件顶部的代码默认值     —— 谁都读不到时兜底。
# 每次下载开始前都重读一遍(配置是单例, 读起来就是一次 dict 查找), 所以用户在
# 界面上改完,**下一次下载**就生效, 不需要重启进程。
#
# 默认值同时被设置页引用: qml/pages/settings/OtherSettings.qml 里
#   downloadSegmentDefault()/downloadTuningDefault() 的字面量与这里的
#   MULTI_MAX_SEGMENTS / MULTI_START_SEGMENTS / MULTI_MAX_CONNECTIONS /
#   MULTI_MIN_SIZE / MULTI_LOW_SPEED_BPS **以及** pclpy/core/config.py 的
#   DEFAULTS["download"] 三处必须一致, 改默认值要三处一起改。
#
# 设置项键名与代码默认值的对照:
#   download.segments_enabled (默认 True)  → 总开关; False 等价于段数上限 1(单流)
#   download.segments_max     (默认 MULTI_MAX_SEGMENTS = 8)     → 每文件段数上限
#   download.segments_start   (默认 MULTI_START_SEGMENTS = 4)   → 起步段数
#   download.connections      (默认 MULTI_MAX_CONNECTIONS = 32) → 全局 Range 连接预算
#   download.min_size_mb      (默认 MULTI_MIN_SIZE//1MB = 1)    → 分片阈值(MB)
#   download.slow_kbps        (默认 MULTI_LOW_SPEED_BPS//1KB = 1024) → 低速阈值(KB/s)
#   download.debug_log        (默认 False)  → 等价于 PCLPY_DEBUG_DOWNLOAD=1
# 界面/后端可写区间(与设置页的范围校验一致; 设置项被手改成 0/负数/超范围时,
# 这里会安全回落到默认值, 下载层绝不会拿到 0 或负数):
SEGMENTS_ENABLED_KEY = "download.segments_enabled"
SEGMENTS_MAX_KEY = "download.segments_max"
SEGMENTS_START_KEY = "download.segments_start"
CONNS_KEY = "download.connections"
MIN_MB_KEY = "download.min_size_mb"
SLOW_KBPS_KEY = "download.slow_kbps"
DEBUG_KEY = "download.debug_log"

SEGMENTS_MAX_RANGE = (1, 64)
SEGMENTS_START_RANGE = (1, 64)
CONNS_RANGE = (1, 256)
MIN_MB_RANGE = (0, 1024)
SLOW_KBPS_RANGE = (0, 1048576)


def _clamp(value: int, low: int, high: int, fallback: int) -> int:
    """把设置项夹到 ``[low, high]``; 读不出/越界时用 ``fallback``(代码默认值)。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    if number < low or number > high:
        return int(fallback)
    return number


def _setting(name: str, default, cast=None):
    """读一个设置项; 拿不到主配置(纯库调用/单测)或读失败时返回 ``default``。"""
    cfg = config_mod.current()
    if cfg is None:
        return default
    try:
        value = cfg.get(name, None)
    except Exception:  # noqa: BLE001
        return default
    if value is None or value == "" or isinstance(value, (dict, list)):
        return default
    if cast is None:
        return value
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _segments_enabled() -> bool:
    """设置项里的分片总开关(默认开); 环境变量不受它影响。"""
    return bool(_setting(SEGMENTS_ENABLED_KEY, True))


def _env_override(name: str, default: int, mul: int = 1) -> int:
    """环境变量是否覆盖了该项; 覆盖了就返回换算后的值, 没设返回 -1。

    ``0`` 是合法取值(逃生开关/不限制), 所以"没设"用 ``-1`` 表示。
    """
    if name in os.environ:
        return _env_int(name, default) * mul
    return -1


def download_tuning() -> dict:
    """当前**实际生效**的下载/分片参数(每次下载前读一次)。

    给后端只读属性 ``SettingsBackend.downloadTuning`` 与界面上的"当前实际生效值"
    那行用; 返回值里的 ``source`` 说明这一组值是被谁定下来的。
    """
    from_env = [name for name in (SEGMENTS_ENV, START_SEGMENTS_ENV, CONNS_ENV,
                                  MIN_MB_ENV, SLOW_KBPS_ENV, DEBUG_ENV)
                if name in os.environ]
    enabled = _segments_enabled()
    max_segments = multi_max_segments()
    return {
        "enabled": enabled and max_segments > 1,
        "max_segments": max_segments,
        "start_segments": max(1, min(multi_start_segments(), max(1, max_segments))),
        "connections": multi_max_connections(),
        "min_size_mb": multi_min_size() // (1024 * 1024),
        "slow_kbps": multi_low_speed_bps() // 1024,
        "debug": debug_enabled(),
        "env": sorted(from_env),
    }


def _env_int(name: str, default: int) -> int:
    """读一个整数环境变量(没设/读不出/负数 → 用默认值)。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        value = int(str(raw).strip())
    except Exception:
        return int(default)
    return value if value >= 0 else int(default)


def multi_min_size() -> int:
    """当前生效的分片阈值(字节); 0 表示"只要服务端支持 Range 就切"。

    优先级: 环境变量 > 设置项 ``download.min_size_mb`` > 代码默认值。
    """
    env = _env_override(MIN_MB_ENV, MULTI_MIN_SIZE // (1024 * 1024), 1024 * 1024)
    if env >= 0:
        return env
    if not _segments_enabled():
        return 0
    return _clamp(_setting(MIN_MB_KEY, MULTI_MIN_SIZE // (1024 * 1024)),
                  MIN_MB_RANGE[0], MIN_MB_RANGE[1],
                  MULTI_MIN_SIZE // (1024 * 1024)) * 1024 * 1024


def multi_max_segments() -> int:
    """当前生效的单文件段数上限; ≤1 表示单流(逃生开关的落点)。

    优先级: 环境变量 > 设置项 ``download.segments_max`` > 代码默认值;
    设置项里的分片总开关 ``download.segments_enabled`` 关掉时返回 1(单流)。
    """
    env = _env_override(SEGMENTS_ENV, MULTI_MAX_SEGMENTS)
    if env >= 0:
        return env
    if not _segments_enabled():
        return 1
    return _clamp(_setting(SEGMENTS_MAX_KEY, MULTI_MAX_SEGMENTS),
                  SEGMENTS_MAX_RANGE[0], SEGMENTS_MAX_RANGE[1], MULTI_MAX_SEGMENTS)


def multi_max_connections() -> int:
    """当前生效的全局 Range 连接预算; 0 表示不限制。

    优先级: 环境变量 > 设置项 ``download.connections`` > 代码默认值。
    """
    env = _env_override(CONNS_ENV, MULTI_MAX_CONNECTIONS)
    if env >= 0:
        return env
    return _clamp(_setting(CONNS_KEY, MULTI_MAX_CONNECTIONS),
                  CONNS_RANGE[0], CONNS_RANGE[1], MULTI_MAX_CONNECTIONS)


def multi_start_segments() -> int:
    """当前生效的单文件**起步**段数(自适应加段的起点); ≤1 表示起步就是单流。

    优先级: 环境变量 > 设置项 ``download.segments_start`` > 代码默认值。
    """
    env = _env_override(START_SEGMENTS_ENV, MULTI_START_SEGMENTS)
    if env >= 0:
        return env
    if not _segments_enabled():
        return 1
    return _clamp(_setting(SEGMENTS_START_KEY, MULTI_START_SEGMENTS),
                  SEGMENTS_START_RANGE[0], SEGMENTS_START_RANGE[1],
                  MULTI_START_SEGMENTS)


def multi_low_speed_bps() -> int:
    """当前生效的"低速阈值"(字节/秒): 文件总吞吐低于它才值得再加一条连接。

    优先级: 环境变量 > 设置项 ``download.slow_kbps`` > 代码默认值。
    """
    env = _env_override(SLOW_KBPS_ENV, MULTI_LOW_SPEED_BPS // 1024, 1024)
    if env >= 0:
        return env
    return _clamp(_setting(SLOW_KBPS_KEY, MULTI_LOW_SPEED_BPS // 1024),
                  SLOW_KBPS_RANGE[0], SLOW_KBPS_RANGE[1],
                  MULTI_LOW_SPEED_BPS // 1024) * 1024


class _NoGate(object):
    """连接预算的"放行一切"实现(预算=0 时用它, 不做任何记账)。"""

    def acquire(self, timeout: Optional[float] = None) -> bool:
        return True

    def release(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


_NO_GATE = _NoGate()


class _RangeGate(object):
    """全局 Range 连接预算(信号量)。

    调用方(整合包是 8 文件并发)可能一下子想开几十条连接, 这里把它们挡在预算内。
    ``acquire`` 带超时: 万一线程被打断/回收异常, 也不会把整批下载永久卡死。
    """

    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self._sem = threading.BoundedSemaphore(self.limit)

    def acquire(self, timeout: Optional[float] = None) -> bool:
        if timeout is None:
            timeout = MULTI_SEGMENT_ACQUIRE_TIMEOUT
        return bool(self._sem.acquire(timeout=float(timeout)))

    def release(self) -> None:
        try:
            self._sem.release()
        except Exception:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.release()
        return False


_GATE_LOCK = threading.Lock()
_GATE_LIMIT = None      # type: Optional[int]
_GATE = None            # type: Optional[_RangeGate]


def _range_gate():
    """取当前生效的全局连接预算(按需重建: 调小预算在下一个下载就生效)。"""
    global _GATE, _GATE_LIMIT
    limit = multi_max_connections()
    if limit <= 0:
        return _NO_GATE
    with _GATE_LOCK:
        if _GATE is None or _GATE_LIMIT != limit:
            _GATE = _RangeGate(limit)
            _GATE_LIMIT = limit
        return _GATE


def debug_enabled() -> bool:
    """下载层调试日志是否打开。

    优先级: 环境变量 ``PCLPY_DEBUG_DOWNLOAD``(**非空**即开) >
    设置项 ``download.debug_log`` > 代码默认(关)。
    """
    raw = os.environ.get(DEBUG_ENV)
    if raw is not None:
        return str(raw).strip() not in ("", "0")
    return bool(_setting(DEBUG_KEY, False))


# 调试日志的两道刹车(旧版实测一次下载写出 97.9MB / 111 万行, 磁盘 + GIL 全被吃死):
#   ① 同类事件每个 key 每秒最多一条(``_DBG_MIN_INTERVAL``), 被压掉多少条会汇总补一句;
#   ② 只保留 ASCII 标签, 输出行数因此与"事件种类 × 持续秒数"成正比, 与重试次数无关。
_DBG_MIN_INTERVAL = 1.0
_DBG_LOCK = threading.Lock()
_DBG_LAST = {}      # type: Dict[str, float]
_DBG_DROPPED = {}   # type: Dict[str, int]


def _dbg_key(text: str) -> str:
    """给一条调试行算"同类 key": 取到第一个空格/等号为止的标签部分。"""
    head = str(text or "").strip()
    for cut in (" ", "="):
        index = head.find(cut)
        if index > 0:
            head = head[:index]
    return head[:32]


def _dbg(fmt: str, *args) -> None:
    """下载层调试输出(默认关闭), 只用 ASCII 标签, 不会被 GBK 控制台吃掉。

    开关每次调用都重新判一次 → 界面上勾上"下载调试日志"后立刻开始输出。
    输出**按事件类别每秒最多一条**: 下载循环里的重复事件(例如同一段反复收缩)
    以前会一行一行刷爆 stderr(实测百万行), 现在是"每秒一条 + 期间被压掉的条数"。
    """
    if not debug_enabled():
        return
    try:
        text = str(fmt % args if args else fmt)
        key = _dbg_key(text)
        now = time.monotonic()
        extra = 0
        with _DBG_LOCK:
            last = _DBG_LAST.get(key)
            if last is not None and (now - last) < _DBG_MIN_INTERVAL:
                _DBG_DROPPED[key] = _DBG_DROPPED.get(key, 0) + 1
                return
            extra = _DBG_DROPPED.pop(key, 0)
            _DBG_LAST[key] = now
        if extra:
            text = "%s (suppressed %d in last %.0fs)" % (text, extra, _DBG_MIN_INTERVAL)
        sys.stderr.write("[multipart] " + text + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _is_mirror(source) -> bool:
    """判断下载源是否为镜像。"""
    return str(source or "").strip().lower() in _MIRROR_ALIASES


def endpoint(name: str, source: str = "official") -> str:
    """取某个功能的基地址(未知名字回退官方表)。"""
    table = MIRROR if _is_mirror(source) else OFFICIAL
    value = table.get(str(name))
    if value is None:
        value = OFFICIAL.get(str(name), "")
    return value or ""


def rewrite_url(url: str, source: str) -> str:
    """把官方域名替换成镜像域名; 不认识的 url 原样返回。"""
    text = str(url or "")
    if not text or not _is_mirror(source):
        return text
    pairs = [
        ("https://piston-meta.mojang.com", MIRROR["version"]),
        ("http://piston-meta.mojang.com", MIRROR["version"]),
        ("https://launchermeta.mojang.com", MIRROR["version"]),
        ("https://launcher.mojang.com", MIRROR["launcher"]),
        ("https://resources.download.minecraft.net", MIRROR["assets"]),
        ("https://libraries.minecraft.net", MIRROR["launcher"] + "/maven"),
        ("https://meta.fabricmc.net", MIRROR["fabric"]),
    ]
    for old, new in pairs:
        if text.startswith(old):
            return new + text[len(old):]
    return text


def _request(url: str, timeout: int = 15, headers: Optional[dict] = None,
             method: Optional[str] = None) -> urllib.request.Request:
    """构造带 User-Agent 的请求对象(可选附加头/方法; timeout 由调用方传给 urlopen)。

    **永远带 ``Connection: close``**: 本项目从不用 ``HTTPConnection`` 连接池,
    每条连接都是当前线程自己 ``urlopen`` 出来的。但 HTTP/1.1 默认 keep-alive, 万一
    服务端/中间盒在"响应读完"和"我们关连接"之间复用了那条 socket, 就会看到
    ``[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC]`` 这类"TLS 记录被污染"的错误
    (表现为同一个错连刷 12 次重试)。显式要求服务端关连接, 从协议层杜绝复用。
    该头由调用方 ``headers`` 覆盖时以调用方为准。
    """
    merged = {"User-Agent": USER_AGENT, "Connection": "close"}
    if headers:
        for key, value in dict(headers).items():
            merged[str(key)] = str(value)
    return urllib.request.Request(str(url), headers=merged, method=method)


def http_json(url: str, timeout: int = 15) -> Optional[dict]:
    """GET 一个 JSON 接口, 失败(含无网络)返回 None。"""
    text = str(url or "")
    if not text:
        return None
    try:
        with urllib.request.urlopen(_request(text, timeout), timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace"))
        return data if isinstance(data, (dict, list)) else None
    except Exception:
        return None


def _silent_remove(path: str) -> None:
    """删除临时文件, 失败忽略。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
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


class _Cancelled(Exception):
    """内部取消信号。"""


class _NoRange(Exception):
    """服务端不认 Range(返回非 206 / 416 等): 多线程这条路作废。"""


class _MultiFailed(Exception):
    """分片下载失败: 回滚账本后降级为单流(等价 PCL2 的"禁用该源")。"""

    def __init__(self, reason: str = ""):
        Exception.__init__(self, str(reason))
        self.reason = str(reason)


class _Segment(object):
    """一个 [start, end) 区间 + 只存在**内存**里的已下载量账本。

    ``end`` 会因为"自适应扩容"被**改小**(把尾巴切给新线程), 所以它不再是只读的。
    切段和写盘必须**互斥**: 扩容线程改 ``end`` 时, 旧连接可能正好在 seek/write 一个
    已经越过新段尾的 64KB 块 —— 那一块会被写进 .part, 而拿到这段尾巴的新线程又会写
    一遍, 于是 ``sum(seg.written)`` 比文件还大(实测 MULTIPART INCOMPLETE
    written=4232577/4194304)。所以两件事都进 ``lock``: sink 的"检查段尾 + 写"和
    :meth:`shrink` 的"标记收手 + 改段尾"。
    """

    __slots__ = ("start", "end", "written", "abort", "last_byte", "thread", "abandon",
                 "lock")

    def __init__(self, start: int, end: int):
        self.start = int(start)
        self.end = int(end)
        self.written = 0
        self.abort = threading.Event()
        self.last_byte = time.monotonic()      # 最近一次真的收到字节的时刻(测速用)
        self.thread = None                      # type: Optional[threading.Thread]
        self.abandon = None                     # type: Optional[_PipeAbandon]
        self.lock = threading.Lock()

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def remaining(self) -> int:
        return self.end - self.start - self.written

    def write_at(self, pos: int, data, write) -> int:
        """把 ``data`` 写到 ``pos``; 返回**实际写进去的字节数**。

        返回 ``-1``: ``pos`` 已经到/过了段尾, 这块完全不属于本段(调用方应收手)。
        块尾越过段尾时**截断到段尾**(见下面注释), 返回截断后的字节数。
        ``write`` 是真正落盘的调用(内部还得拿文件锁), 只在真有数据要写时被调用。
        """
        with self.lock:
            limit = self.end - pos
            if limit <= 0:
                return -1
            if limit < len(data):
                # **跨段尾的块必须截断**: 一颗 64KB 的块可能正好骑在"刚被切小的段尾"上,
                # 整块写下去就会把属于新段的字节也写进本段账本(实测比文件多出 37KB,
                # 于是整份 MULTIPART INCOMPLETE 作废重下)。切断点之后的部分留给新段。
                data = data[:limit]
            write(data)
            self.written += len(data)
            return len(data)

    def split_tail(self, take: int):
        """在**段锁里**把"还没下的尾巴"切出去, 返回 ``(marker, cut)``; 切不动时返回
        ``(None, 0)``。``cut`` 是尾巴的新起点(新段用 ``_Segment(cut, 原 end)`` 建)。

        这是整个自适应扩容里唯一必须原子的一步。原因: 连接的下一颗 64KB 块可能已经开始
        读了, 它的起写位置 = ``start + written``。如果 ``cut``(= ``end - take``)比这个
        位置还靠前, 那颗块就会**跨过** ``cut`` 被写进来一次, 而拿到尾巴的新段又下了一遍
        → 本段账本比文件大(实测 MULTIPART INCOMPLETE written=4232052/4194304)。
        所以 ``cut`` 必须 ≥ 下一颗块的起写位置, 并且"算 cut + 改 end"在同一把锁里完成。
        """
        with self.lock:
            old_end = self.end
            next_pos = self.start + self.written
            cut = max(old_end - int(take), next_pos)
            if cut >= old_end:
                return None, 0              # 尾巴已经下完/太小, 放弃这次加段
            marker = _PipeAbandon()
            self.abandon = marker
            marker.fire()
            self.end = int(cut)
            return marker, int(cut)

    def clear_abandon(self) -> None:
        """worker 消费完"切段标记"后清掉它(下一轮才能干净地重开连接)。"""
        with self.lock:
            marker = self.abandon
            self.abandon = None
        if marker is not None:
            marker.consume()

    def touch(self) -> None:
        """收到字节了(测速采样点)。"""
        self.last_byte = time.monotonic()


class _Progress(object):
    """字节账本 + 单调显示。

    账本 ``done`` 是"已经确认落盘的字节", 可以回滚(PCL2 ModNet.vb:1147-1156 的
    ``Reset()``), 所以重试/换路径时不会虚高; 但回滚后重下同一批字节不能让界面
    看到进度倒退, 于是回调里给的是"只增不减、且 ≤ total"的 ``shown``。
    多个分片线程会并发回调, 这里用锁把回调串行化(调用方的字节增量统计不是线程安全的)。
    """

    def __init__(self, cb, total: int = 0):
        self.cb = cb
        self.total = int(total or 0)
        self.done = 0
        self.shown = 0
        self._lock = threading.Lock()
        self._cb_lock = threading.Lock()
        self._last = 0.0

    def add(self, count: int) -> None:
        with self._lock:
            self.done += int(count)

    def rollback(self, count: int) -> int:
        """回滚账本, 返回真正减掉的字节数。"""
        with self._lock:
            amount = max(0, min(int(count), self.done))
            self.done -= amount
            return amount

    def reset(self) -> int:
        """整份账本清零(整体重来前用), 返回回滚掉的字节数。"""
        with self._lock:
            amount = self.done
            self.done = 0
            return amount

    def emit(self, force: bool = False) -> None:
        if self.cb is None:
            return
        now = time.monotonic()
        with self._cb_lock:
            with self._lock:
                if not force and self.done < self.total \
                        and (now - self._last) < PROGRESS_MIN_INTERVAL:
                    return
                self._last = now
                self.shown = max(self.shown, self.done)
                current, total = self.shown, self.total
            try:
                self.cb(current, total)
            except Exception:
                pass


# ---------------------------------------------------------------- 小工具
def _host_of(url) -> str:
    """取 host(调试打印用, 拿不到就截一段 url)。"""
    try:
        host = urllib.parse.urlsplit(str(url)).netloc
    except Exception:
        host = ""
    return host or str(url or "")[:60]


def _silent_close(resp) -> None:
    """关闭响应, 失败忽略。"""
    if resp is None:
        return
    try:
        resp.close()
    except Exception:
        pass


def _content_length(headers) -> int:
    """Content-Length(拿不到返回 0)。"""
    try:
        return int(headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _range_total(headers) -> int:
    """从 ``Content-Range: bytes 0-0/12345`` 里取总长度(拿不到返回 0)。"""
    text = str(headers.get("Content-Range") or "")
    if "/" not in text:
        return 0
    tail = text.rsplit("/", 1)[-1].strip()
    return int(tail) if tail.isdigit() else 0


def _sha1_file(path: str) -> str:
    """文件的 sha1(读不了返回空串)。"""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _verify_file(path: str, size: int = 0, expect_sha1=None) -> bool:
    """大小 + (可选)sha1 校验。"""
    try:
        if size and os.path.getsize(path) != int(size):
            return False
    except Exception:
        return False
    if expect_sha1:
        return _sha1_file(path) == str(expect_sha1).strip().lower()
    return True


def _multipart_blocked(url) -> bool:
    """命中"禁用多线程"名单就返回 True(大小写不敏感子串匹配, ModNet.vb:853-854)。"""
    low = str(url or "").lower()
    for token in MULTIPART_BLOCKED_TOKENS:
        if token in low:
            return True
    return False


def _conn_corrupt(exc) -> bool:
    """这个异常是不是"连接/记录层已经坏了, 必须换一条新连接"?

    典型是 ``ssl.SSLError``(例如 ``DECRYPTION_FAILED_OR_BAD_RECORD_MAC``): 一旦出现,
    **同一条连接上继续 read 或"原地续传"都是错的** —— 记录边界已经不可信, 续传只会
    把坏数据接在好数据后面(大小对、sha1 错的静默坏文件), 而且会在同一条坏连接上
    反复失败。所以这里统一判定为"坏连接", 由调用方丢弃连接、清掉本次已写字节、重开。
    """
    try:
        if isinstance(exc, ssl.SSLError):
            return True
    except Exception:
        pass
    text = repr(exc).lower()
    for token in ("decryption_failed", "bad_record_mac", "wrong_version_number",
                  "sslv3_alert", "tlsv1_alert", "record layer failure",
                  "eof occurred in violation of protocol"):
        if token in text:
            return True
    return False


def _plan_segments(size: int, limit: Optional[int] = None) -> List[Tuple[int, int]]:
    """按 PCL2 的动态分段规则切分: 每次在"剩余量最大且 ≥256KB"的段上切走 40%。

    ``limit`` 不传时读**当前生效**的段数上限(环境变量优先, 见 :func:`multi_max_segments`);
    注意不能写成默认参数 ``limit=MULTI_MAX_SEGMENTS`` —— 那样默认值在函数定义时就被
    固定, 改常量/设环境变量都不会生效。

    大小未知(≤0)或 < 阈值一律不给分片方案(ModNet.vb:674-678)。
    """
    total = int(size)
    if limit is None:
        limit = multi_max_segments()
    if total < multi_min_size():
        return [(0, total)] if total > 0 else []
    count = max(1, int(limit))
    segments = [(0, total)]
    while len(segments) < count:
        index, best = -1, 0
        for i, (start, end) in enumerate(segments):
            if end - start > best:
                index, best = i, end - start
        if index < 0 or best < MULTI_MIN_SEGMENT:
            break
        take = int(best * MULTI_SPLIT_RATIO)
        if take <= 0:
            break
        start, end = segments[index]
        segments[index] = (start, end - take)     # 原段留 60%
        segments.append((end - take, end))        # 新段拿走 40%
    segments.sort()
    return segments


# ---------------------------------------------------------------- Range 探测
def _accepts_bytes(resp) -> bool:
    """响应头没有**明确否认** Range 支持(缺这条头不算否认)。"""
    if resp is None:
        return False
    value = str(resp.headers.get("Accept-Ranges") or "").strip().lower()
    return (not value) or ("bytes" in value)


def _probe_range(url: str, timeout: int):
    """发一个 ``Range: bytes=0-1`` 探测, 并**只读 PROBE_PREFIX(2) 字节**就停手。

    返回 ``(resp, code, total, prefix)``:
      * code==206: resp 是打开的连接(已读完), prefix 是那 2 字节正文;
      * code==200: 服务端忽略了 Range, 正文是完整文件, 可以当单流直接用(prefix 接回去);
      * 其它(416/403/429/502/连接失败): resp 为 None。

    ⚠️ 这里以前发的是 ``Range: bytes=0-``, 等于让服务端推整份文件, 探测请求白耗
    64-90KB(本地实测); 而且 ``resp.read(PROBE_PREFIX)`` 里的 PROBE_PREFIX 当时**没有
    定义**, 抛出的 NameError 被下面的 ``except`` 吞掉, prefix 永远是 b"" —— 是"静默失效"。
    现在常量已定义, 探测正文被钉死在 2 字节, 不读进内存、也不计进度。
    """
    try:
        request = _request(url, timeout, {"Range": "bytes=0-%d" % (PROBE_PREFIX - 1)})
        resp = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        _silent_close(exc)
        return None, code, 0, b""
    except Exception:
        return None, 0, 0, b""
    code = int(getattr(resp, "status", 0) or 0)
    if code not in (200, 206):
        _silent_close(resp)
        return None, code, 0, b""
    total = _range_total(resp.headers) if code == 206 else _content_length(resp.headers)
    try:
        prefix = resp.read(PROBE_PREFIX) or b""
    except Exception:
        prefix = b""
    return resp, code, total, prefix


class _PrefixReader(object):
    """把"探测时已经读掉的正文"接回响应流, 让单流下载看起来像没读过。

    只实现下载路径真正用到的那点接口(read / headers / status / close), 故意不做
    通用的 file-like 假象 —— 越像就越容易在别处被误用。
    """

    __slots__ = ("_resp", "_prefix")

    def __init__(self, resp, prefix: bytes):
        self._resp = resp
        self._prefix = prefix or b""

    def read(self, size: int = -1) -> bytes:
        if not self._prefix:
            return self._resp.read(size)
        if size is None or size < 0:
            head, self._prefix = self._prefix, b""
            return head + (self._resp.read() or b"")
        head = self._prefix[:size]
        self._prefix = self._prefix[size:]
        if len(head) >= size:
            return head
        return head + (self._resp.read(size - len(head)) or b"")

    def close(self) -> None:
        _silent_close(self._resp)

    @property
    def headers(self):
        return self._resp.headers

    @property
    def status(self) -> int:
        return int(getattr(self._resp, "status", 0) or 0)


def _probe_download(url: str, timeout: int):
    """决定用哪种方式下, 返回 ``(mode, size, resp)``。

      * ``("multi", size, None)``  —— 支持 Range 且总长度达到阈值, 走分片并发;
      * ``("single", size, None)`` —— 单流(命中禁多线程名单/Range 被拒/不到阈值);
      * ``("reuse", size, resp)``  —— 单流, 且 resp 就是探测时打开的那份正文
        (需要调用方 close; 已预读的 2 字节被 _PrefixReader 接回去了)。只有服务端
        **不认 Range**(200)时才会走到这里 —— 那时正文本来就是整份文件。

    只有 ``reuse`` 的 resp 需要调用方 close。
    """
    segments = multi_max_segments()
    if segments <= 1:
        # 逃生开关(PCLPY_DOWNLOAD_SEGMENTS=0 或 1): 连探测都不发, 直接单流
        _dbg("MULTIPART DISABLED (segments=%d) -> single stream" % segments)
        return "single", 0, None
    if _multipart_blocked(url):
        # 命中禁多线程名单: 直接普通 GET(1 次请求), 连 Range 探测都不发
        _dbg("MULTIPART BLOCKED (host in blacklist) -> single stream")
        return "single", 0, None
    resp, code, total, prefix = _probe_range(url, timeout)
    length = _content_length(resp.headers) if resp is not None else 0
    _dbg("PROBE url=%s http=%d total=%d length=%d prefix=%d"
         % (_host_of(url), code, total, length, len(prefix)))
    if code == 206:
        # 206 的 total 来自 Content-Range(唯一可信的总长度来源)。
        if total >= multi_min_size() and _accepts_bytes(resp):
            _silent_close(resp)          # 多线程会各自重开连接, 这条探测连接退休
            return "multi", total, None
        # 不到阈值: 走单流。探测只取了 2 字节(bytes=0-1)而且响应已经到尾巴, 这点正文
        # 接不回单流(以前 bytes=0- 时能复用), 所以关掉连接、由单流重新发一次普通 GET。
        # 代价是每个"不分片的小文件"多 1 次请求、白读 2 字节; 换来的是探测**绝不**让
        # 服务端推整份正文 —— 分片省下来的请求远多于这一次。
        _silent_close(resp)
        return "single", total, None
    if code == 200 and resp is not None:
        # 服务端不认 Range: 正文就是完整文件, 直接拿它当单流, 不报错也不多花一次请求
        return "reuse", total, _PrefixReader(resp, prefix)
    _silent_close(resp)
    return "single", 0, None


class _Registry(object):
    """在途响应登记簿: 取消时把它们全部 close, 阻塞在 read 上的线程才会立刻退出。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = []  # type: List[Any]

    def add(self, resp) -> None:
        with self.lock:
            self.items.append(resp)

    def discard(self, resp) -> None:
        with self.lock:
            try:
                self.items.remove(resp)
            except ValueError:
                pass

    def take_all(self) -> list:
        with self.lock:
            items = list(self.items)
            del self.items[:]
        return items


# ---------------------------------------------------------------- 分段下载
class _PipeAbandon(object):
    """一次性的"这条连接该收手了"标记(扩容把本段尾巴切走时用)。

    为什么需要它: ``abort`` 是**一次性**事件, 但 ``_pipe_range`` 的读循环每轮都会看
    它一眼。如果直接复用 ``abort``, 那么"扩容 → 连接收手 → worker 从头重试"这条
    路径上, 重试的 ``_pipe_range`` 会**一进门就看到 abort 已置位而立刻返回 0 字节**,
    worker 于是拿到 0 字节 → 不报错 → 立刻再试 → 再拿 0 字节 …… 一个纯 GIL 空转的
    活锁(实测 6 万次/秒/线程, 能把主线程饿到"未响应")。

    所以扩容给段挂上这个标记; 谁先消费掉它谁负责把连接收掉, 标记随即作废, 下一轮
    ``_pipe_range`` 就能正常重开连接从"上次写到的位置"继续。调用方拿返回值判断自己
    是不是那个"中选者"(``True`` = 本次调用因为切段而收手)。
    """

    __slots__ = ("_event", "_fired", "abandoned", "_lock")

    def __init__(self):
        self._event = threading.Event()
        self._fired = False
        self.abandoned = False
        self._lock = threading.Lock()

    def fire(self) -> None:
        """扩容切段时调用(由监控线程执行)。"""
        self._fired = True
        self._event.set()

    def take(self) -> bool:
        """读循环里调用: 返回 True 表示"本次因为切段收手", 且标记只生效一次。"""
        with self._lock:
            if not (self._fired and self._event.is_set()):
                return False
            self._fired = False
            self._event.clear()
            self.abandoned = True
            return True

    def consume(self) -> None:
        """worker 侧确认这条连接已经收手(清掉标记, 允许重开连接)。"""
        with self._lock:
            self._fired = False
            self._event.clear()

    def cancelled(self) -> bool:
        """已经因为切段收过手了(worker 用它区分"切段"和"0 字节空转")。"""
        with self._lock:
            return bool(self.abandoned)


class _SegPool(object):
    """单文件分片线程池: 段在队列里排队, 线程**复用**(不再每轮 plan 起一批/join 一批)。

    * 线程**按需增长**(提交任务时若没有空闲线程才新建), 上限 = :data:`MULTI_POOL_SIZE`;
      用不到的线程阻塞在队列上, 0 CPU; 有任务时优先交给空闲线程, 不新建;
    * 线程全部是 daemon; 一个文件下载完就把池标成空闲, 由 :func:`_drain_idle_pools`
      发退出哨兵(正在下别的文件时不会误杀)。
    """

    __slots__ = ("_work", "_threads", "_busy_count", "_lock", "_size")

    def __init__(self, size: int):
        self._work = queue.Queue()
        self._threads = []          # type: List[threading.Thread]
        self._busy_count = 0
        self._lock = threading.Lock()
        self._size = max(1, int(size))

    def _runner(self) -> None:
        while True:
            item = self._work.get()
            if item is None or item[0] is None:
                with self._lock:
                    self._busy_count -= 1
                return                   # 退出哨兵
            job, on_done = item
            try:
                job()
            except BaseException:        # job 自己负责记错, 这里绝不让线程死掉
                pass
            finally:
                try:
                    if on_done is not None:
                        on_done()
                finally:
                    with self._lock:
                        self._busy_count -= 1

    def submit(self, job, on_done=None) -> None:
        """投递一段的下载任务; ``on_done`` 在工作线程里执行(用于递减在途计数)。"""
        with self._lock:
            if self._busy_count >= len(self._threads) and len(self._threads) < self._size:
                thread = threading.Thread(target=self._runner, name="pclpy-seg-pool")
                thread.daemon = True
                self._threads.append(thread)
                thread.start()
            self._busy_count += 1
        self._work.put((job, on_done))

    def stop(self, timeout: float = 0.5) -> None:
        """发退出哨兵并回收线程(下载结束/失败时由 _drain_idle_pools 调用)。"""
        with self._lock:
            count = len(self._threads)
            self._threads = []
            self._busy_count = 0
        for _index in range(count):
            try:
                self._work.put((None, None))
            except Exception:
                pass

    @property
    def threads_count(self) -> int:
        with self._lock:
            return len(self._threads)


_SEG_POOL = None         # type: Optional[_SegPool]
_POOL_LOCK = threading.Lock()
_POOL_BUSY = 0           # 正在用这个池子的文件数


def _acquire_pool() -> "_SegPool":
    """取进程内唯一的段线程池(正在下别的文件时也只是共用, 线程上限不变)。"""
    global _SEG_POOL, _POOL_BUSY
    with _POOL_LOCK:
        if _SEG_POOL is None or not _SEG_POOL.threads_count and _POOL_BUSY <= 0:
            _SEG_POOL = _SegPool(MULTI_POOL_SIZE)
        _POOL_BUSY += 1
        return _SEG_POOL


def _release_pool(pool) -> None:
    """文件下载结束(无论成败)时归还池子。"""
    global _POOL_BUSY
    with _POOL_LOCK:
        _POOL_BUSY = max(0, _POOL_BUSY - 1)


def _drain_idle_pools() -> None:
    """没有任何文件在用分片时, 把池子的线程收掉(不留常驻空转线程)。"""
    global _SEG_POOL
    with _POOL_LOCK:
        if _POOL_BUSY > 0 or _SEG_POOL is None:
            return
        pool = _SEG_POOL
        _SEG_POOL = None
    pool.stop()


def _pipe_range(url: str, start: int, end: int, timeout: int, cancel_ev, registry,
                sink, gate=None, abort_ev=None, seg=None) -> int:
    """按 Range 拉 ``[start, end)`` 并喂给 ``sink(data, pos)``。

    返回写入字节数; 少于请求长度**不算异常**(服务端分段返回是允许的), 由调用方
    续传。服务端不返回 206 时抛 ``_NoRange`` → 上层降级单流。

    ``gate``: 全局连接预算(信号量), 拿到才开连接、连接关掉就还回去 —— 这是
    "整个进程最多 N 条并发 Range 连接"的落点。
    ``abort_ev``: "这段被切成两段了"的信号(见 :func:`_download_multipart` 的自适应
    扩容) —— 它其实是一个 :class:`_PipeAbandon`; 被它拦下一次就作废(一次性),
    这样 worker 的重试能从"上次写到的位置"重开连接接着下, 不会一进门就被拦死。
    ``seg``: 本段进度记账对象; 给它挂 abort_ev 之后, 扩容线程一置位就能让这条
    正在 read 的连接停下(_pipe_range 的读循环里检查, 不在函数入口检查)。
    """
    if end <= start:
        return 0
    if cancel_ev is not None and cancel_ev.is_set():
        raise _Cancelled()
    if abort_ev is not None and abort_ev.cancelled():
        # 上一轮连接已经按旧的段尾收手了; 现在必须重开连接从 start 继续, 不能在这里
        # 直接返回 0 —— 那正是老代码的活锁入口(0 字节 → 不报错 → 立刻重试 → 又 0 字节)。
        pass
    request = _request(url, timeout, {"Range": "bytes=%d-%d" % (start, end - 1)})
    gate = gate if gate is not None else _NO_GATE
    if not gate.acquire():
        raise IOError("connection budget wait timed out")
    resp = None
    try:
        try:
            resp = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            _silent_close(exc)
            # 416 不支持 Range; 502/403/429 等按 PCL2 当"该源失败"(ModNet.vb:1079-1099)
            raise _NoRange("http %d" % code)
        except Exception as exc:
            raise IOError("range request failed: %r" % (exc,))
        if registry is not None:
            registry.add(resp)
        code = int(getattr(resp, "status", 0) or 0)
        if code != 206:
            raise _NoRange("http %d (range ignored)" % code)
        content_range = str(resp.headers.get("Content-Range") or "")
        match = re.match(r"\s*bytes\s+(\d+)-", content_range)
        if match and int(match.group(1)) != int(start):
            raise _NoRange("content-range start %s != %d" % (match.group(1), start))
        written = 0
        pos = int(start)
        while True:
            if cancel_ev is not None and cancel_ev.is_set():
                raise _Cancelled()
            if abort_ev is not None and abort_ev.take():
                # 这段被切成两段了: 连接收掉, 不报错, 由 _segment_worker 按新的段尾续
                return written
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            if sink(chunk, pos) is False:
                # sink 说"到这里为止"(段尾被自适应扩容改小了), 干净收工
                return written
            pos += len(chunk)
            written += len(chunk)
            if seg is not None:
                seg.touch()
        return written
    finally:
        if registry is not None and resp is not None:
            registry.discard(resp)
        _silent_close(resp)
        gate.release()


def _close_responses(registry) -> None:
    """关掉所有在途响应(取消时用它立刻解开阻塞在 read 上的线程)。"""
    items = registry.take_all() if registry is not None else []
    for resp in items:
        _silent_close(resp)


def _stop_workers(segments, registry, cancel_ev, progress=None) -> None:
    """置取消事件 + 让所有段收手 + 关掉在途连接, 然后等"字节停止增长"再返回。

    连接关掉之后, 阻塞在 ``read`` 上的线程会立刻返回/报错, 所以这里**不需要**按线程
    join 5+2 秒(池化之后段任务本来也没有自己的 Thread 对象可 join)。判据改成"账本
    连续一小段时间没有新增字节", 既精确又短: 以前 8 个文件一起失败时, 每个线程
    join(5.0) 能把主线程按住几十秒, 那本身就是"未响应"的一大来源。
    """
    cancel_ev.set()
    for seg in list(segments or []):
        seg.abort.set()                  # 让还在循环里的段马上下线
        marker = getattr(seg, "abandon", None)
        if marker is not None:
            marker.fire()                # 让下一次读循环收手(已经在 read 里的靠 close)
    _close_responses(registry)
    last = None
    for _round in range(20):             # 最多 ~0.5s
        current = None
        if progress is not None:
            try:
                current = int(progress.done)
            except Exception:
                current = None
        if current is not None and current == last:
            break
        last = current
        time.sleep(0.025)
    _close_responses(registry)           # 有的线程可能刚开了新连接


def _segment_worker(url: str, seg: _Segment, timeout: int, cancel_ev, registry,
                    sink, progress: _Progress, gate=None) -> None:
    """下完一个段: 失败先原地续传, 续不动了就回滚本段账本从段头重来。

    ``seg.end`` 会在自适应扩容时被别的线程改小(尾巴切给新段), 同时该段被挂上一个
    :class:`_PipeAbandon` 标记。被标记的那条连接收手后, 这里**重开一条连接**从
    "上次写到的绝对位置"接着下 —— 绝不空转: 只有真的又收到 0 字节才会重新计数,
    连续 :data:`MULTI_ZERO_BYTE_LIMIT` 次 0 字节(且没被切段)就把这一段判死。
    """
    attempts = 0
    resumes = 0
    stalls = 0
    last_error = None  # type: Optional[BaseException]
    while True:
        if seg.remaining <= 0:
            return                       # 下完了(含"被切走尾巴后正好下完"的情况)
        if cancel_ev.is_set():
            raise _Cancelled()
        attempts += 1
        if attempts > MULTI_SEGMENT_ATTEMPTS:
            raise _MultiFailed("segment attempts exceeded [%d,%d)" % (seg.start, seg.end))
        start = seg.start + seg.written
        before = seg.written
        seg.clear_abandon()              # 本轮开始前先清标记: 之后它非空 = 本轮真被切了
        error = None
        try:
            _pipe_range(url, start, seg.end, timeout, cancel_ev, registry, sink,
                        gate=gate, abort_ev=seg.abandon, seg=seg)
        except _Cancelled:
            raise
        except _NoRange as exc:
            raise _MultiFailed(str(exc))
        except _MultiFailed:
            raise
        except Exception as exc:  # 网络中断/短读/磁盘错误
            error = exc
            last_error = exc
        if seg.remaining <= 0:
            return
        advanced = seg.written > before
        if advanced:
            stalls = 0                  # 真的有进展 → 上次的"停滞"不算数
        if error is None:
            # 没出错却没下完: 要么被扩容切段(正常), 要么服务端给了 0 字节的短读。
            # 切段不是失败: 不计数、不退避, 直接按新的段尾接着下(重开连接前会先清标记)。
            attempts = max(0, attempts - 1)
            if seg.abandon is not None:
                _dbg("SHRUNK seg=[%d,%d) from=%d written=%d remaining=%d"
                     % (seg.start, seg.end, before, seg.written, seg.remaining))
                continue
            stalls += 1
            if stalls >= MULTI_ZERO_BYTE_LIMIT:
                # 真的停滞(反复 0 字节又不报错) → 交给回滚/重试路径收敛, 绝不 while 空转
                error = IOError("zero-byte stall at %d" % (seg.start + seg.written))
                last_error = error
            else:
                continue
        if error is None:
            continue
        if resumes < MULTI_SEGMENT_RESUMES and seg.remaining > 0 \
                and not _conn_corrupt(error):
            # 普通短读/连接重置: 原地续传(不重下已经写好的字节)
            resumes += 1
            _dbg("RESUME seg=[%d,%d) from=%d written=%d remaining=%d err=%s"
                 % (seg.start, seg.end, seg.start + seg.written, seg.written,
                    seg.remaining, last_error))
            time.sleep(min(MULTI_RETRY_BACKOFF * (2 ** max(0, attempts - 1)), 1.0))
            continue
        if resumes < MULTI_SEGMENT_RESUMES and _conn_corrupt(error):
            # TLS 记录层坏了: 这条连接写进来的字节不可信 → 原地续传会拼出坏文件。
            # 丢连接、丢本段已写字节、**从段头重开一条新连接**(不复用任何 socket)。
            resumes += 1
            rolled = progress.rollback(seg.written)
            _dbg("CORRUPT DROP seg=[%d,%d) rolled=%d err=%s"
                 % (seg.start, seg.end, rolled, last_error))
            seg.written = 0
            time.sleep(min(MULTI_RETRY_BACKOFF * (2 ** max(0, attempts - 1)), 1.0))
            continue
        # 续传走不通 → 回滚本段已计字节, 从段头重来(账本不许虚高)
        rolled = progress.rollback(seg.written)
        seg.written = 0
        resumes = 0
        stalls = 0
        attempts = 0                     # 重新开一个"续传-回滚"周期, 免得一次抖动就判死
        _dbg("ROLLBACK segment=[%d,%d) bytes_before=%d rolled=%d bytes_after=%d err=%s"
             % (seg.start, seg.end, before, rolled, seg.written, last_error))
        if cancel_ev.is_set():
            raise _Cancelled()
        if rolled == 0 and start == seg.start and not seg.abort.is_set():
            raise _MultiFailed("segment dead [%d,%d): %s" % (seg.start, seg.end, last_error))


def _expand(now: float, state: list, phase: dict, segments: list, progress: _Progress,
            gate, submit) -> bool:
    """低速才加线程(PCL2 ModNet.vb:1747): 返回是否真的加了一段。

    判据(全部满足才加) —— 这就是"加段必须有界且带迟滞":
      ① 距上次采样 ≥ ``MULTI_SPEED_SAMPLE_INTERVAL``; 没到就什么都不做;
      ② 窗口内本文件实测吞吐 < ``multi_low_speed_bps()`` 且连续若干次都低(防抖);
      ③ **冷却**: 距上次真正加段 ≥ :data:`MULTI_EXPAND_COOLDOWN` 秒;
      ④ **看疗效**: 上一个"加段相位"的平均吞吐至少要到加段前的
         :data:`MULTI_EXPAND_MIN_GAIN` 倍; 不然记一次"没收益", 连续
         :data:`MULTI_EXPAND_NO_GAIN` 次没收益就不再评估加段(不再无限追);
      ⑤ **硬上限**: 单文件整个生命周期内加段次数 ≤ :data:`MULTI_EXPAND_MAX`;
      ⑥ 还没到段数上限、连接预算有空位、且存在"剩余量 ≥2×256KB 的未切段"。
    """
    if (now - state[0]) < MULTI_SPEED_SAMPLE_INTERVAL:
        return False
    interval = max(now - state[0], 1e-6)
    done = progress.done
    speed = (done - state[1]) / interval
    state[0] = now
    state[1] = done
    phase["speed"] += speed
    phase["samples"] += 1
    if speed >= multi_low_speed_bps():
        state[2] = 0
        return False
    state[2] += 1
    _dbg("SPEED sample bps=%d low_streak=%d" % (int(speed), state[2]))
    if state[2] < MULTI_LOW_SPEED_SAMPLES:
        return False
    # ① 硬上限: 加够了就永远不再评估(慢连接不可能被"加段"救活, 只能别再折腾)
    if state[7] >= MULTI_EXPAND_MAX:
        _dbg("EXPAND SKIP at-cap expanded=%d" % state[7])
        return False
    # ② 冷却: 两次加段之间必须隔够时间, 给足"观察疗效"的窗口
    if state[3] and (now - state[3]) < MULTI_EXPAND_COOLDOWN:
        _dbg("EXPAND SKIP cooldown %.1fs" % (now - state[3]))
        return False
    # ③ 看疗效: 上一个相位加了段却没把吞吐抬起来 → 记一次"没收益"
    if state[3] and state[5]:
        elapsed = max(now - state[3], 1e-6)
        phase_speed = (done - state[4]) / elapsed
        if phase_speed < state[5] * MULTI_EXPAND_MIN_GAIN:
            state[6] += 1
            _dbg("EXPAND NO-GAIN phase_bps=%d before_bps=%d streak=%d"
                 % (int(phase_speed), int(state[5]), state[6]))
            if state[6] >= MULTI_EXPAND_NO_GAIN:
                _dbg("EXPAND SKIP no-gain-streak=%d" % state[6])
                return False
        else:
            state[6] = 0
    if len(segments) >= multi_max_segments():
        _dbg("EXPAND SKIP at-max segments=%d" % len(segments))
        return False
    # 切"剩余量最大且 ≥2×256KB"的段: 切的是**还没下的尾巴**(ModNet.vb:857-862),
    # 已落盘的字节不受影响, 所以正在下载的段也能切。
    candidate = None
    best = 0
    for seg in segments:
        if seg.abort.is_set():
            continue
        if seg.remaining > best:
            candidate, best = seg, seg.remaining
    if candidate is None or best < 2 * MULTI_MIN_SEGMENT:
        _dbg("EXPAND SKIP no-room %s"
             % [(s.start, s.end, s.written) for s in segments])
        return False
    # 连接预算还有空位才加(拿不到就保持现状, 不要为了加线程去占满预算)
    if not gate.acquire(timeout=0.05):
        _dbg("EXPAND SKIP no-budget")
        return False
    gate.release()
    take = int(best * MULTI_SPLIT_RATIO)
    if take < MULTI_MIN_SEGMENT:
        _dbg("EXPAND SKIP take-too-small take=%d" % take)
        return False
    # 新段拿走"剩余量的 40%"(= 段尾), 原段的尾巴缩短 40% 后继续下。
    # 真正的切点在 ``split_tail`` 里算(要和"下一颗 64KB 块的起写位置"原子比较)。
    old_end = candidate.end
    marker, cut = candidate.split_tail(take)
    if marker is None:
        _dbg("EXPAND SKIP split-refused src=[%d,%d) take=%d" % (candidate.start, old_end, take))
        return False
    tail = _Segment(cut, old_end)
    segments.append(tail)
    state[2] = 0
    state[3] = now                       # 冷却起点 / 疗效基准时刻
    state[4] = done
    before_speed = (phase["speed"] / phase["samples"]) if phase["samples"] else 0.0
    state[5] = before_speed
    state[6] = 0
    state[7] += 1
    phase["speed"] = 0.0
    phase["samples"] = 0
    _dbg("EXPAND segments=%d src=[%d,%d) new=[%d,%d) bytes=%d count=%d before_bps=%d"
         % (len(segments), candidate.start, candidate.end, tail.start,
            tail.end, tail.size, state[7], int(before_speed)))
    submit(tail)
    return True


def _download_multipart(url: str, dest: str, part: str, size: int, timeout: int,
                        cancel_cb, expect_sha1, progress: _Progress) -> bool:
    """多段并发下载到 ``dest.part``。

    返回 True: 成功(dest 已就位); 返回 False: 多线程这条路失败(账本已回滚,
    调用方按 PCL2 的"全部源降级单线程"再试一次); 用户取消抛 ``_Cancelled``。
    """
    initial = max(1, min(multi_max_segments(), multi_start_segments()))
    plan = _plan_segments(size, initial)
    segments = [_Segment(start, end) for start, end in plan]
    _dbg("PLAN url=%s size=%d segments=%d max_segments=%d gate=%d start=%d slow_bps=%d"
         % (_host_of(url), size, len(segments), multi_max_segments(),
            multi_max_connections(), initial, multi_low_speed_bps()))
    for seg in segments:
        _dbg("  SEGMENT [%d,%d) bytes=%d" % (seg.start, seg.end, seg.size))
    try:
        with open(part, "wb") as handle:
            handle.truncate(int(size))       # 先占好位置, 各段按绝对偏移并发写
    except Exception as exc:
        _dbg("MULTIPART PREP FAILED: %r" % (exc,))
        return False

    cancel_ev = threading.Event()
    registry = _Registry()               # 打开中的响应, 取消时直接 close
    gate = _range_gate()                 # 全局连接预算(信号量)
    errors = []                          # type: List[BaseException]
    pool = _acquire_pool()               # 单文件线程池: 段在队列里排队, 线程复用
    counters = {"pending": 0}
    counters_lock = threading.Lock()
    part_lock = threading.Lock()

    def _sink_factory(seg: _Segment):
        """每段一个写句柄, 按绝对偏移写同一份 .part。

        写句柄在**同一把锁**里 seek+write: Windows 上多个线程共享/并行操作文件指针
        很容易写出错位的数据, 而且这种错位是"大小对、sha1 错"的静默坏文件。
        """
        try:
            handle = open(part, "r+b")
        except Exception as exc:
            raise _MultiFailed("open part failed: %r" % (exc,))

        def _sink(data, pos):
            # 段尾检查 + 写盘必须在段的锁里原子完成(见 _Segment 的说明): 否则扩容
            # 改小段尾的瞬间, 旧连接会把一块"已经不属于自己"的数据写进 .part,
            # 而拿到这段尾巴的新线程又会写一遍 → 字节数比文件还大, 整份作废重下。
            def _write(payload):
                with part_lock:
                    handle.seek(pos)
                    handle.write(payload)

            written = seg.write_at(pos, data, _write)
            if written < 0:
                # 段尾被自适应扩容改小了, 落在新段里的字节不是我们的: 停止本连接
                return False
            progress.add(written)
            progress.emit()
            return True

        return handle, _sink

    def _worker(seg: _Segment) -> None:
        handle = None
        try:
            handle, _sink = _sink_factory(seg)
            _segment_worker(url, seg, timeout, cancel_ev, registry, _sink, progress,
                            gate=gate)
        except _Cancelled:
            errors.append(_Cancelled())
            cancel_ev.set()
        except BaseException as exc:  # 一段废了, 其它段立刻停
            errors.append(exc)
            cancel_ev.set()
        finally:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass

    def _done() -> None:
        with counters_lock:
            counters["pending"] -= 1

    def _submit(seg: _Segment) -> None:
        with counters_lock:
            counters["pending"] += 1
        pool.submit(lambda seg=seg: _worker(seg), _done)

    for seg in segments:
        _submit(seg)

    # [上次采样时刻, 上次字节, 连续低速次数, 上次加段时刻, 上次加段字节,
    #  上次加段时本文件吞吐, 连续"加了没收益"次数, 已加段次数]
    last_check = [time.monotonic(), 0, 0, 0.0, 0, None, 0, 0]
    phase = {"start": time.monotonic(), "bytes": 0, "speed": 0.0, "samples": 0}
    try:
        while True:
            if _cancelled(cancel_cb):
                _stop_workers(segments, registry, cancel_ev, progress)
                raise _Cancelled()
            with counters_lock:
                pending = counters["pending"]
            if not pending or errors:
                break
            try:
                _expand(time.monotonic(), last_check, phase, segments, progress,
                        gate, _submit)
            except Exception as exc:                 # 扩容是"锦上添花", 绝不能拖垮下载
                _dbg("EXPAND FAILED: %r" % (exc,))
            time.sleep(0.05)
        if not errors:
            # 所有段都已下完, 但可能有段刚被切过尾巴: 再扫一轮, 把尾巴交给池子
            while True:
                with counters_lock:
                    pending = counters["pending"]
                if pending or errors:
                    break
                if not _expand(time.monotonic(), last_check, phase, segments, progress,
                               gate, _submit):
                    break
                time.sleep(0.01)
    finally:
        if errors or cancel_ev.is_set():
            _stop_workers(segments, registry, cancel_ev, progress)
        _release_pool(pool)
        _drain_idle_pools()

    if errors:
        fatal = [item for item in errors if not isinstance(item, _Cancelled)]
        if not fatal:
            raise _Cancelled()
        _stop_workers(segments, registry, cancel_ev, progress)
        rolled = progress.reset()
        # ⚠️ 分片写出来的 .part 是**稀疏**的(各段按绝对偏移写, 段与段之间可能还是
        # 洞)。单流兜底只能**从 0 重下**, 所以这里必须把它清掉 —— 留着它, 兜底会
        # 以为"已有 N 字节可以续传", 把新数据接到洞里, 产出大小对、内容错的坏文件。
        _silent_remove(part)
        _dbg("MULTIPART FAIL reason=%s bytes_before=%d bytes_after=%d"
             % (fatal[0], rolled, progress.done))
        return False

    written = sum(seg.written for seg in segments)
    if written != int(size) or any(seg.remaining > 0 for seg in segments):
        rolled = progress.reset()
        _dbg("MULTIPART INCOMPLETE written=%d/%d rollback=%d" % (written, size, rolled))
        _silent_remove(part)             # 稀疏 .part 不能留给单流兜底"续传"
        return False
    # 拼接前校验: 段数/每段字节都对(数据是按绝对偏移写进同一个 .part 的,
    # "按顺序拼接"在落盘时就完成了, 不需要再搬一遍数据)。
    if expect_sha1 and _sha1_file(part) != str(expect_sha1).strip().lower():
        rolled = progress.reset()
        _dbg("MULTIPART SHA1 FAIL (before rename) rollback=%d" % rolled)
        _silent_remove(part)
        return False
    os.replace(part, str(dest))
    # 拼接后校验: 大小 + (可选)sha1
    if not _verify_file(dest, size, expect_sha1):
        _silent_remove(dest)
        rolled = progress.reset()
        _dbg("MULTIPART VERIFY FAIL (after rename) rollback=%d" % rolled)
        return False
    progress.emit(force=True)
    _dbg("MULTIPART DONE url=%s bytes=%d" % (_host_of(url), written))
    return True


def _unlink(path: str) -> None:
    """删掉一个临时文件(不存在/删不掉都忽略; 单流重下前用它把 .part 清零)。"""
    try:
        os.remove(path)
    except Exception:
        pass


def _part_path(dest: str) -> str:
    return str(dest) + ".part"


def _report_avail(path: str, progress: _Progress) -> int:
    """把"磁盘上已有的那部分"计进进度账本(单流续传时用), 返回它的字节数。"""
    try:
        size = os.path.getsize(path)
    except Exception:
        return 0
    if size > 0:
        progress.add(int(size))
        progress.emit(force=True)
    return int(size)


def _download_single_once(url: str, dest: str, part: str, timeout: int, cancel_cb,
                          expect_sha1, progress: _Progress, mode: str,
                          offset: int = 0, prefix: bytes = b"", known_total: int = 0,
                          gate=None) -> bool:
    """单流下载的**一次**尝试(read 抛异常就让它抛出去, 由调用方续传)。

    ``mode`` 只有三个取值(用字符串而不是布尔, 便于调试输出):
      * ``"buffer"`` —— 内存里拼装(文件小于阈值, 探测把正文读了一点也能对上);
      * ``"truncate"`` —— 从 0 开始写 .part;
      * ``"append"`` —— 接着 .part 里已有的 offset 字节往下写(单流续传)。
    """
    handle = None
    close_resp = False
    buffer = None            # type: Optional[bytearray]
    try:
        resp = urllib.request.urlopen(_request(url, timeout), timeout=timeout)
        close_resp = True
        total = _content_length(resp.headers)
        if offset > 0:
            code = int(getattr(resp, "status", 0) or 0)
            if code != 206:
                _dbg("SINGLE RESUME REJECTED http=%d -> restart from 0" % code)
                _silent_close(resp)
                close_resp = False
                return False
            match = re.match(r"\s*bytes\s+(\d+)-", str(resp.headers.get("Content-Range") or ""))
            if match and int(match.group(1)) != int(offset):
                _silent_close(resp)
                close_resp = False
                return False
            if known_total > 0 and total > 0 and offset + total != known_total:
                _silent_close(resp)
                close_resp = False
                return False
            total = known_total or (offset + total)
        if total > 0:
            progress.total = total
        if mode == "buffer":
            buffer = bytearray(prefix)
            progress.reset()
        elif mode == "append":
            handle = open(part, "ab")
        else:
            handle = open(part, "wb")
        done = 0
        try:
            while True:
                if _cancelled(cancel_cb):
                    raise _Cancelled()
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                if buffer is not None:
                    buffer.extend(chunk)
                else:
                    handle.write(chunk)
                done += len(chunk)
                progress.add(len(chunk))
                progress.emit()
        finally:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
        on_disk = (len(buffer) + offset) if buffer is not None else (offset + done)
        if total > 0 and on_disk != total:
            raise IOError("short read %d/%d" % (on_disk, total))
        if buffer is not None:
            if expect_sha1 and hashlib.sha1(buffer).hexdigest() \
                    != str(expect_sha1).strip().lower():
                raise IOError("sha1 mismatch (memory)")
            with open(part, "wb") as out:
                out.write(buffer)
            if not _verify_file(part, total, expect_sha1):
                raise IOError("verify failed (after write)")
        elif expect_sha1 and not _verify_file(part, total, expect_sha1):
            raise IOError("verify failed")
        progress.emit(force=True)
        os.replace(part, str(dest))
        return True
    finally:
        if close_resp:
            _silent_close(resp)


def _download_single(url: str, dest: str, part: str, timeout: int, cancel_cb, expect_sha1,
                     progress: _Progress, resp=None, prefix: bytes = b"",
                     known_total: int = 0) -> bool:
    """单流下载(未知大小 / 小文件 / 不支持 Range / 多线程失败后的统一兜底)。

    * 探测已经打开的连接直接复用(``resp``), 探测预读的 ``prefix`` 也一并喂回来;
    * 小于阈值的文件先在**内存**里拼装, 不落分片文件;
    * 下完先校验总大小, 给了 expect_sha1 再校验 sha1;
    * **续传**: 一次尝试中途断线(短读/连接重置)不再从 0 重来 —— 把已经落盘的
      ``.part`` 接着写, 用 ``Range: bytes=<已有>-`` 续(服务端不认 Range 才回到 0),
      最多 :data:`MULTI_SEGMENT_ATTEMPTS` 次, 每次退避一点。以前这里只试一次,
      而且一失败就把整份文件删掉重下, 整合包这种"上百个文件并发"的场景下代价很大。
    * **连接层损坏(TLS 记录错)不续传**: 见 :func:`_conn_corrupt` —— 丢连接、丢这次
      已写字节、重开一条**全新**连接从 0 开始, 免得把坏字节接在好字节后面。
    * 取消或彻底失败都会清掉 .part, 坏文件不会被改名成 dest。
    """
    total = int(known_total or 0)
    gate = _range_gate()
    last_error = None  # type: Optional[BaseException]
    for attempt in range(1, MULTI_SEGMENT_ATTEMPTS + 1):
        if _cancelled(cancel_cb):
            _silent_remove(part)
            return False
        mode = "truncate"
        offset = 0
        use_resp = None
        use_prefix = b""
        if attempt == 1 and resp is not None:
            # 探测那条连接还开着: 直接拿它当这次单流的正文(prefix 已经在流里了)。
            # **只有第一次尝试**能复用它 —— 一旦这次读失败, 这条连接就废了, 后面
            # 必须重开, 免得对着一条坏连接反复 read(那样只会白等超时)。
            use_resp = resp
            use_prefix = prefix
            mode = "buffer" if 0 < int(total or 0) < multi_min_size() else "truncate"
        elif attempt > 1 and 0 < total < multi_min_size():
            # 小文件重试时在**内存**里拼, 不落 .part(和第一次的模式保持一致)
            mode = "buffer"
            _unlink(part)
        else:
            try:
                if os.path.isfile(part):
                    offset = int(os.path.getsize(part))
            except Exception:
                offset = 0
            if attempt > 1 and offset > 0 and offset < total:
                mode = "append"
                _report_avail(part, progress)     # 续传前先把已有字节计回账本
            else:
                _unlink(part)                     # 大小不对/已下满 → 从 0 重来
                offset = 0
        try:
            if not gate.acquire():
                raise IOError("connection budget wait timed out")
            try:
                if use_resp is not None:
                    handled = _download_single_once(url, dest, part, timeout, cancel_cb,
                                                    expect_sha1, progress, mode,
                                                    offset=0, prefix=use_prefix,
                                                    known_total=total)
                else:
                    handled = _download_single_once(url, dest, part, timeout, cancel_cb,
                                                    expect_sha1, progress, mode,
                                                    offset=offset,
                                                    known_total=total)
            finally:
                gate.release()
            if use_resp is not None:
                _silent_close(use_resp)           # 用完就关(成功也不会再回到这里)
                use_resp = None
                resp = None
            if not handled:
                # 服务端不认 Range(返回 200): .part 从 0 重来
                if mode == "append":
                    _unlink(part)
                    continue
                _silent_remove(part)
                return False
            return True
        except _Cancelled:
            _silent_close(use_resp)
            _silent_remove(part)
            return False
        except Exception as exc:
            last_error = exc
            _silent_close(use_resp)
            resp = None
            # 连接层损坏: 丢掉这条连接**以及**它可能写坏的字节, 下一次从 0 重开
            corrupt = _conn_corrupt(exc)
            if corrupt:
                _unlink(part)
                try:
                    progress.rollback(progress.done)
                except Exception:
                    pass
            _dbg("SINGLE RETRY attempt=%d/%d mode=%s offset=%d corrupt=%s err=%r"
                 % (attempt, MULTI_SEGMENT_ATTEMPTS, mode, offset, corrupt, exc))
            if _cancelled(cancel_cb):
                _silent_remove(part)
                return False
            time.sleep(min(MULTI_RETRY_BACKOFF * attempt, 1.0))
    _silent_remove(part)
    _dbg("SINGLE GIVE UP url=%s attempts=%d last_err=%r"
         % (_host_of(url), MULTI_SEGMENT_ATTEMPTS, last_error))
    return False


def download_file(url, dest, source="official", progress_cb=None, cancel_cb=None,
                  timeout=30, expect_sha1=None) -> bool:
    """下载到 dest(先写 .part 再改名), 成功返回 True。

    对外接口保持不变(调用方: install.py / core.resources / backend.workers);
    内部对"大小已知 ≥1MB 且服务端支持 Range"的文件改用多连接分片下载, 其它
    情况自动退回单流下载。

    ``progress_cb(current, total)``: current 是已确认字节(单调不减, 回滚时不会
    倒退), total 是文件总大小(未知时 0)。``expect_sha1`` 是新增的**可选**参数,
    传了就做哈希校验(不传至少校验总大小)。
    """
    text = str(url or "")
    if not text or not dest:
        return False
    final_url = rewrite_url(text, source)
    target = str(dest)
    part = target + ".part"
    try:
        folder = os.path.dirname(os.path.abspath(target))
        if folder:
            os.makedirs(folder, exist_ok=True)
    except Exception:
        pass

    progress = _Progress(progress_cb)
    probe_resp = None
    probe_prefix = b""
    try:
        mode, size, probe_resp = _probe_download(final_url, timeout)
        # reuse 模式下 resp 是 _PrefixReader, 探测预读的正文在它肚子里; 单流万一
        # 中途断线要续传, 得知道"已经吃进去多少字节"才不会重复写。
        if probe_resp is not None:
            probe_prefix = getattr(probe_resp, "_prefix", b"") or b""
        _dbg("MODE=%s url=%s size=%d" % (mode, _host_of(final_url), size))
        if mode == "multi":
            progress.total = size
            if _download_multipart(final_url, target, part, size, timeout, cancel_cb,
                                   expect_sha1, progress):
                return True
            # 该源的多线程作废 → 等价 PCL2 的"全部源降级为单线程"重试一次。
            # 注意: 单流兜底会**续传**已经落盘的 .part, 不会把整份文件重下一遍。
            _dbg("FALLBACK all-sources-single-thread url=%s keep_part=%s"
                 % (_host_of(final_url), os.path.isfile(part)))
        return _download_single(final_url, target, part, timeout, cancel_cb,
                                expect_sha1, progress, probe_resp,
                                prefix=probe_prefix, known_total=size)
    except _Cancelled:
        _silent_remove(part)
        return False
    except Exception:
        _silent_remove(part)
        return False


def _read_manifest_cache(path: str) -> Optional[dict]:
    """读取未过期的清单缓存。"""
    try:
        if not os.path.isfile(path):
            return None
        if time.time() - os.path.getmtime(path) > MANIFEST_TTL:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            return data
    except Exception:
        return None
    return None


def _write_manifest_cache(path: str, data: dict) -> None:
    """写入清单缓存, 失败忽略。"""
    try:
        ensure_dir(os.path.dirname(os.path.abspath(path)))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _fallback_manifest() -> dict:
    """把 catalog.vanilla_fallback() 转成 manifest 结构。"""
    fallback = catalog_mod.vanilla_fallback()
    latest = fallback.get("latest") if isinstance(fallback, dict) else {}
    latest = latest if isinstance(latest, dict) else {}
    versions = []  # type: List[dict]
    raw_versions = fallback.get("versions") if isinstance(fallback, dict) else []
    for item in (raw_versions or []):
        try:
            if isinstance(item, dict):
                versions.append({
                    "id": str(item.get("id") or ""),
                    "type": str(item.get("type") or "release"),
                    "time": str(item.get("time") or item.get("releaseTime") or ""),
                    "url": str(item.get("url") or ""),
                })
            elif isinstance(item, str):
                versions.append({"id": item, "type": "release", "time": "", "url": ""})
        except Exception:
            continue
    return {
        "latest": {
            "release": str(latest.get("release") or ""),
            "snapshot": str(latest.get("snapshot") or ""),
        },
        "versions": versions,
    }


def get_manifest(cfg=None, force: bool = False) -> dict:
    """获取版本清单: 优先缓存(TTL 1 小时), 失败回退内置 data/catalog.json。"""
    source = "official"
    if cfg is not None:
        try:
            source = str(cfg.get("download.list_source") or cfg.get("download.source") or "official")
        except Exception:
            source = "official"
    cache_path = os.path.join(str(cache_dir()), "version_manifest_v2.json")
    if not force:
        cached = _read_manifest_cache(cache_path)
        if cached is not None:
            return cached
    data = http_json(endpoint("manifest", source))
    if data is None and _is_mirror(source):
        data = http_json(endpoint("manifest", "official"))
    if not isinstance(data, dict) or not isinstance(data.get("versions"), list):
        return _fallback_manifest()
    _write_manifest_cache(cache_path, data)
    return data


def _time_is_april(time_text: str) -> bool:
    """时间字符串是否落在 4 月 1 日。"""
    match = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", str(time_text or ""))
    if not match:
        return False
    return match.group(2) == "04" and match.group(3) == "01"


def _is_april(entry: dict) -> bool:
    """判断一个 snapshot 是否为愚人节版本。"""
    ident = str(entry.get("id") or "").lower()
    if "april" in ident or "愚人" in ident:
        return True
    return _time_is_april(str(entry.get("time") or ""))


def _version_sort_key(ident: str):
    """把 "1.21.4" / "26.1.2" / "b1.7.3" 变成可比较的元组。"""
    nums = re.findall(r"\d+", str(ident or ""))
    return tuple(int(n) for n in nums[:4])


def vanilla_entries(manifest: dict) -> dict:
    """按类型整理清单: release / snapshot / old / april, 以及 latest 条目。"""
    out = {
        "release": [],
        "snapshot": [],
        "old": [],
        "april": [],
        "latest": {"release": None, "snapshot": None},
    }  # type: Dict[str, Any]
    versions = manifest.get("versions") if isinstance(manifest, dict) else []
    entries = []  # type: List[dict]
    for item in (versions or []):
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "")
        if not ident:
            continue
        entries.append({
            "id": ident,
            "type": str(item.get("type") or "release"),
            # 用 releaseTime(真正的发布时间)而不是 time(清单里那个"最后修改"时间),
            # 否则列表顺序会乱
            "time": str(item.get("releaseTime") or item.get("time") or ""),
            "url": str(item.get("url") or ""),
        })
    for entry in entries:
        etype = entry["type"]
        if etype == "release":
            out["release"].append(entry)
        elif etype in ("old_beta", "old_alpha", "old"):
            out["old"].append(entry)
        elif etype == "snapshot":
            if _is_april(entry):
                out["april"].append(entry)
            else:
                out["snapshot"].append(entry)
        else:
            out["snapshot"].append(entry)
    for key in ("release", "snapshot", "old"):
        try:
            # 先按版本号升序, 再按发布时间降序(稳定排序), 时间相同时保证版本号新的在前
            out[key].sort(key=lambda e: _version_sort_key(e.get("id") or ""))
            out[key].sort(key=lambda e: str(e.get("time") or ""), reverse=True)
        except Exception:
            pass
    latest = manifest.get("latest") if isinstance(manifest, dict) else {}
    latest = latest if isinstance(latest, dict) else {}
    for key in ("release", "snapshot"):
        ident = str(latest.get(key) or "")
        found = None  # type: Optional[dict]
        if ident:
            for entry in entries:
                if entry["id"] == ident:
                    found = entry
                    break
            if found is None:
                found = {
                    "id": ident,
                    "type": "release" if key == "release" else "snapshot",
                    "time": "",
                    "url": "",
                }
        elif out[key]:
            found = out[key][0]
        out["latest"][key] = found
    return out


def fetch_version_json(entry_url: str, source: str = "official") -> Optional[dict]:
    """下载某个版本的 json(自动应用镜像重写)。"""
    url = rewrite_url(str(entry_url or ""), source)
    if not url:
        return None
    data = http_json(url)
    return data if isinstance(data, dict) else None


def fabric_loader_versions(mc_version: str) -> List[dict]:
    """取指定 MC 版本可用的 Fabric 加载器版本列表(失败返回 [])。"""
    mc = str(mc_version or "").strip()
    if not mc:
        return []
    url = endpoint("fabric").rstrip("/") + "/v2/versions/loader/" + urllib.parse.quote(mc)
    data = http_json(url)
    result = []  # type: List[dict]
    if not isinstance(data, list):
        return result
    for item in data:
        try:
            if not isinstance(item, dict):
                continue
            loader = item.get("loader") if isinstance(item.get("loader"), dict) else {}
            version = str(loader.get("version") or "")
            if not version:
                continue
            result.append({"version": version, "stable": bool(loader.get("stable", False))})
        except Exception:
            continue
    return result


def fabric_profile_json(mc_version, loader_version) -> Optional[dict]:
    """取 Fabric 安装 profile(包含 libraries 与 mainClass)。"""
    mc = str(mc_version or "").strip()
    loader = str(loader_version or "").strip()
    if not mc or not loader:
        return None
    url = "%s/v2/versions/loader/%s/%s/profile/json" % (
        endpoint("fabric").rstrip("/"),
        urllib.parse.quote(mc),
        urllib.parse.quote(loader),
    )
    data = http_json(url)
    return data if isinstance(data, dict) else None


# ================================================================ 其它加载器
def _maven_versions(base: str, group: str, artifact: str) -> List[str]:
    """读 maven-metadata.xml 里的版本号列表(失败返回 [])。"""
    url = "%s/%s/%s/maven-metadata.xml" % (base.rstrip("/"),
                                           group.replace(".", "/"), artifact)
    try:
        request = _request(url)
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8", "ignore")
    except Exception:
        return []
    return re.findall(r"<version>([^<]+)</version>", text)


def quilt_loader_versions(mc_version: str) -> List[dict]:
    """Quilt 加载器版本列表(格式与 Fabric 一致)。"""
    mc = str(mc_version or "").strip()
    if not mc:
        return []
    url = endpoint("quilt").rstrip("/") + "/v3/versions/loader/" + urllib.parse.quote(mc)
    data = http_json(url)
    result = []  # type: List[dict]
    if not isinstance(data, list):
        return result
    for item in data:
        try:
            loader = item.get("loader") if isinstance(item.get("loader"), dict) else {}
            version = str(loader.get("version") or "")
            if version:
                result.append({"version": version, "stable": bool(loader.get("stable", False))})
        except Exception:
            continue
    return result


def quilt_profile_json(mc_version, loader_version) -> Optional[dict]:
    """Quilt 安装 profile。"""
    mc = str(mc_version or "").strip()
    loader = str(loader_version or "").strip()
    if not mc or not loader:
        return None
    url = "%s/v3/versions/loader/%s/%s/profile/json" % (
        endpoint("quilt").rstrip("/"), urllib.parse.quote(mc), urllib.parse.quote(loader))
    data = http_json(url)
    return data if isinstance(data, dict) else None


def forge_versions(mc_version: str) -> List[str]:
    """Forge 版本号列表(形如 47.2.0, 已按 MC 版本过滤, 新的在前)。

    官方 maven 的 maven-metadata.xml 很大且国内常常很慢, 所以优先用 BMCLAPI。
    """
    mc = str(mc_version or "").strip()
    if not mc:
        return []
    data = http_json("https://bmclapi2.bangbang93.com/forge/minecraft/"
                     + urllib.parse.quote(mc), timeout=15)
    versions = set()
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            value = str(item.get("version") or "").strip()
            if value:
                versions.add(value)
    if versions:
        return sorted(versions, key=_version_sort_key, reverse=True)

    prefix = mc + "-"
    listed = [v for v in _maven_versions(endpoint("forge"), "net.minecraftforge", "forge")
              if v.startswith(prefix)]
    listed.sort(key=lambda v: _version_sort_key(v[len(prefix):]), reverse=True)
    return [v[len(prefix):] for v in listed]


def forge_installer_url(mc_version: str, forge_version: str, source: str = "official") -> str:
    """Forge 安装器 jar 的下载地址。"""
    folder = "%s-%s" % (mc_version, forge_version)
    return "%s/net/minecraftforge/forge/%s/forge-%s-installer.jar" % (
        endpoint("forge", source).rstrip("/"), folder, folder)


def forge_installer_sha1(mc_version: str, forge_version: str) -> str:
    """Forge 安装器 jar 的 sha1(取不到返回空串)。"""
    folder = "%s-%s" % (mc_version, forge_version)
    url = "%s/net/minecraftforge/forge/%s/forge-%s-installer.jar.sha1" % (
        endpoint("forge").rstrip("/"), folder, folder)
    try:
        request = _request(url)
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", "ignore").strip().split()[0]
    except Exception:
        return ""


def neoforge_versions(mc_version: str) -> List[str]:
    """NeoForge 版本号列表(形如 21.1.233)。

    NeoForge 用自己的编号: MC 1.21.1 → NeoForge 21.1.x(去掉开头的 "1.")。
    官方 maven 在国内经常超时, 所以优先用 BMCLAPI 的列表接口。
    """
    mc = str(mc_version or "").strip()
    if not mc:
        return []
    data = http_json("https://bmclapi2.bangbang93.com/neoforge/list/"
                     + urllib.parse.quote(mc), timeout=15)
    versions = set()
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            # 1.20.1 的 NeoForge 是 net.neoforged:forge:forge-47.1.x, rawVersion 带前缀
            value = str(item.get("version") or "").strip()
            if not value:
                raw = str(item.get("rawVersion") or "").strip()
                value = re.sub(r"^(?:neo)?forge-", "", raw)
            if value:
                versions.add(value)
    if versions:
        return sorted(versions, key=_version_sort_key, reverse=True)

    parts = mc.split(".")
    if len(parts) >= 3 and parts[0] == "1":
        prefix = "%s.%s." % (parts[1], parts[2])
    elif len(parts) >= 2:
        prefix = "%s.%s." % (parts[0], parts[1])
    else:
        return []
    listed = [v for v in _maven_versions(endpoint("neoforge"), "net.neoforged", "neoforge")
              if v.startswith(prefix)]
    listed.sort(key=lambda v: _version_sort_key(v), reverse=True)
    return listed


def neoforge_installer_urls(loader_version: str) -> List[str]:
    """NeoForge 安装器 jar 的候选地址(BMCLAPI 镜像在前)。"""
    version = str(loader_version or "").strip()
    return [
        "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/%s/"
        "neoforge-%s-installer.jar" % (version, version),
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/%s/"
        "neoforge-%s-installer.jar" % (version, version),
    ]


def neoforge_installer_url(loader_version: str, source: str = "official") -> str:
    """NeoForge 安装器 jar 的下载地址(取第一个候选)。"""
    return neoforge_installer_urls(loader_version)[0]


def forge_installer_urls(mc_version: str, forge_version: str) -> List[str]:
    """Forge 安装器 jar 的候选地址(BMCLAPI 镜像在前)。"""
    folder = "%s-%s" % (mc_version, forge_version)
    return [
        "https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge/%s/"
        "forge-%s-installer.jar" % (folder, folder),
        "%s/net/minecraftforge/forge/%s/forge-%s-installer.jar" % (
            endpoint("forge").rstrip("/"), folder, folder),
    ]


def optifine_versions(mc_version: str) -> List[str]:
    """OptiFine 版本列表(形如 ``HD_U_I5``, 新的在前)。"""
    mc = str(mc_version or "").strip()
    if not mc:
        return []
    data = http_json("https://bmclapi2.bangbang93.com/optifine/" + urllib.parse.quote(mc),
                     timeout=15)
    result = []  # type: List[str]
    if not isinstance(data, list):
        return result
    for item in data:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip()
        patch = str(item.get("patch") or "").strip()
        if kind and patch:
            result.append("%s_%s" % (kind, patch))
    return result


def optifine_installer_urls(mc_version: str, version: str) -> List[str]:
    """OptiFine 安装包的候选下载地址。"""
    mc = str(mc_version or "").strip()
    text = str(version or "").strip()
    if "_" not in text:
        return []
    kind, _, patch = text.partition("_")
    name = "OptiFine_%s_%s_%s.jar" % (mc, kind, patch)
    return [
        "https://bmclapi2.bangbang93.com/optifine/%s/%s/%s" % (mc, kind, patch),
        "https://bmclapi2.bangbang93.com/optifine/%s/%s" % (mc, name),
        "https://optifine.net/downloadx?f=%s" % name,
    ]


# ================================================================ Modrinth
# Modrinth 搜索 facet `project_type:<值>` 的合法取值(插件/服务端核心也算一类)。
MODRINTH_KINDS = {
    "mod": "mod",
    "modpack": "modpack",
    "datapack": "datapack",
    "resourcepack": "resourcepack",
    "shader": "shader",
    "plugin": "plugin",
}

# 叫法对照: 界面/调用方写成复数、下划线、连字符或习惯叫法时也认。
# ⚠️ 以前缺这一层, 对不上 MODRINTH_KINDS 的写法会被**静默**当成 mod:
# kind="texturepack"/"resourcepacks"/"shaderpack"/"modpacks" 都会去搜
# `project_type:mod`, 于是资源包页里列出一堆 Mod —— 有结果, 但类型全错, 还不报错。
_KIND_ALIASES = {
    "mods": "mod",
    "modpacks": "modpack",
    "datapacks": "datapack",
    "resourcepacks": "resourcepack",
    "texturepack": "resourcepack",
    "texturepacks": "resourcepack",
    "shaderpack": "shader",
    "shaderpacks": "shader",
    "shaders": "shader",
    "plugins": "plugin",
}

# "不筛选"的各种写法(界面上的"全部"最容易漏进来: 加载器那一栏后端会先过滤掉,
# 版本那一栏以前不过滤, 于是一个"全部"就让搜索**静默返回 0 条**)。
_ANY_FILTER = frozenset(["", "all", "any", "none", "-", "*",
                         "全部", "不限", "所有", "任意"])

# facet 值只能是 ASCII 标签(版本号 / 加载器名)。中文、带空格的值放进去不会报错,
# 只会让 Modrinth 静默返回 0 条, 所以这类值一律当"不筛选"处理。
_FACET_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")

_LOADER_FACET = {
    "fabric": "fabric",
    "quilt": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}


def normalize_kind(kind: str) -> str:
    """把写法五花八门的资源类型统一成 Modrinth 的 project_type(空串 = 不认识)。"""
    text = str(kind or "").strip().lower()
    if not text:
        return ""
    # "resource_pack" / "resource-pack" / "ResourcePack" → "resourcepack"
    key = re.sub(r"[\s_\-]+", "", text)
    if key in MODRINTH_KINDS:
        return key
    return _KIND_ALIASES.get(key, "")


def facet_value(value) -> str:
    """整理一个 facet 过滤值: 表示"不筛选"或不可能命中时返回空串(调用方跳过该 facet)。"""
    text = str(value or "").strip()
    if text.lower() in _ANY_FILTER:
        return ""
    if not _FACET_TOKEN_RE.match(text):
        return ""
    return text


def modrinth_search(kind: str = "mod", query: str = "", mc_version: str = "",
                    loader: str = "", project_type: str = "", limit: int = 20,
                    offset: int = 0, source: str = "all") -> dict:
    """搜索 Modrinth 项目。

    返回 ``{"hits": [...], "total": int, "error": str}``; hits 里每项已整理成界面
    需要的字段(标题/作者/简介/下载量/更新时间/来源/图标/项目 id 等)。

    facet 规则(每条都对应一个真实踩过的坑):
      * ``project_type:`` 只用合法取值; 不认识的 kind **明确报错**, 不再悄悄按 mod 搜;
      * ``versions:`` 只在值真的像一个版本号时才加 —— "全部"/"all"/中文值一律当不筛选,
        否则 Modrinth 会静默返回 0 条(搜索框里一个"全部"就能让整页空白);
      * ``categories:``(加载器)同理, 空/占位符不进 facet。
    """
    result = {"hits": [], "total": 0, "error": ""}  # type: dict
    raw_kind = str(kind or "").strip()
    kind_key = normalize_kind(raw_kind)
    if not kind_key:
        if raw_kind:
            result["error"] = "不认识的资源类型：%s" % raw_kind
            return result
        kind_key = "mod"
    wanted_type = facet_value(project_type) or MODRINTH_KINDS[kind_key]
    facets = [["project_type:%s" % wanted_type]]
    mc = facet_value(mc_version)
    if mc:
        facets.append(["versions:%s" % mc])
    if kind_key in ("mod", "modpack"):
        loader_key = str(loader or "").strip().lower()
        token = facet_value(_LOADER_FACET.get(loader_key, loader_key))
        if token:
            facets.append(["categories:%s" % token])
    params = {
        "limit": max(1, min(50, int(limit))),
        "offset": max(0, int(offset)),
        "query": str(query or ""),
        "facets": json.dumps(facets, ensure_ascii=False),
        "index": "relevance" if query else "downloads",
    }
    url = endpoint("modrinth").rstrip("/") + "/search?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=20)
    if not isinstance(data, dict):
        result["error"] = "无法连接 Modrinth(检查网络或下载源)"
        return result
    hits = data.get("hits")
    result["total"] = int(data.get("total_hits") or 0)
    if not isinstance(hits, list):
        return result
    for item in hits:
        if not isinstance(item, dict):
            continue
        try:
            result["hits"].append({
                "id": str(item.get("project_id") or item.get("slug") or ""),
                "slug": str(item.get("slug") or ""),
                "title": str(item.get("title") or ""),
                "author": str(item.get("author") or ""),
                "description": str(item.get("description") or ""),
                "downloads": int(item.get("downloads") or 0),
                "follows": int(item.get("follows") or 0),
                "updated": str(item.get("date_modified") or "")[:10],
                "icon": str(item.get("icon_url") or ""),
                "categories": [str(c) for c in (item.get("categories") or [])][:4],
                # ⚠️ 这里以前还多一层 [:3]: 项目支持 4 个以上加载器时, 列表上的"加载器"
                # 信息被**静默**砍掉一半, 界面上完全看不出来(数据已经没了, 谁也补不回来)。
                # 加载器的可能取值本来就那么几个, 全量保留 —— 该缩写的是展示层, 不是数据层。
                "loaders": [str(c) for c in (item.get("categories") or [])
                            if str(c).lower() in
                            ("fabric", "forge", "neoforge", "quilt", "iris", "optifine")],
                "versions": [str(v) for v in (item.get("versions") or [])][-3:],
                "source": "Modrinth",
            })
        except Exception:
            continue
    return result


def modrinth_versions(project_id: str, mc_version: str = "", loader: str = "",
                      kind: str = "mod") -> List[dict]:
    """某个项目可下载的文件版本列表(已按 MC 版本/加载器过滤, 新的在前)。

    过滤值同样先过 ``facet_value``: ``game_versions=["全部"]`` / ``loaders=["全部"]``
    这类查询会让 Modrinth 返回**空列表**(详情页于是显示"没有匹配当前版本/加载器的
    文件"), 所以"全部"这类值当作不筛选取掉, kind/loader 也按别名归一化。
    """
    pid = str(project_id or "").strip()
    if not pid:
        return []
    kind_key = normalize_kind(kind) or "mod"
    params = {}  # type: dict
    mc = facet_value(mc_version)
    if mc:
        params["game_versions"] = json.dumps([mc])
    if kind_key in ("mod", "modpack"):
        loader_key = str(loader or "").strip().lower()
        token = facet_value(_LOADER_FACET.get(loader_key, loader_key))
        if token:
            params["loaders"] = json.dumps([token])
    url = endpoint("modrinth").rstrip("/") + "/project/" + urllib.parse.quote(pid) + "/version"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=20)
    files = []  # type: List[dict]
    if not isinstance(data, list):
        return files
    for item in data:
        if not isinstance(item, dict):
            continue
        for entry in (item.get("files") or []):
            if not isinstance(entry, dict):
                continue
            url_file = str(entry.get("url") or "")
            if not url_file:
                continue
            files.append({
                "name": str(item.get("name") or ""),
                "version": str(item.get("version_number") or ""),
                "file": str(entry.get("filename") or ""),
                "url": url_file,
                "size": int(entry.get("size") or 0),
                "primary": bool(entry.get("primary", False)),
                # 同上: 这里以前是 [:3], 支持 4 个以上加载器的版本文件会被悄悄截短,
                # 详情页因此**永远**显示不出第 3 个以后的加载器(B5)。数据层不再截断。
                "loaders": [str(x) for x in (item.get("loaders") or [])],
                "game_versions": [str(x) for x in (item.get("game_versions") or [])][:3],
                "date": str(item.get("date_published") or "")[:10],
                "downloads": int(item.get("downloads") or 0),
            })
            break     # 每个版本只取第一个文件(通常是主文件)
    return files
