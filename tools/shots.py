"""开发用截图脚本: 把各个界面渲染成 PNG, 便于和设计稿比对。

现在所有菜单都在同一个窗口里, 截图时通过窗口自带的导航函数切换页面。

用法::

    python main.py --shot shots

截图全部在屏幕外完成(窗口移到 -4000,-4000 再抓图), 不会打断正常使用。

场景表 ``PAGES`` 的每一项是::

    {"name": 输出文件名(不含 .png),
     "fn":   窗口上的导航函数名,
     "args": 传给导航函数的参数,
     "setup":  可选, 导航前执行的函数 ``fn(window) -> bool``(False 表示跳过本页),
     "settle": 可选, 抓图前等待的判定函数 ``fn(window) -> bool``
               (资源详情页要等异步文件列表回来, 否则只会拍到"正在获取…"的空页),
     "wait_ms": settle 轮询的最长等待时间}

新增的资源详情场景(Mods / 数据包)走的是窗口既有的
``openResourceDetail(项目id, 标题, 图标)`` 入口 —— 与界面里点击列表项完全同一条路径。
**离线时**这些场景会优雅降级: 拿不到文件列表时 ``detailGroups`` 为空, 页面显示
"没有匹配当前版本/加载器的文件"而不是报错, 截图照常保存(见 ``_detail_ready``)。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEventLoop, QTimer

# 资源详情场景要用的分类(与下载页的分类 key 一致)
DETAIL_MOD_KIND = "mod"
DETAIL_DATAPACK_KIND = "datapack"

# "文件列表正在获取"时状态栏的前缀(ResourcesBackend.openProjectById 写入;
# 一旦它被改写就说明异步请求结束了 —— 离线时用来提前结束等待)
_DETAIL_LOADING_PREFIX = "正在获取"

# capture() 时填入的社区资源后端, 供场景的 setup/settle 使用
_community = None


def _pump(milliseconds: int = 320) -> None:
    """等待界面布局与动画完成。"""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _community_of(window):
    """拿到注入 QML 上下文的社区资源后端(community)。

    ``community`` 是 QML 上下文属性, 不是窗口上的 Python 属性; capture() 会把
    launcher.resources 记在 ``_community`` 上, 这里优先用它, 取不到时再退回
    QQmlEngine 的上下文查询(只为容错, 正常路径不会走到)。
    """
    if _community is not None:
        return _community
    try:
        from PySide6.QtQml import QQmlEngine

        context = QQmlEngine.contextForObject(window)
        if context is not None:
            return context.contextProperty("community")
    except Exception:  # noqa: BLE001
        pass
    return None


def _set_detail_kind(window, kind: str) -> bool:
    """设置社区资源的当前分类。取不到社区对象时返回 False(本页跳过, 不影响其它页)。"""
    community = _community_of(window)
    if community is None:
        print("SKIP detail kind=%s: community backend unavailable" % kind)
        return False
    try:
        community.setKind(kind)
    except Exception as exc:  # noqa: BLE001
        print("SKIP detail kind=%s: %s" % (kind, exc))
        return False
    _pump(200)
    return True


def _prepare_mod_detail(window) -> bool:
    """把详情的分类切到 Mods(openResourceDetail 按当前分类决定取哪一类文件)。"""
    return _set_detail_kind(window, DETAIL_MOD_KIND)


def _prepare_datapack_detail(window) -> bool:
    """把详情的分类切到数据包(才会有「客户端 / 服务端」两个大类 + 跳转条)。"""
    return _set_detail_kind(window, DETAIL_DATAPACK_KIND)


def _detail_ready(window) -> bool:
    """资源详情页是否可以抓图了。

    * 有内容(``detailGroups`` 非空) → 立刻抓;
    * **离线 / 网络失败**: 后端不会给出任何分组, 这时状态栏会被改写成
      "「X」没有匹配当前版本/加载器的文件"(见 ``ResourcesBackend._on_files_done``),
      也就是**异步请求已经结束**了 —— 这时也直接抓(拍到空状态页),
      不必空等满 ``wait_ms``, 后面的场景不会被拖住。
    * 请求还在飞(状态栏仍是 "正在获取…") → 返回 False 继续等。
    """
    community = _community_of(window)
    if community is None:
        return False
    try:
        if community.detailGroups:
            return True
        status = str(community.statusText or "")
    except Exception:  # noqa: BLE001
        return False
    return not status.startswith(_DETAIL_LOADING_PREFIX)


def _wait_for(predicate, window, timeout_ms: int, step_ms: int = 250) -> bool:
    """轮询等待异步加载, 超时也返回, 不抛异常。"""
    waited = 0
    while waited < timeout_ms:
        try:
            if predicate(window):
                return True
        except Exception:  # noqa: BLE001
            pass
        _pump(step_ms)
        waited += step_ms
    return False


# 每个场景: (名称, 导航函数名, 参数)。前 12 项是原有的六个页面(含二级/三级菜单),
# 输出文件名保持不变; 后面两项是新增的社区资源详情页。
PAGES = [
    {"name": "home", "fn": "setPage", "args": [0]},
    {"name": "download", "fn": "setPage", "args": [1]},
    {"name": "settings", "fn": "setPage", "args": [2]},
    {"name": "settings-personalization", "fn": "showSettingsSection", "args": [1]},
    {"name": "settings-other", "fn": "showSettingsSection", "args": [2]},
    {"name": "version-select", "fn": "openVersionSelect", "args": []},
    {"name": "version-settings-overview", "fn": "showVersionSettingsSection", "args": [0]},
    {"name": "version-settings-config", "fn": "showVersionSettingsSection", "args": [1]},
    {"name": "version-settings-mods", "fn": "showVersionSettingsSection", "args": [2]},
    {"name": "version-settings-export", "fn": "showVersionSettingsSection", "args": [3]},
    {"name": "tasks", "fn": "openTasks", "args": []},
    {"name": "log", "fn": "openLog", "args": []},

    # ------------------------------------------------------------ 社区资源详情页
    # Mods 详情(sodium, Modrinth 项目 id AANobbMI): 客户端大类 → 加载器 → 适配版本 → 文件
    {"name": "resource-detail-mod-sodium",
     "fn": "openResourceDetail",
     "args": ["AANobbMI", "Sodium", ""],
     "setup": _prepare_mod_detail,
     "settle": _detail_ready,
     "wait_ms": 20000},
    # 数据包详情(terralith, Modrinth 项目 id 8oi3bsk5):
    # 顶部跳转条 + 「客户端 / 服务端」两个大类(UI 改动最多的一页)
    {"name": "resource-detail-datapack-terralith",
     "fn": "openResourceDetail",
     "args": ["8oi3bsk5", "Terralith", ""],
     "setup": _prepare_datapack_detail,
     "settle": _detail_ready,
     "wait_ms": 20000},
]


def capture(launcher, out_dir: str) -> list:
    global _community
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    window = launcher.window
    saved = []
    _community = getattr(launcher, "resources", None)

    # 截图时如果本机没装版本, 用内置示例数据把界面填满(不影响真实使用)
    if launcher.backend.versionCount == 0:
        launcher.backend.cfg.set("use_demo_data", True)
        launcher.backend.reloadVersions()
        _pump(900)

    # 等版本列表加载完成(有网络时会拉官方列表, 最多等 25 秒)
    launcher.download.refresh()
    waited = 0
    while launcher.download.loading and waited < 25000:
        _pump(250)
        waited += 250

    # 尽量挑一个装有 Mod 的版本, 便于展示 Mod 管理页
    best = _version_with_mods(launcher)
    if best:
        launcher.backend.selectVersion(best)
        _pump(200)

    # 造一个"进行中"的下载任务, 让任务页和右下角悬浮按钮有内容可看
    _fake_download_task(launcher)

    window.setPosition(-4000, -4000)
    window.show()
    _pump(600)

    for page in PAGES:
        name = page["name"]
        setup = page.get("setup")
        if setup is not None:
            try:
                if not setup(window):
                    print("skip page %s (setup returned False)" % name)
                    continue
            except Exception as exc:  # noqa: BLE001
                print("skip page %s (setup failed: %s)" % (name, exc))
                continue
        try:
            getattr(window, page["fn"])(*page.get("args", []))
        except Exception as exc:  # noqa: BLE001
            print("导航到 %s 失败: %s" % (name, exc))
            continue
        _pump(700)
        settle = page.get("settle")
        if settle is not None:
            _wait_for(settle, window, int(page.get("wait_ms", 20000)))
            _pump(400)          # 等折叠动画/列表布局稳定
        path = os.path.join(out_dir, "%s.png" % name)
        window.grabWindow().save(path, "PNG")
        saved.append(path)

    # 收尾: 关掉资源详情(清空 detailGroups)。截图已经全部完成, 这一步只影响
    # 退出阶段 —— 详情页的绑定在关窗销毁时 context 属性已经变成 null,
    # 会额外刷出 "Cannot read property 'detailGroups' of null" 这类噪音。
    _close_detail(window)

    for path in saved:
        print("saved:", path)
    return saved


def _close_detail(window) -> None:
    """截图结束后清掉资源详情的内容(失败忽略, 不影响已保存的截图)。"""
    community = _community_of(window)
    if community is None:
        return
    try:
        community.closeDetail()
    except Exception:  # noqa: BLE001
        pass


def _version_with_mods(launcher):
    """找一个 Mod 数量最多的已安装版本(截图用)。"""
    try:
        from pclpy.core import mods as core_mods
        best, best_count = "", 0
        for ver in getattr(launcher.backend, "_versions", []):
            if not ver.path:
                continue
            folder = core_mods.mods_dir_for(ver.path, launcher.backend.root(), True)
            count = len(core_mods.list_mods(folder))
            if count > best_count:
                best, best_count = ver.id, count
        return best
    except Exception:  # noqa: BLE001
        return ""


def _fake_download_task(launcher) -> None:
    """构造一个假的下载任务(仅用于截图, 不产生任何真实下载)。"""
    try:
        from pclpy.backend.launcher import INSTALL_STEPS
        backend = launcher.backend
        task = backend._new_task("26.4-snapshot-3 安装", "install", INSTALL_STEPS, None)
        backend._on_task_progress(task, "资源文件 637/1500", 77)
        backend._on_task_phase(task, "json", 100, "")
        backend._on_task_phase(task, "client", 100, "")
        backend._on_task_phase(task, "libraries", 95, "下载原版支持库文件")
        backend._on_task_phase(task, "assets", 69, "下载原版资源文件")
        task["percent"] = 77
        task["speed"] = 6.4 * 1024 * 1024
        task["speedText"] = "6.4 M/s"
        task["remaining"] = 863
        task["remainingText"] = "863"
        backend._update_task(task)
    except Exception:  # noqa: BLE001
        pass
