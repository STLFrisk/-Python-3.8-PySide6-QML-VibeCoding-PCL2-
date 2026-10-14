"""社区资源(Mod / 整合包 / 数据包 / 资源包 / 光影包)的搜索与安装。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

from . import remote
from .paths import download_dir, ensure_dir, safe_name

# 资源种类 → 启动器目录下 Download/ 里的子文件夹
KIND_FOLDERS = {
    "mod": "Mods",
    "resourcepack": "ResourcePacks",
    "shader": "ShaderPacks",
    "datapack": "DataPacks",
    "modpack": "ModPacks",
}

KIND_LABELS = {
    "mod": "Mod",
    "modpack": "整合包",
    "datapack": "数据包",
    "resourcepack": "资源包",
    "shader": "光影包",
}


def search(kind: str, query: str = "", mc_version: str = "", loader: str = "",
           source: str = "all", limit: int = 20, offset: int = 0) -> dict:
    """搜索社区资源(目前走 Modrinth; CurseForge 需要 API Key)。"""
    kind_key = str(kind or "mod").lower()
    if str(source).lower() in ("curseforge", "cf"):
        return {"hits": [], "total": 0,
                "error": "CurseForge 需要 API Key，当前使用 Modrinth 源"}
    return remote.modrinth_search(kind_key, query, mc_version, loader, limit=limit,
                                  offset=offset, source=source)


def project_files(project_id: str, kind: str, mc_version: str = "",
                  loader: str = "") -> List[dict]:
    """某个资源可下载的文件列表。"""
    return remote.modrinth_versions(project_id, mc_version, loader, kind)


def target_dir(game_dir: str, kind: str) -> str:
    """资源保存到 **启动器目录** 下的 ``Download/<类型>``。

    (不再放进版本目录 —— 打包成 exe 后就是 exe 同级的 Download 文件夹,
    用户可以自己复制进任意版本的 mods / resourcepacks 等目录。)
    """
    return download_dir(str(kind or "mod").lower())


def install_file(url: str, filename: str, game_dir: str, kind: str, source: str = "official",
                 progress_cb=None, cancel_cb=None) -> str:
    """把资源文件下载到对应目录, 返回落盘路径。"""
    name = safe_name(os.path.basename(str(filename or "")) or "download.jar")
    folder = target_dir(game_dir, kind)
    dest = os.path.join(folder, name)
    ensure_dir(os.path.dirname(dest))
    if not remote.download_file(url, dest, source=source, progress_cb=progress_cb,
                                cancel_cb=cancel_cb):
        raise RuntimeError("下载失败: %s" % url)
    return dest


# ================================================================ 整合包
def _read_index(archive: str) -> Optional[dict]:
    """读取 .mrpack 里的 modrinth.index.json。"""
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name.lower().endswith("modrinth.index.json"):
                    return json.loads(zf.read(name).decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return None
    return None


def modpack_loader(index: dict) -> Dict[str, str]:
    """从整合包索引里推断需要的加载器与 MC 版本。"""
    result = {"mc_version": "", "loader": "", "loader_version": ""}
    deps = index.get("dependencies") if isinstance(index, dict) else None
    if not isinstance(deps, dict):
        return result
    for key, value in deps.items():
        name = str(key).lower()
        if name == "minecraft":
            result["mc_version"] = str(value)
        elif name in ("fabric-loader", "quilt-loader", "forge", "neoforge"):
            result["loader"] = name.replace("-loader", "")
            result["loader_version"] = str(value)
    return result


LOADER_TITLES = {"fabric": "Fabric", "quilt": "Quilt",
                 "forge": "Forge", "neoforge": "NeoForge"}


def _has_version(root: str, version_id: str) -> bool:
    if not version_id:
        return False
    folder = os.path.join(str(root), "versions", version_id)
    return os.path.isfile(os.path.join(folder, version_id + ".json"))


def _find_loader_version(root: str, loader: str, loader_version: str) -> str:
    """在已安装版本里找这个加载器/版本(命名规则各家不同, 所以按名字搜)。"""
    versions_dir = os.path.join(str(root), "versions")
    if not os.path.isdir(versions_dir) or not loader_version:
        return ""
    title = LOADER_TITLES.get(loader, loader).lower()
    key = str(loader).lower()
    for name in sorted(os.listdir(versions_dir)):
        low = name.lower()
        if loader_version.lower() not in low:
            continue
        if title in low or key in low:
            if _has_version(root, name):
                return name
    return ""


# PCL2 整合包安装步骤顺序(ModModpack.vb:408 起 + ModDownloadLib.vb:1855 起的 McInstallLoader):
#   解压整合包文件 → 下载额外文件 → 下载原版 json → 下载原版支持库 → 下载原版资源文件
#   → 获取/下载 Forge(Fabric/NeoForge)详细信息与主文件 → 分析/下载加载器支持库 → 安装加载器
#   → 安装游戏 → 下载游戏支持库
# 括号里是 install.py 里对应阶段回调用到的 **原始 stage id**。
_MODPACK_LOADER_STAGE_TEXT = {
    "prepare": "获取/下载加载器详细信息与主文件",
    "json": "写入加载器版本 json",
    "libraries": "分析/下载加载器支持库",
    "client": "下载加载器主文件",
    "done": "安装加载器",
}


def _modpack_phase_relay(phase_cb):
    """把 install.py 加载器安装阶段回调"翻译"成 PCL2 的整合包步骤文案。

    ``done`` 阶段被**吃掉**: install_vanilla / install_fabric 结束时会报 ``done``,
    而任务页收到 ``done`` 会把整条任务的所有步骤直接标成完成(launcher.py:414)。
    整合包安装后面还有"安装游戏/下载游戏支持库", 不能在这里提前收工。
    """
    if not callable(phase_cb):
        return None

    def _relay(phase_id, percent, text=""):
        pid = str(phase_id or "")
        if pid == "done":
            return
        label = _MODPACK_LOADER_STAGE_TEXT.get(pid, text or "")
        _phase_emit(phase_cb, pid, percent, label or text)

    return _relay


def _forge_watch_matcher(mc_version: str):
    """返回"这个目录名像不像**本次**安装器要产出的版本目录"的判定函数。

    单独拎出来只为一件事: 起监视的那次扫描、收尾时的补扫必须用**同一套**判定。
    两处各写一遍必然漂移, 一漂移不是漏清(占位残留 → 装好的版本在列表里消失),
    就是误清(把调用前就存在的目录给清了)。
    """
    mc = str(mc_version or "").lower()

    def _looks_like_this_loader(name: str) -> bool:
        low = str(name or "").lower()
        if "forge" not in low:               # neoforge 里也含 "forge"
            return False
        return (not mc) or (mc in low)

    return _looks_like_this_loader


def _forge_watch_new_dirs(state: dict) -> List[str]:
    """扫一遍 ``versions/``, 返回"调用前不存在、名字像本次安装器产出、且真的是目录"的名字。

    **纯扫描, 没有任何副作用**(不写占位): 写占位这件事由调用方决定 ——
    监视循环(安装进行中)标上占位, 收尾补扫则只是"扫出来清掉"。
    """
    if not isinstance(state, dict):
        return []
    root = str(state.get("root") or "")
    snapshot = state.get("snapshot") or set()
    marked = state.get("marked") or []
    matcher = state.get("matcher")
    if not callable(matcher):
        return []
    versions_root = os.path.join(root, "versions")
    try:
        names = list(os.listdir(versions_root))
    except OSError:
        return []
    found = []  # type: List[str]
    for name in names:
        if name in snapshot or name in marked:
            continue
        if not matcher(name):
            continue
        if not os.path.isdir(os.path.join(versions_root, name)):
            continue
        found.append(name)
    return found


def _start_forge_placeholder_watch(root: str, loader: str, mc_version: str,
                                   interval: float = 0.4) -> dict:
    """给 Forge / NeoForge 补写 ``.pclpy_installing`` 占位 —— **目录监视**版(B4)。

    为什么不能在调用前写: 这两个加载器的版本 id 是**安装器自己生成**的
    (``versions/<mc>-forge-<版本>/``), 调用前算不出来 —— ``install_forge_like``
    自己也是装完才用 ``after - before`` 的目录差找出它(install.py:798/841/861)。

    为什么要在"安装器刚产出目录"时写: 安装器要跑几十秒到几分钟, 期间它已经建出了
    ``versions/<新 id>/`` 但 json 还没写完 —— 这一段时间版本列表会把半成品当正常版本
    列出来(点一下必炸); 安装器中途失败/被取消时更是留下半成品目录。占了位之后
    扫描器会跳过它, ``cleanup_unfinished()`` 也能把它清掉。

    做法: 调用安装器**之前**给 versions/ 拍快照, 起一个后台线程盯着新出现的目录;
    名字对得上(含 forge / neoforge, 且含本次的 MC 版本号)就立刻 ``mark_installing``。
    只标记"安装期间新出现的目录", 绝不碰调用前就存在的版本; 只标记我们自己标过的,
    收尾时也只清我们自己写的那些(``clear_installing`` 是幂等的)。

    返回一个状态字典, 交给 :func:`_finish_forge_placeholder_watch` 收尾。
    """
    from . import install as install_mod      # _loop 闭包里要用(mark_installing)
    import threading

    versions_root = os.path.join(str(root), "versions")
    snapshot = set()  # type: set
    try:
        if os.path.isdir(versions_root):
            snapshot = set(os.listdir(versions_root))
    except OSError:
        snapshot = set()
    state = {"root": str(root), "stop": threading.Event(), "thread": None, "marked": [],
             "snapshot": snapshot, "matcher": _forge_watch_matcher(mc_version)}

    def _loop() -> None:
        while True:
            if state["stop"].is_set():
                return
            try:
                for name in _forge_watch_new_dirs(state):
                    if state["stop"].is_set():
                        return
                    install_mod.mark_installing(state["root"], name)
                    state["marked"].append(name)
            except Exception:  # noqa: BLE001   监视失败绝不能影响安装本身
                pass
            state["stop"].wait(interval)

    try:
        thread = threading.Thread(target=_loop)
        thread.daemon = True
        thread.start()
        state["thread"] = thread
    except Exception:  # noqa: BLE001
        state["thread"] = None
    return state


def _finish_forge_placeholder_watch(state: dict, version_id: str = "",
                                    ok: bool = False) -> List[str]:
    """收尾 Forge/NeoForge 的占位监视: 返回被我们标记/清除过的版本 id 列表。

    ``ok=True``(安装器成功、版本 json 真的落盘了) → 停线程, 并把**我们自己写的**占位
    全部清掉(``clear_installing``), 保证成功路径上不留占位。
    ``ok=False``(安装器报错 / 被取消) → **故意保留**占位: 扫描器会隐藏这个半成品,
    ``cleanup_unfinished()`` 之后能按"有占位 + 无用户数据"把它清掉。

    B4': 旧写法是"**先**抓一份 ``marked`` 快照, 再去 join 线程", 于是有一个 <400ms 的
    残留窗口 —— 监视线程可能刚好在快照之后、退出之前又标了一个目录(它进 for 循环时
    stop 还没置位), 这个占位谁也清不掉, 装好的 Forge 版本就在列表里消失到下次安装为止。
    现在改成**先 join 再取清单**, 并且停稳之后再补扫一次 ``versions/``:
    补扫只清(不写占位), 所以"最后一次轮询之后才出现"的目录即便已经有占位也会被清掉,
    而调用前就存在的目录(在 snapshot 里)永远不在清除名单里。
    """
    from . import install as install_mod

    if not isinstance(state, dict):
        return []
    stop = state.get("stop")
    try:
        if stop is not None:
            stop.set()
    except Exception:  # noqa: BLE001
        pass
    thread = state.get("thread")
    root = str(state.get("root") or "")
    cleared = []  # type: List[str]
    if ok:
        # ① 先让监视线程**彻底停下**: 它只要还在跑, 就可能在我们取清单之后又标一个目录。
        for _ in range(3):
            if thread is not None and thread.is_alive():
                try:
                    thread.join(timeout=1.0)
                except Exception:  # noqa: BLE001
                    pass
            if thread is None or not thread.is_alive():
                break
        # ② 线程停稳后再扫一次 versions/(**纯扫描**, 不写占位): 补上"最后一次轮询之后、
        #    线程退出之前"才出现的目录 —— 它要么没被标过(无事可做), 要么标了却没进
        #    线程的 marked 清单(这里的清就是唯一一次机会)。
        for name in _forge_watch_new_dirs(state):
            install_mod.clear_installing(root, name)
            cleared.append(str(name))
        # ③ 线程自己标过的那些(此时清单已不会再变)照旧全清。
        for name in list(state.get("marked") or []):
            install_mod.clear_installing(root, str(name))
            cleared.append(str(name))
        if version_id:
            install_mod.clear_installing(root, str(version_id))
            cleared.append(str(version_id))
    marked = [str(name) for name in (state.get("marked") or [])]
    out = []  # type: List[str]
    for name in marked + cleared:             # 去重保序: 标记过的 + 补扫清掉的
        if name not in out:
            out.append(name)
    return out


def ensure_modpack_parent(info: Dict[str, str], root: str, cfg=None,
                          progress_cb=None, cancel_cb=None, phase_cb=None) -> str:
    """确保整合包需要的**原版 + 模组加载器**都装好了, 返回可用的 inheritsFrom。

    这一步以前是缺的: 整合包只写了继承关系, 但对应的加载器版本根本没装,
    启动时启动器找不到父版本 → 只能当纯原版启动(整包里的 Mod 一个都不生效)。
    """
    from . import install as install_mod

    mc = str(info.get("mc_version") or "").strip()
    loader = str(info.get("loader") or "").strip().lower()
    loader_version = str(info.get("loader_version") or "").strip()
    parent = mc if _has_version(root, mc) else ""
    # 把原版安装内部的阶段(json/client/libraries/assets/natives)透传给任务页
    relay = _modpack_phase_relay(phase_cb)

    if mc and not parent:
        # PCL2 这一步的步骤名是"下载原版 json 文件"; 原版安装内部的 json 阶段会用
        # 同样的名字继续报进度。这里**只报 json, 不报 prepare** —— prepare 早就完成
        # ("解压整合包文件"), 再报一次会把界面上的已完成步骤打回"进行中"。
        _phase_emit(phase_cb, "json", 0, "下载原版 json 文件")
        if progress_cb:
            progress_cb(2, "安装整合包需要的原版 %s" % mc)
        parent = install_mod.install_vanilla(mc, root, cfg, cancel_cb=cancel_cb,
                                             phase_cb=relay)
        parent = parent or mc
    elif mc:
        # 原版已经有了 → json / 客户端 / 支持库 / 资源文件都当已完成(PCL2 也是跳过)
        for pid, text in (("json", "下载原版 json 文件"),
                          ("client", "下载客户端 jar"),
                          ("libraries", "下载原版支持库文件"),
                          ("assets", "下载原版资源文件"),
                          ("natives", "解压本地库")):
            _phase_emit(phase_cb, pid, 100, text)

    if not loader or not loader_version:
        return parent

    candidate = "%s-%s_%s" % (mc, LOADER_TITLES.get(loader, loader.title()), loader_version)
    installed = candidate if _has_version(root, candidate) else ""
    if not installed:
        installed = _find_loader_version(root, loader, loader_version)
    if installed:
        # 加载器本来就有 → 老界面的 "deps" 步骤也要收尾(否则它会停在 20% 不动)
        _phase_emit(phase_cb, "deps", 100, "模组加载器已就绪")
        _phase_emit(phase_cb, "loader", 100, "安装加载器")
        return installed

    if mc:
        loader_title = LOADER_TITLES.get(loader, loader)
        if phase_cb:
            # "deps" 是任务页 MODPACK_STEPS 里已有的 id(显示"安装原版与模组加载器"),
            # "loader" 是 PCL2 口径的步骤名 —— 两个都报, 老界面和新界面都能动。
            phase_cb("deps", 20, "安装 %s %s" % (loader_title, loader_version))
            phase_cb("loader", 20, "安装 %s %s" % (loader_title, loader_version))
        if progress_cb:
            progress_cb(6, "整合包需要 %s %s，正在自动安装…" % (loader_title, loader_version))
        if loader == "fabric":
            installed = install_mod.install_fabric(mc, loader_version, root, cfg,
                                                   cancel_cb=cancel_cb, phase_cb=relay)
        elif loader == "quilt":
            installed = install_mod.install_quilt(mc, loader_version, root, cfg,
                                                  cancel_cb=cancel_cb, phase_cb=relay)
        elif loader in ("forge", "neoforge"):
            java = install_mod.find_java_for(cfg, mc)
            # B4: 版本 id 由安装器生成, 调用前算不出来 → 用目录监视在"安装器刚产出目录、
            # json 还没写完"的窗口里补上 .pclpy_installing 占位。
            mark_state = _start_forge_placeholder_watch(root, loader, mc)
            try:
                installed = install_mod.install_forge_like(loader, mc, loader_version, root, cfg,
                                                           java, cancel_cb=cancel_cb,
                                                           phase_cb=relay)
            except BaseException:
                # 失败 / 取消: 占位**保留**(扫描器隐藏半成品 + cleanup_unfinished 清理)
                _finish_forge_placeholder_watch(mark_state, "", ok=False)
                raise
            # 成功(安装器退出码 0 且版本 json 真的在) → 一定把占位清掉
            _finish_forge_placeholder_watch(
                mark_state, str(installed or ""),
                ok=bool(installed) and _has_version(root, str(installed or "")))
        if installed and _has_version(root, installed):
            _phase_emit(phase_cb, "deps", 100, "安装 %s %s 完成" % (loader_title, loader_version))
            _phase_emit(phase_cb, "loader", 100, "安装 %s %s 完成" % (loader_title, loader_version))
            return installed
    # 加载器没装上: 至少用原版父版本, 但要让调用方知道这包跑不完整
    return parent


def _match_sha1(path: str, expect: str) -> bool:
    """校验文件 sha1(索引里给的就是 sha1)。出错或为空时按"不通过"处理, 由调用方决定。"""
    want = str(expect or "").strip().lower()
    if not want or not os.path.isfile(path):
        return False
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(256 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().lower() == want
    except Exception:  # noqa: BLE001
        return False


def _matches_entry(path: str, sha1: str, size: int) -> bool:
    """本机文件是否就是索引里那一个: 先比大小(便宜), 再比 sha1(权威)。"""
    if not path or not os.path.isfile(path):
        return False
    want = str(sha1 or "").strip().lower()
    try:
        if size > 0 and os.path.getsize(path) != int(size):
            return False
    except OSError:
        return False
    if not want:
        # 索引没给 sha1 时只能靠大小, 但**大小必须是已知且为正**的, 否则不算命中
        return size > 0
    return _match_sha1(path, want)


def _reuse_local(dest: str, size: int, sha1: str = "") -> bool:
    """本机已有**同一个文件**(大小 + sha1 都对得上)时复制过来, 省一次下载。

    查找范围(学 PCL2 的"已存在文件复用"):
      * 启动器目录 ``Download/<类型>`` 下的同名文件
      * 其它版本实例里**相同相对路径**的文件(例如 ``mods/xxx.jar``)

    ⚠️ 以前这里**只比大小**(注释还写着"不做哈希, 得不偿失"), 于是：

      * 别的整合包/版本里"同名同大小但内容不同"的文件会被当成它复制过来 →
        整合包 mod 数量对但内容不对;
      * 复制完不复核, 复制中途出错也照样返回成功。

    现在: 候选文件必须 **大小一致且 sha1 一致** 才会被复制, 并且**复制后必须复核 sha1**,
    复核不过就删掉复制结果、返回 False, 让调用方老老实实去下载。
    """
    if size <= 0 or not dest:
        return False
    name = os.path.basename(dest)
    sub = os.path.basename(os.path.dirname(dest))       # mods / resourcepacks / shaderpacks …
    want = str(sha1 or "").strip().lower()
    candidates = []
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(dest)))   # versions/<id>
        for kind_dir in ("Mods", "ResourcePacks", "ShaderPacks", "DataPacks"):
            candidates.append(os.path.join(download_dir(kind_dir), name))
        versions_root = os.path.dirname(base)
        if os.path.isdir(versions_root):
            for folder in os.listdir(versions_root):
                candidates.append(os.path.join(versions_root, folder, sub, name))
    except Exception:  # noqa: BLE001
        return False
    for path in candidates:
        try:
            if os.path.abspath(path) == os.path.abspath(dest):
                continue
            if not _matches_entry(path, want, size):
                continue
            ensure_dir(os.path.dirname(dest))
            shutil.copy2(path, dest)
            # 复制后复核: 复制过程中磁盘出错/源文件被改, 都不能算命中
            if _matches_entry(dest, want, size):
                return True
            try:
                os.remove(dest)
            except OSError:
                pass
            return False
        except Exception:  # noqa: BLE001
            continue
    return False


def _entry_client_unsupported(entry) -> bool:
    """索引条目是否写着"客户端跑不了"(``env.client == "unsupported"``)。

    ``.mrpack`` 的 modrinth.index.json 里每个 entry 可以带 ``env`` 字段:
    ``{"client": "required" | "optional" | "unsupported", "server": ...}``。
    客户端启动器只关心 client 一侧:

      * ``unsupported`` —— 客户端装了也用不上(纯服务端 Mod / 插件 / 服务端工具),
        **不下载、不安装**, 也**不算失败/未完成**(它本来就不该装);
      * ``optional``    —— 规范里是"可选"; 本启动器**保持原有行为: 照装**
        (理由见 ``install_modpack`` 里 skipped 那段注释);
      * 缺失 / ``required`` —— 照旧安装。
    """
    if not isinstance(entry, dict):
        return False
    env = entry.get("env")
    if not isinstance(env, dict):
        return False
    return str(env.get("client") or "").strip().lower() == "unsupported"


def is_modpack_file(path: str) -> bool:
    """判断文件是不是真正的整合包(.mrpack / 内含 modrinth.index.json 的 zip)。

    用户很容易把下载好的 Mod jar 当成整合包导入, 那时不该报
    "缺少 modrinth.index.json", 而应该按普通资源处理。
    """
    text = str(path or "")
    if not text or not os.path.isfile(text):
        return False
    try:
        with zipfile.ZipFile(text) as zf:
            for name in zf.namelist():
                if name.lower().endswith("modrinth.index.json"):
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _version_name_checker(root: str):
    """拿 ``pclpy/backend/download.py`` 里那套 ``validateVersionName`` 来用。

    它是 ``DownloadBackend`` 上的 QML Slot(靠 ``self.launcher.root()`` 找 versions 目录),
    所以这里造一个**只要 root() 的哑 launcher** 把它包起来 —— 命名规则只有一处定义,
    core 里不再自己抄一份(抄一份就会和下载页的校验漂移)。

    ``DownloadBackend.defaultVersionName`` 是"加载器 key + MC 版本 → 默认名"的界面辅助
    (签名 ``(key, mc_version)``, 只能按加载器拼名), 整合包这里是"用户/整合包自带的
    名字 → 校验/避让", 语义对不上, 所以只用 ``validateVersionName``。
    名字被占用时的 ``-2``/``-3`` 后缀避让逻辑与 ``defaultVersionName`` 完全一致。

    PySide6 不可用(纯核心环境)时退回 ``_fallback_version_name_error``, 规则保持一致。
    """
    try:
        from ..backend.download import DownloadBackend   # 惰性导入: core 不硬依赖 PySide6

        class _RootOnlyLauncher(object):                 # noqa: D401
            def root(self) -> str:
                return str(root)

        backend = DownloadBackend(cfg=None, launcher=_RootOnlyLauncher())
        return backend.validateVersionName
    except Exception:  # noqa: BLE001
        return _fallback_version_name_error


def _fallback_version_name_error(name: str) -> str:
    """``DownloadBackend.validateVersionName`` 的等价实现(只在没有 PySide6 时兜底)。

    返回空串表示没问题, 否则返回中文错误提示。
    """
    text = str(name or "").strip()
    if not text:
        return "名称不能为空"
    bad = [ch for ch in '\\/:*?"<>|' if ch in text]
    if bad:
        return "名称不能包含 \\ / : * ? \" < > | 这些符号"
    if text in (".", ".."):
        return "名称不合法"
    if text.endswith("."):
        return "名称不能以点结尾"
    return ""


# Windows 保留设备名: 用它们当目录名时系统会静默丢弃, 安装过程会莫名其妙失败
_RESERVED_NAMES = set(["con", "prn", "aux", "nul"] +
                      ["com%d" % i for i in range(1, 10)] +
                      ["lpt%d" % i for i in range(1, 10)])


def _name_extra_error(name: str) -> str:
    """``validateVersionName`` 没覆盖、但会真的害死安装的两条:
    版本目录已存在(会影响**目录名/json 文件名/json 里的 id** 三处)与 Windows 保留名。
    """
    text = str(name or "").strip()
    if not text:
        return "名称不能为空"
    base = text.split(".")[0].strip().lower()
    if base in _RESERVED_NAMES:
        return "名称不能是 Windows 保留设备名(%s)" % text.split(".")[0]
    return ""


def _resolve_modpack_name(root: str, wanted: str) -> Tuple[str, str]:
    """把整合包自带的版本名**校验+定案**: 返回 (可用名, 被采用的替代名)。

    * 名字合法且没被占用 → 原样返回 (``wanted``, "")
    * 名字非法 → 清掉非法字符并去掉 Windows 保留名风险; 清不出可用名就退回 "ModPack"
    * 定为的名字已被占用 → 自动加 ``-2``/``-3``/… 后缀避让

    改名的理由: 启动器只能拿到一个字符串, 如果这里抛错, 用户得自己猜一个合法名字;
    自动改名既能装完, 又能把最终名字回报给界面/日志。真正"重名"的用户意图
    (想覆盖已装版本)不应该被猜, 所以**只避让、绝不覆盖**已有版本目录。
    """
    check = _build_version_name_checker(root)

    wanted = str(wanted or "").strip()
    # 名字本身没问题 → 直接用
    if wanted and not check(wanted):
        return wanted, ""
    # 非法 → 先按 Windows 文件名规则清理一眼(和 safe_name 同一套字符表)
    base = safe_name(wanted)
    if base == "unnamed":
        base = "ModPack"
    if not check(base):
        return base, base
    for index in range(2, 100):
        candidate = "%s-%d" % (base, index)
        if not check(candidate):
            return candidate, candidate
    raise RuntimeError("整合包版本名 %r 无法确定可用的名字(重名太多或全是非法字符)" % wanted)


def _build_version_name_checker(root: str):
    """返回一个 ``check(name) -> 错误提示(空串=可用)`` 的闭包。

    规则 = ``validateVersionName``(直接复用) + ``_name_extra_error``(目录已存在/保留名)。
    """
    validate = _version_name_checker(root)

    def _check(text: str) -> str:
        try:
            error = str(validate(text) or "")
        except Exception as exc:  # noqa: BLE001
            print("[resources] 版本名校验失败:", type(exc).__name__, exc, flush=True)
            error = ""
        if error:
            return error
        return _name_extra_error(text)

    return _check


def _phase_emit(phase_cb, phase_id: str, percent: int, text: str) -> None:
    """阶段回调的**防错包装**(PCL2 步骤文案与顺序见 ModModpack.vb:408 / ModDownloadLib.vb:1855)。

    ``phase_id`` 沿用现有调用形式 ``phase_cb(阶段id, 百分比, 文案)``。其中 ``files`` /
    ``overrides`` 就是任务页 MODPACK_STEPS 里已有的 id, 所以老界面照样动; 其余 id
    (json/client/libraries/assets/natives/loader/install/libs)只有在
    ``launcher.py`` 的 MODPACK_STEPS 里补上才会显示成独立步骤, 现在会被
    ``_on_task_phase`` 安全忽略(不会报错、不会打乱已有步骤)。
    """
    if not callable(phase_cb):
        return
    try:
        phase_cb(str(phase_id), int(percent), str(text))
    except Exception as exc:  # noqa: BLE001
        print("[resources] 阶段回调失败:", type(exc).__name__, exc, flush=True)


def install_modpack(archive: str, root: str, instance_name: str, cfg=None,
                    progress_cb=None, cancel_cb=None, phase_cb=None, bytes_cb=None) -> str:
    """安装整合包(.mrpack): 建一个独立版本目录, 下载其中所有文件。

    返回新版本 id(可能与传入的 ``instance_name`` 不同: 非法字符/重名会被自动改名)。
    整合包的游戏目录就是 ``versions/<id>/``(版本隔离), 所以 mods/config/资源包都装在里面,
    不会污染其它版本。

    ``bytes_cb`` 用来接收**字节增量**, 任务页要靠它显示下载速度(只报百分比是看不到速度的)。
    """
    from . import install as install_mod

    index = _read_index(archive)
    if not isinstance(index, dict):
        raise RuntimeError("不是有效的 Modrinth 整合包(缺少 modrinth.index.json)")
    info = modpack_loader(index)
    # ---- 版本名: 目录名 / json 文件名 / json 里的 id **三处必须同一个值**(见规范)
    raw_name = str(instance_name or "").strip() or os.path.splitext(os.path.basename(archive))[0]
    version_id, renamed_from = _resolve_modpack_name(root, raw_name)
    version_dir = os.path.join(str(root), "versions", version_id)
    ensure_dir(version_dir)
    _phase_emit(phase_cb, "prepare", 5, "解压整合包文件")

    # 整合包实例**强制隔离**, 且必须在创建 mods/saves 目录之前写:
    # PCL2 正是靠这种"先定隔离、再建目录"的顺序保证隔离信息已确定(ModDownloadLib.vb:1968)。
    try:
        install_mod.write_isolation_flag(str(root), version_id, True)
    except Exception:  # noqa: BLE001
        pass

    progress_cb = install_mod.adapt_progress_callback(progress_cb)
    if renamed_from:
        # 自动改名必须让用户看得见, 否则他会以为"我明明叫 A 怎么装出来是 A-2"
        print("[resources] 整合包版本名 %r 不可用(非法字符/重名), 已改用 %r"
              % (renamed_from, version_id), flush=True)
        if progress_cb:
            progress_cb(1, "版本名 %s 不可用（非法字符或已存在），已改用 %s"
                        % (renamed_from, version_id))
    files = index.get("files") if isinstance(index.get("files"), list) else []
    total = max(1, len(files))
    source = str(cfg.get("download.source") or "official") if cfg is not None else "official"

    # 整合包里动辄上百个文件, 逐个下载太慢 —— 这里并行下载(默认 8 线程)
    # pending 里除了 url/dest, 还带上索引里的 sha1 与大小: 用于"本机已有就不重复下载"与下载后校验
    pending = []  # type: List[Tuple[str, str, str, int]]
    missing = []  # type: List[str]       索引里有、但**没有下载地址**的文件(典型是 CurseForge 托管的)
    skipped = []  # type: List[str]       客户端跑不了、**故意不装**的文件(env.client=unsupported)
    for entry in files:
        if not isinstance(entry, dict):
            continue
        downloads = entry.get("downloads") if isinstance(entry.get("downloads"), list) else []
        url = str(downloads[0]) if downloads else ""
        relative = str(entry.get("path") or "").replace("\\", "/").lstrip("/")
        if not relative or ".." in relative:
            continue
        if _entry_client_unsupported(entry):
            # B2: env.client == "unsupported" → 客户端装了也跑不起来, 不下载、不安装。
            # 必须放在 `not url` 判定**之前**: 这类纯服务端文件常常也没有 downloads,
            # 先走 missing 会把它记成"缺下载地址/未完成", 而它本就不该装。
            # optional **不在这里**跳过 —— 保持原有行为(照装), 理由见下面的注释。
            skipped.append(relative)
            continue
        if not url:
            # ⚠️ 以前这里是**静默跳过** —— 于是"整合包报安装完成, mods 里却少一大半",
            # 失败清单还是空的。CurseForge 托管的文件在 .mrpack 里就是没有 downloads,
            # 需要 CurseForge API 才能换到地址(PCL2 也是这么做的)。这里必须记下来。
            missing.append(relative)
            continue
        hashes = entry.get("hashes") if isinstance(entry.get("hashes"), dict) else {}
        sha1 = str(hashes.get("sha1") or "").lower()
        size = int(entry.get("fileSize") or 0)
        dest = os.path.join(version_dir, relative.replace("/", os.sep))
        if _matches_entry(dest, sha1, size):
            # 本机已有**校验通过**的同一个文件 → 跳过。
            # ⚠️ 以前这里只写 `if os.path.isfile(dest): continue`: 上一次安装留下的
            # 半个/损坏/同名不同内容的文件会被无脑认下, 于是"重装之后还是少文件/内容不对"。
            continue
        ensure_dir(os.path.dirname(dest))
        pending.append((url, dest, sha1, size))

    failed = []  # type: List[Tuple[str, str]]   (url, dest) 下载失败的文件
    # PCL2 里"下载额外文件"本身就是一步(ModModpack.vb:448), 所以不管有没有 pending
    # 都要报出来; 否则任务页上这一步会凭空消失, 看起来像跳步了。
    _phase_emit(phase_cb, "files", 0, "下载额外文件")
    if skipped:
        # 跳过的数量必须让用户看得见 —— 否则"包里 143 个文件、装出来 138 个"会被当成丢文件。
        # 文案里**不要**出现 "n/m" 这种数字(会和真正的 pending 计数混淆)。
        # 关于 optional: 保持"照装"的原有行为 —— 规范里 optional 表示"客户端可用但非必需",
        # 大多数整合包用它装客户端侧的辅助 Mod/资源; 官方 Modrinth 启动器/ PCL2 也是
        # "client != unsupported 就装"。跳过 optional 会让这些包功能缺失, 属于超出
        # "跳过 unsupported" 的行为变更, 所以这里只跳过 unsupported。
        if progress_cb:
            progress_cb(1, "跳过 %d 个客户端不支持的文件（env.client = unsupported，"
                          "不下载也不算失败）" % len(skipped))
        for relative in skipped[:5]:
            print("[resources] 跳过客户端不支持的文件:", relative, flush=True)
    if pending:
        import threading
        finished = {"count": 0}         # 已"处理完"(成功或失败)的文件数, 进度用
        lock = threading.Lock()

        def _one(url: str, dest: str, sha1: str = "", size: int = 0) -> None:
            if install_mod._cancelled(cancel_cb):
                return
            stream = {"last": 0}

            def _file_progress(current, total):
                # 字节增量 → 任务页的"下载速度"才能显示(以前这里只报百分比, 速度恒为 --)
                delta = int(current) - int(stream["last"])
                if delta > 0:
                    stream["last"] = int(current)
                    if bytes_cb:
                        try:
                            bytes_cb(delta)
                        except Exception:  # noqa: BLE001
                            pass
                # 大文件下载期间也要让进度动起来(否则看起来像卡死在 98%)
                if total and progress_cb:
                    with lock:
                        percent = int(100 * float(current) / float(total))
                        count = finished["count"] + 1
                    progress_cb(percent, "下载额外文件 %d/%d（%d%%）"
                                % (count, len(pending), percent))

            try:
                # 1) 本机已有"大小 + sha1 都对得上"的文件 → 复制过来省一次下载。
                #    _reuse_local 自己会按大小+sha1 筛选候选, 并且**复制后复核 sha1**。
                if not _reuse_local(dest, size, sha1):
                    # 2) 老老实实下载; 失败重试一次(CDN 偶发失败很常见), 每轮都用 sha1 复核。
                    ok = False
                    for _attempt in range(2):
                        if install_mod._cancelled(cancel_cb):
                            break
                        if remote.download_file(url, dest, source=source, cancel_cb=cancel_cb,
                                                progress_cb=_file_progress):
                            if not sha1 or _match_sha1(dest, sha1):
                                ok = True
                                break
                    if not ok:
                        # ⚠️ 以前这里的控制流是"成功也走失败分支": 下完的文件被 os.remove 删掉
                        # 又记进失败清单。现在成功就 return, 失败才清理 + 记账。
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
                        failed.append((url, dest))
                        return
            except Exception:  # noqa: BLE001    单个文件失败不影响整体
                failed.append((url, dest))
            with lock:
                finished["count"] += 1
                current = finished["count"]
            if progress_cb:
                progress_cb(int(100 * current / float(max(1, len(pending)))),
                            "下载额外文件 %d/%d" % (current, len(pending)))

        workers = []
        index_pos = {"i": 0}
        index_lock = threading.Lock()

        def _runner() -> None:
            while True:
                with index_lock:
                    if index_pos["i"] >= len(pending):
                        return
                    # ⚠️ pending 里是**四元组** (url, dest, sha1, size)。
                    # 这里以前写成 `url, dest = pending[i]` —— 每个工作线程都会
                    # 立刻抛 ValueError("too many values to unpack") 死掉, 一个文件都
                    # 下不载: 版本目录里只剩 overrides 解压出来的那点文件, failed 还是空的,
                    # 于是"装完了但 mod 少一大半, 失败清单却是空的"。必须整条解包。
                    url, dest, sha1, size = pending[index_pos["i"]]
                    index_pos["i"] += 1
                _one(url, dest, sha1, size)

        thread_count = 8
        try:
            thread_count = max(1, min(16, int(install_mod._thread_count(cfg))))
        except Exception:  # noqa: BLE001
            pass
        for _ in range(min(thread_count, max(1, len(pending)))):
            thread = threading.Thread(target=_runner)
            thread.daemon = True
            thread.start()
            workers.append(thread)
        for thread in workers:
            thread.join()

    _phase_emit(phase_cb, "files", 100, "下载额外文件")

    # 覆盖文件(overrides / client-overrides)直接解压进版本目录。
    # 顺序按 PCL2: 解压整合包文件(含 overrides)在"下载额外文件"之后、"下载原版"之前
    # (ModModpack.vb:408 —— ExtractModpackFiles + CopyOverrideDirectory 是同一步)。
    _phase_emit(phase_cb, "overrides", 0, "解压覆盖文件")
    if progress_cb:
        progress_cb(38, "解压覆盖文件…")
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                lower = member.lower()
                if not (lower.startswith("overrides/") or lower.startswith("client-overrides/")):
                    continue
                if member.endswith("/"):
                    continue
                relative = member.split("/", 1)[1]
                if not relative or ".." in relative:
                    continue
                target = os.path.join(version_dir, relative.replace("/", os.sep))
                ensure_dir(os.path.dirname(target))
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    except Exception:  # noqa: BLE001
        pass
    _phase_emit(phase_cb, "overrides", 100, "解压覆盖文件")

    # 写一个继承自对应加载器/原版的版本 json, 这样能直接启动
    # 关键: 原版和加载器必须真的装好, 否则启动时会退化成纯原版(整合包的 Mod 全不生效)
    relay = _modpack_phase_relay(phase_cb)      # 原版的 json/client/libraries/assets/natives
    _phase_emit(phase_cb, "json", 0, "下载原版 json 文件")
    parent = ensure_modpack_parent(info, root, cfg, progress_cb=progress_cb,
                                   cancel_cb=cancel_cb, phase_cb=relay)
    _phase_emit(phase_cb, "json", 100, "下载原版 json 文件")
    data = {
        "id": version_id,
        "inheritsFrom": parent,
        "type": "release",
        "time": "",
        "releaseTime": "",
        "mainClass": "",
        "libraries": [],
        "pclpy:description": "整合包 %s" % version_id,
        "pclpy:modpack": {"loader": info["loader"], "loaderVersion": info["loader_version"],
                          "mc": info["mc_version"], "parent": parent},
    }
    if not parent:
        raise RuntimeError("整合包缺少可用的游戏版本(原版/加载器都没能装好)，"
                           "请先在下载页安装 %s 与 %s %s"
                           % (info["mc_version"] or "对应的原版",
                              LOADER_TITLES.get(info["loader"], info["loader"]),
                              info["loader_version"]))
    # 目录名 / json 文件名 / json 里的 id 三处都用同一个 version_id
    install_mod._write_json(os.path.join(version_dir, version_id + ".json"), data)
    # 立刻"自包含化": 把 inheritsFrom 链(原版 + 加载器)全部合并进实例自己的 json,
    # 并复制一份客户端 jar 到实例目录 —— 这样整合包实例与父版本**完全独立**,
    # 父版本改名/删除都不影响它, 而且不会出现"空 mainClass 把 Forge 主类清掉"的问题。
    _phase_emit(phase_cb, "install", 50, "安装游戏")
    try:
        install_mod.make_self_contained(str(root), version_id)
    except Exception:  # noqa: BLE001
        pass
    _phase_emit(phase_cb, "install", 100, "安装游戏")
    # 最后一步: 下载游戏支持库(合并进来的 Forge/Fabric 库)
    _phase_emit(phase_cb, "libs", 100, "下载游戏支持库")

    # ---- 落盘复核: 索引里的文件必须**真的在版本目录里且 sha1 对得上**。
    # 这一步是"失败清单为空却少文件"的最后一道保险: 只统计 pending 的成败是不够的,
    # 还得确认文件真的落到了 versions/<id>/ 下(路径拼接错/被别的东西删掉都能查出来)。
    unverified = []  # type: List[str]
    for entry in files:
        if not isinstance(entry, dict):
            continue
        relative = str(entry.get("path") or "").replace("\\", "/").lstrip("/")
        if not relative or ".." in relative:
            continue
        if _entry_client_unsupported(entry):
            continue        # 客户端不支持的文件本来就没打算装 → 不能算"没落盘/校验不通过"
        hashes = entry.get("hashes") if isinstance(entry.get("hashes"), dict) else {}
        sha1 = str(hashes.get("sha1") or "").lower()
        size = int(entry.get("fileSize") or 0)
        dest = os.path.join(version_dir, relative.replace("/", os.sep))
        if not _matches_entry(dest, sha1, size):
            unverified.append(relative)

    if failed or missing or unverified:
        # 没下全 **不能**当成装好了: 打上"未完成"标记(列表里会被跳过), 并明确告诉用户。
        # 以前只报一句"安装完成（N 个文件下载失败）", 实例照样能启动 —— 结果就是
        # "整合包装好了但 mod 少了一半、游戏里什么都没生效"。
        install_mod.mark_installing(str(root), version_id)
        if progress_cb:
            parts = []
            if failed:
                parts.append("%d 个文件下载失败" % len(failed))
            if missing:
                parts.append("%d 个文件缺少下载地址（多为 CurseForge 托管，"
                             "需要配置 CurseForge API Key 才能下载）" % len(missing))
            if unverified:
                parts.append("%d 个文件没有真正落盘或校验不通过" % len(unverified))
            if skipped:
                parts.append("%d 个文件客户端不支持、已跳过(不算失败)" % len(skipped))
            detail = "、".join(parts) if parts else "存在未完成的文件"
            progress_cb(100, "整合包安装**未完成**：%s，版本已标记为未完成" % detail)
            for url, dest in failed[:5]:
                print("[resources] 下载失败:", url, "->", dest, flush=True)
            for relative in (unverified or missing)[:5]:
                print("[resources] 缺失文件:", relative, flush=True)
        return version_id
    if progress_cb:
        progress_cb(100, "整合包安装完成" +
                    ("（已跳过 %d 个客户端不支持的文件）" % len(skipped) if skipped else ""))
    return version_id
