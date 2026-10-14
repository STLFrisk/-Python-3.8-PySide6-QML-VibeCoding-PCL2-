"""核心层冒烟测试(不依赖 pytest)。

运行: python tests/test_core.py
全部通过时输出 "ALL CORE TESTS PASSED"。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

# 保证可以直接 `python tests/test_core.py` 运行
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 用临时目录当 PCLPY_HOME, 避免污染真实配置
_TMP = tempfile.mkdtemp(prefix="pclpy_core_test_")
os.environ["PCLPY_HOME"] = os.path.join(_TMP, "home")

from pclpy.core import accounts, catalog, config, install, launch, mods, packexport, paths, remote, resources, versions  # noqa: E402

_FAILURES = []  # type: list


def check(name, condition, detail=""):
    """记录一条断言结果。"""
    if condition:
        print("    [OK] %s" % name)
    else:
        text = "%s%s" % (name, (" :: %s" % detail) if detail else "")
        _FAILURES.append(text)
        print("    [FAIL] %s" % text)


def run(fn):
    """执行一个测试函数, 捕获异常。"""
    print("[TEST] %s" % fn.__name__)
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _FAILURES.append("%s 抛出异常: %r" % (fn.__name__, exc))


# ------------------------------------------------------------------ 测试
def test_paths():
    check("PCLPY_HOME 生效", str(paths.app_home()) == os.environ["PCLPY_HOME"], str(paths.app_home()))
    target = os.path.join(_TMP, "a", "b", "c")
    paths.ensure_dir(target)
    check("ensure_dir 创建多级目录", os.path.isdir(target))
    check("bundled_data_path 指向真实文件", os.path.isfile(paths.bundled_data_path("catalog.json")))
    check("human_size 832 KB", paths.human_size(851968) == "832 KB", paths.human_size(851968))
    check("human_size 1.2 MB", paths.human_size(1258291) == "1.2 MB", paths.human_size(1258291))
    check("human_size 1.4 GB", paths.human_size(1503238553) == "1.4 GB", paths.human_size(1503238553))
    check("human_size B", paths.human_size(500) == "500 B", paths.human_size(500))
    bad = paths.safe_name('a<b>:c/d|e?f*g"h')
    check("safe_name 去掉非法字符", bad == "abcdefgh", bad)
    check("official_minecraft_dir 非空", bool(paths.official_minecraft_dir()))
    check("desktop_dir 非空", bool(paths.desktop_dir()))


def test_config():
    path = os.path.join(_TMP, "cfg", "config.json")
    cfg = config.Config(path)
    check("默认值(launch.java_path)", cfg.get("launch.java_path") == "auto", cfg.get("launch.java_path"))
    cfg.set("launch.java_path", "D:/jdk/bin/java.exe")
    check("点号 set/get", cfg.get("launch.java_path") == "D:/jdk/bin/java.exe")
    check("save 写盘成功", os.path.isfile(path))
    cfg2 = config.Config(path)
    check("重新加载保持值", cfg2.get("launch.java_path") == "D:/jdk/bin/java.exe")
    cfg.set("custom.deep.key", 42)
    check("自动创建中间层级", cfg.get("custom.deep.key") == 42)
    check("缺失键返回默认值", cfg.get("nothing.here", "d") == "d")

    broken = os.path.join(_TMP, "broken.json")
    with open(broken, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    cfg3 = config.Config(broken)
    check("损坏 json 回退默认值", cfg3.get("window_size.w") == 1000, cfg3.get("window_size.w"))
    check("损坏 json 仍可写回", cfg3.save() is True)

    cfg.add_folder("文件夹A", "C:/mc/a")
    cfg.add_folder("文件夹B", "C:/mc/a")
    check("add_folder 按 path 去重", len(cfg.folders) == 1, len(cfg.folders))
    check("add_folder 更新名字", cfg.folders[0].get("name") == "文件夹B", cfg.folders[0])
    check("selected_folder 自动填充", str(cfg.selected_folder) == "C:/mc/a")

    check("toggle_favorite 打开", cfg.toggle_favorite("1.20.1") is True)
    check("is_favorite 生效", cfg.is_favorite("1.20.1") is True)
    check("toggle_favorite 关闭", cfg.toggle_favorite("1.20.1") is False)
    check("is_favorite 已取消", cfg.is_favorite("1.20.1") is False)

    cfg.add_account(accounts.to_dict(accounts.offline("Steve")))
    check("add_account 写入", len(cfg.accounts) == 1, len(cfg.accounts))
    cfg.add_account({"name": "Steve", "kind": "offline", "uuid": "x", "token": ""})
    check("add_account 同名覆盖", len(cfg.accounts) == 1 and cfg.accounts[0]["uuid"] == "x")
    check("selected_account 自动填充", str(cfg.selected_account) == "Steve")
    cfg.set("selected_version", "1.20.1")
    check("selected_version 可当字符串", cfg.selected_version == "1.20.1")
    check("selected_version 也可调用", cfg.selected_version() == "1.20.1")
    check("as_dict 返回配置副本", isinstance(cfg.as_dict(), dict) and "launch" in cfg.as_dict())
    check("默认 Config 路径在 PCLPY_HOME 下", config.Config().path.startswith(_TMP), config.Config().path)


def test_parse_version_id():
    cases = [
        ("1.8.9-Forge_11.15.1.2318", {"mc_version": "1.8.9", "loader": "Forge", "loader_version": "11.15.1.2318"}),
        ("26.2-Fabric_0.19.3", {"mc_version": "26.2", "loader": "Fabric", "loader_version": "0.19.3"}),
        ("1.21.1-NeoForge_21.1.233", {"mc_version": "1.21.1", "loader": "NeoForge", "loader_version": "21.1.233"}),
        ("1.8.9-OptiFine_M5", {"mc_version": "1.8.9", "loader": "OptiFine", "loader_version": "M5"}),
        ("1.20.1", {"mc_version": "1.20.1", "loader": "", "loader_version": ""}),
    ]
    for vid, expect in cases:
        got = versions.parse_version_id(vid)
        check("parse_version_id %s" % vid, got == expect, got)
    check("version_key 1.21.4", versions.version_key("1.21.4") == (1, 21, 4))
    check("version_key 忽略非数字", versions.version_key("b1.7.3") == (1, 7, 3))


def test_accounts():
    a1 = accounts.offline("Steve")
    a2 = accounts.offline("Steve")
    check("离线 uuid 稳定", a1.uuid == a2.uuid, a1.uuid)
    check("离线 uuid 变更名字后不同", accounts.offline("Alex").uuid != a1.uuid)
    parts = a1.uuid.split("-")
    check("离线 uuid 格式", len(a1.uuid) == 36 and [len(p) for p in parts] == [8, 4, 4, 4, 12], a1.uuid)
    check("离线 uuid 全小写", a1.uuid == a1.uuid.lower())
    check("display 离线账号", accounts.display(a1) == "Steve（离线）", accounts.display(a1))
    restored = accounts.from_dict(accounts.to_dict(a1))
    check("to_dict/from_dict 往返", restored == a1, restored)


def test_scan_folder():
    mc_root = os.path.join(_TMP, "fake_minecraft")
    good1 = os.path.join(mc_root, "versions", "1.20.1")
    good2 = os.path.join(mc_root, "versions", "1.8.9-Forge_11.15.1.2318")
    bad = os.path.join(mc_root, "versions", "1.7.10-Forge_10.13.4.1614")
    for folder in (good1, good2, bad):
        os.makedirs(folder, exist_ok=True)
    with open(os.path.join(good1, "1.20.1.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "1.20.1", "type": "release", "releaseTime": "2023-06-12T12:00:00+00:00"}, f)
    with open(os.path.join(good2, "1.8.9-Forge_11.15.1.2318.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "1.8.9-Forge_11.15.1.2318", "inheritsFrom": "1.8.9", "type": "release",
                   "pclpy:description": "老版本整合"}, f)
    with open(os.path.join(bad, "1.7.10-Forge_10.13.4.1614.json"), "w", encoding="utf-8") as f:
        f.write("{{{ 损坏的 json")

    items = versions.scan_folder(mc_root)
    check("scan_folder 跳过损坏 json(2 条)", len(items) == 2, [v.id for v in items])
    ids = sorted(v.id for v in items)
    check("scan_folder 版本 id", ids == ["1.20.1", "1.8.9-Forge_11.15.1.2318"], ids)
    forge = versions.select_version(items, "1.8.9-Forge_11.15.1.2318")
    check("select_version 命中", forge is not None)
    if forge is not None:
        check("inheritsFrom 作为 mc_version", forge.mc_version == "1.8.9", forge.mc_version)
        check("loader 解析", forge.loader == "Forge" and forge.loader_version == "11.15.1.2318")
        check("installed/source/path", forge.installed and forge.source == "local" and os.path.isabs(forge.path))
        check("size_bytes 非零", forge.size_bytes > 0, forge.size_bytes)
        check("subtitle", forge.subtitle() == "正式版 1.8.9, Forge 11.15.1.2318", forge.subtitle())
        check("icon_name(Forge)", forge.icon_name() == "cube_gray", forge.icon_name())
        check("description 自定义字段", forge.description == "老版本整合", forge.description)
    vanilla = versions.select_version(items, "1.20.1")
    check("原版 subtitle", vanilla is not None and vanilla.subtitle() == "正式版 1.20.1",
          vanilla.subtitle() if vanilla else None)
    check("matches 忽略大小写", vanilla is not None and vanilla.matches("1.20"))
    check("scan_folder 空目录返回 []", versions.scan_folder(os.path.join(_TMP, "not_exist")) == [])


def test_group_versions():
    items = versions.demo_installed()
    check("demo_installed 数量", len(items) == 13, len(items))
    grouped = versions.group_versions(items)
    check("modded 桶", len(grouped["modded"]) == 7, len(grouped["modded"]))
    check("normal 桶", len(grouped["normal"]) == 4, len(grouped["normal"]))
    check("uncommon 桶", len(grouped["uncommon"]) == 2, len(grouped["uncommon"]))
    normal_mc = [v.mc_version for v in grouped["normal"]]
    check("normal 按版本从新到旧", normal_mc == ["26.1.2", "1.21.4", "1.20.1", "1.8.9"], normal_mc)
    uncommon_mc = [v.mc_version for v in grouped["uncommon"]]
    check("uncommon 排序", uncommon_mc == ["1.7.10", "b1.7.3"], uncommon_mc)
    check("modded 保持原顺序", [v.id for v in grouped["modded"]][0] == "26.2-Fabric_0.19.3")
    extra = versions.VersionInfo(id="x", name="x", category="不存在")
    check("未知 category 归入 normal", len(versions.group_versions([extra])["normal"]) == 1)


def test_catalog():
    data = catalog.catalog()
    check("catalog 是 dict", isinstance(data, dict))
    check("installable 非空", len(catalog.installable()) > 0, len(catalog.installable()))
    check("installable 共 9 条", len(catalog.installable()) == 9, len(catalog.installable()))
    check("demo_installed 非空", len(catalog.demo_installed()) > 0, len(catalog.demo_installed()))
    check("demo_installed 共 13 条", len(catalog.demo_installed()) == 13, len(catalog.demo_installed()))
    fallback = catalog.vanilla_fallback()
    check("vanilla_fallback 30 条", len(fallback.get("versions") or []) == 30, len(fallback.get("versions") or []))
    check("vanilla_fallback latest", fallback["latest"]["release"] == "1.21.4", fallback["latest"])

    items = versions.catalog_installable()
    check("catalog_installable 共 9 条", len(items) == 9, len(items))
    first = versions.select_version(items, "1.21.4-Fabric_0.16.13")
    check("installable id 由 name 推导", first is not None, [v.id for v in items][:2])
    if first is not None:
        check("installable 字段", first.loader == "Fabric" and first.mc_version == "1.21.4"
              and first.installed is False and first.source == "catalog")
    demo = versions.demo_installed()
    check("demo 全部 installed", all(v.installed and v.path == "" for v in demo))
    check("demo 解析 mc_version", demo[0].mc_version == "26.2", demo[0].mc_version)
    check("catalog 缓存生效", catalog.catalog() is data)


def test_remote():
    check("endpoint 官方", remote.endpoint("fabric", "official") == "https://meta.fabricmc.net")
    check("endpoint 镜像", remote.endpoint("fabric", "mirror") == remote.MIRROR["fabric"])
    rewritten = remote.rewrite_url("https://piston-meta.mojang.com/v1/packages/a/b.json", "mirror")
    check("rewrite_url 镜像重写", rewritten.startswith(remote.MIRROR["version"]), rewritten)
    unknown = "https://example.com/foo.json"
    check("rewrite_url 未知地址原样", remote.rewrite_url(unknown, "mirror") == unknown)
    check("rewrite_url 官方源不改", remote.rewrite_url(unknown, "official") == unknown)

    fallback = catalog.vanilla_fallback()
    manifest = {
        "latest": {"release": fallback["latest"]["release"], "snapshot": fallback["latest"]["snapshot"]},
        "versions": [
            {"id": v["id"], "type": v["type"], "time": v["time"], "url": v.get("url", "")}
            for v in fallback["versions"]
        ],
    }
    entries = remote.vanilla_entries(manifest)
    check("release 非空", len(entries["release"]) > 0, len(entries["release"]))
    check("release 按时间新到旧", entries["release"][0]["id"] == "1.21.5-pre1" or entries["release"][0]["time"] >= entries["release"][-1]["time"])
    check("old 分桶", sorted(e["id"] for e in entries["old"]) == ["a1.2.6", "b1.7.3"],
          [e["id"] for e in entries["old"]])
    check("april 分桶", [e["id"] for e in entries["april"]] == ["24w14potato"], entries["april"])
    check("latest.release", entries["latest"]["release"]["id"] == "1.21.4")
    check("latest.snapshot", entries["latest"]["snapshot"]["id"] == "1.21.5-pre1")
    check("无网络快速失败", remote.http_json("http://127.0.0.1:9/none.json", timeout=2) is None)
    check("下载无地址返回 False", remote.download_file("", os.path.join(_TMP, "x.bin")) is False)


def test_mods():
    mods_dir = os.path.join(_TMP, "mods")
    os.makedirs(mods_dir, exist_ok=True)
    jar = os.path.join(mods_dir, "jei-1.20.1-forge-15.2.0.27.jar")
    with open(jar, "wb") as f:
        f.write(b"x" * 2048)
    disabled = os.path.join(mods_dir, "sodium.jar.disabled")
    with open(disabled, "wb") as f:
        f.write(b"y" * 10)
    os.makedirs(os.path.join(mods_dir, "config"), exist_ok=True)

    check("parse_mod_name 切版本", mods.parse_mod_name("sodium-fabric-0.5.8.jar") == ("sodium-fabric", "0.5.8"),
          mods.parse_mod_name("sodium-fabric-0.5.8.jar"))
    check("parse_mod_name 后缀剥离", mods.parse_mod_name("jei-1.20.1-forge-15.2.0.27.jar")
          == ("jei", "1.20.1-forge-15.2.0.27"), mods.parse_mod_name("jei-1.20.1-forge-15.2.0.27.jar"))
    check("parse_mod_name 无版本", mods.parse_mod_name("sodium.jar.disabled")[0] == "sodium")
    items = mods.list_mods(mods_dir)
    check("list_mods 数量", len(items) == 3, [m.file_name for m in items])
    check("list_mods 排序", [m.name.lower() for m in items] == sorted(m.name.lower() for m in items))
    sodium = [m for m in items if m.name == "sodium"][0]
    check("禁用文件 enabled=False", sodium.enabled is False)
    check("启用重命名", mods.set_enabled(sodium, True) and os.path.isfile(os.path.join(mods_dir, "sodium.jar")))
    check("再次禁用", mods.set_enabled(sodium, False) and os.path.isfile(os.path.join(mods_dir, "sodium.jar.disabled")))
    installed = mods.install_mod(jar, mods_dir)
    check("install_mod 重名加序号", installed is not None and " (2)" in installed.file_name,
          installed.file_name if installed else None)
    check("delete_mod", installed is not None and mods.delete_mod(installed) and not os.path.exists(installed.path))
    check("list_mods 目录不存在返回 []", mods.list_mods(os.path.join(_TMP, "nope")) == [])
    check("mods_dir_for 隔离", mods.mods_dir_for("V", "R", True) == os.path.join("V", "mods"))
    check("mods_dir_for 非隔离", mods.mods_dir_for("V", "R", False) == os.path.join("R", "mods"))


def test_install_helpers():
    lib = {"name": "org.lwjgl:lwjgl:3.3.3", "downloads": {"artifact": {"path": "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar"}}}
    check("library_path 优先 artifact", install.library_path(lib) == "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar")
    check("library_path 推导", install.library_path({"name": "net.fabricmc:fabric-loader:0.16.13"})
          == "net/fabricmc/fabric-loader/0.16.13/fabric-loader-0.16.13.jar")
    check("library_path classifier", install.library_path({"name": "a.b:c:1.0:natives-windows"})
          == "a/b/c/1.0/c-1.0-natives-windows.jar")
    check("rule_allows 空规则", install.rule_allows(None) is True)
    check("rule_allows 平台", install.rule_allows([{"action": "allow", "os": {"name": install._OS_NAME}}]) is True)
    check("rule_allows 拒绝", install.rule_allows([{"action": "allow", "os": {"name": "plan9"}}]) is False)
    check("rule_allows 先允许后拒绝", install.rule_allows([
        {"action": "allow"}, {"action": "disallow", "os": {"name": install._OS_NAME}}]) is False)
    check("rule_allows features", install.rule_allows(
        [{"action": "allow", "features": {"is_demo_user": True}}]) is False)

    natives = os.path.join(_TMP, "natives.zip")
    with zipfile.ZipFile(natives, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "x")
        zf.writestr("lwjgl.dll", "dll")
        zf.writestr("sub/lib.so", "so")
    dest = os.path.join(_TMP, "natives_out")
    count = install.extract_natives(natives, dest)
    check("extract_natives 跳过 META-INF", count == 2, count)
    check("extract_natives 文件落地", os.path.isfile(os.path.join(dest, "lwjgl.dll"))
          and os.path.isfile(os.path.join(dest, "sub", "lib.so")))
    check("is_installed 不存在", install.is_installed(_TMP, "不存在") is False)


def test_launch_helpers():
    check("java_major 8", launch.java_major("1.8.0_481") == 8)
    check("java_major 17", launch.java_major("17.0.2") == 17)
    check("JavaInfo.label", launch.JavaInfo(path="j", version="1.8.0_481").label() == "Java 8 (8.0.481.0)",
          launch.JavaInfo(path="j", version="1.8.0_481").label())
    check("JavaInfo.label 空版本", launch.JavaInfo(path="j").label() == "Java")
    check("required_java_major 低版本", launch.required_java_major("1.16.5") == 8)
    check("required_java_major 1.20.1", launch.required_java_major("1.20.1") == 17)
    check("required_java_major 1.20.5+", launch.required_java_major("1.21.4") == 21)
    javas = [launch.JavaInfo(path="j17", version="17.0.2"), launch.JavaInfo(path="j8", version="1.8.0_481"),
             launch.JavaInfo(path="j21", version="21.0.1")]
    check("java_for_version 1.16.5 -> 8", launch.java_for_version(javas, "1.16.5").path == "j8")
    check("java_for_version 1.20.1 -> 17", launch.java_for_version(javas, "1.20.1").path == "j17")
    check("java_for_version 1.21.4 -> 21", launch.java_for_version(javas, "1.21.4").path == "j21")
    check("java_for_version 空列表", launch.java_for_version([], "1.21.4").path == "java")
    check("java_for_version 显式路径不存在则自动",
          launch.java_for_version(javas, "1.21.4", "D:/nope/javaw.exe").path == "j21")

    root = os.path.join(_TMP, "launch_root")
    parent_dir = os.path.join(root, "versions", "1.20.1")
    child_dir = os.path.join(root, "versions", "1.20.1-Fabric_0.15.11")
    os.makedirs(parent_dir, exist_ok=True)
    os.makedirs(child_dir, exist_ok=True)
    with open(os.path.join(parent_dir, "1.20.1.json"), "w", encoding="utf-8") as f:
        json.dump({
            "id": "1.20.1", "type": "release", "mainClass": "net.minecraft.client.main.Main",
            "assetIndex": {"id": "5"}, "libraries": [{"name": "a.b:lib:1.0"}, {"name": "a.b:dup:1.0"}],
            "arguments": {"jvm": ["-Dparent=1"], "game": ["--username", "${auth_player_name}"]},
            "logging": {"client": {"file": {"id": "client-1.12.xml"}}},
        }, f)
    with open(os.path.join(child_dir, "1.20.1-Fabric_0.15.11.json"), "w", encoding="utf-8") as f:
        json.dump({
            "id": "1.20.1-Fabric_0.15.11", "inheritsFrom": "1.20.1",
            "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
            "libraries": [{"name": "a.b:dup:1.0"}, {"name": "a.b:extra:2.0"}],
            "arguments": {"jvm": ["-Dchild=1"], "game": ["--versionType", "${version_type}"]},
        }, f)
    merged = launch.merge_version_json(root, "1.20.1-Fabric_0.15.11")
    check("merge mainClass 子覆盖父", merged.get("mainClass") == "net.fabricmc.loader.impl.launch.knot.KnotClient")
    names = [lib.get("name") for lib in merged.get("libraries") or []]
    check("merge libraries 去重", names.count("a.b:dup:1.0") == 1, names)
    check("merge libraries 子优先", names[0] == "a.b:dup:1.0", names)
    check("merge assetIndex 继承", merged.get("assetIndex", {}).get("id") == "5")
    check("merge arguments 拼接", "-Dparent=1" in (merged.get("arguments") or {}).get("jvm", [])
          and "-Dchild=1" in (merged.get("arguments") or {}).get("jvm", []))

    cfg = config.Config(os.path.join(_TMP, "launch_cfg.json"))
    cfg.set("launch.memory_mode", "custom", autosave=False)
    cfg.set("launch.memory_mb", 4096, autosave=False)
    cfg.set("launch.min_memory_mb", 512, autosave=False)
    plan = launch.build_launch(root, "1.20.1-Fabric_0.15.11", accounts.offline("Steve"), cfg, java_path="javaw")
    check("build_launch 是 LaunchPlan", isinstance(plan, launch.LaunchPlan))
    check("build_launch java", plan.java == "javaw")
    check("build_launch 主类", plan.main_class == "net.fabricmc.loader.impl.launch.knot.KnotClient")
    # 带加载器的版本默认做版本隔离(mods/config/saves 读版本目录), 见第六轮修复
    check("build_launch 带 Mod 版本默认隔离到版本目录",
          plan.cwd == os.path.join(root, "versions", "1.20.1-Fabric_0.15.11"), plan.cwd)
    check("build_launch 有内存参数", any(a.startswith("-Xmx4096M") for a in plan.command), plan.command[:6])
    check("build_launch 有 -cp", "-cp" in plan.command)
    check("build_launch 有 library.path", any(a.startswith("-Djava.library.path=") for a in plan.command))
    check("build_launch 替换用户名", "Steve" in plan.command, plan.command)
    check("build_launch 替换 assetsIndex", "5" in plan.command)
    check("build_launch 无遗留 classpath 占位符", not any("${classpath}" in a for a in plan.command))
    check("build_launch 缺失文件有 warning", len(plan.warnings) > 0, plan.warnings)
    check("build_launch 隔离模式", launch.build_launch(
        root, "1.20.1", accounts.offline("Steve"), config.Config(os.path.join(_TMP, "iso.json")),
        java_path="javaw").cwd == root)
    iso_cfg = config.Config(os.path.join(_TMP, "iso2.json"))
    iso_cfg.set("launch.isolation", "open", autosave=False)
    iso_plan = launch.build_launch(root, "1.20.1", accounts.offline("Steve"), iso_cfg, java_path="javaw")
    check("build_launch open 隔离到版本目录", iso_plan.cwd == os.path.join(root, "versions", "1.20.1"), iso_plan.cwd)

    close_cfg = config.Config(os.path.join(_TMP, "iso3.json"))
    close_cfg.set("launch.isolation", "close", autosave=False)
    close_plan = launch.build_launch(root, "1.20.1-Fabric_0.15.11",
                                     accounts.offline("Steve"), close_cfg, java_path="javaw")
    check("build_launch close 不隔离", close_plan.cwd == root, close_plan.cwd)

    if os.name == "nt":
        plan2 = launch.LaunchPlan(command=["cmd", "/c", "echo PCLPY_OK"], cwd=_TMP, java="cmd", version_id="x")
        try:
            proc = launch.start_process(plan2)
            line = (proc.stdout.readline() or "").strip()
            proc.wait(timeout=10)
            check("start_process 返回 Popen 并可读输出", line == "PCLPY_OK" and proc.returncode == 0,
                  "%r rc=%r" % (line, proc.returncode))
        except Exception as exc:  # noqa: BLE001
            check("start_process 返回 Popen 并可读输出", False, repr(exc))


def test_packexport():
    root = os.path.join(_TMP, "pack_root")
    os.makedirs(os.path.join(root, "mods"), exist_ok=True)
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    with open(os.path.join(root, "mods", "demo.jar"), "wb") as f:
        f.write(b"jar-data")
    with open(os.path.join(root, "config", "demo.toml"), "w", encoding="utf-8") as f:
        f.write("k = 1")
    with open(os.path.join(root, "options.txt"), "w", encoding="utf-8") as f:
        f.write("lang:zh_cn")
    out = os.path.join(_TMP, "out", "pack.zip")
    options = {"pack_name": "测试整合包", "pack_version": "1.2", "mods": True,
               "mod_configs": True, "game_settings": True, "saves": False}
    result = packexport.export_pack(root, "1.20.1-Forge_47.4.0", out, options)
    check("export_pack 返回路径", result == out and os.path.isfile(out))
    with zipfile.ZipFile(out, "r") as zf:
        names = zf.namelist()
        check("zip 内有 pclpy_pack.json", "pclpy_pack.json" in names, names)
        check("zip 内有模组", "mods/demo.jar" in names, names)
        check("zip 内有配置", "config/demo.toml" in names, names)
        check("zip 内有 options.txt", "options.txt" in names, names)
        check("zip 内无 saves", not any(n.startswith("saves/") for n in names), names)
        meta = json.loads(zf.read("pclpy_pack.json").decode("utf-8"))
    check("meta 包名", meta.get("name") == "测试整合包", meta.get("name"))
    check("meta 版本", meta.get("version") == "1.2")
    check("meta mc_version", meta.get("mc_version") == "1.20.1", meta.get("mc_version"))
    check("meta loader", meta.get("loader") == "Forge", meta.get("loader"))
    check("meta 文件数", meta.get("file_count") == 3, meta.get("file_count"))

    dest = os.path.join(_TMP, "import_root")
    name = packexport.import_pack(out, dest)
    check("import_pack 返回包名", name == "测试整合包", name)
    check("import_pack 解出文件", os.path.isfile(os.path.join(dest, "mods", "demo.jar"))
          and os.path.isfile(os.path.join(dest, "options.txt")))
    check("import_pack 不落地元数据", not os.path.exists(os.path.join(dest, "pclpy_pack.json")))

    evil = os.path.join(_TMP, "evil.zip")
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../evil.txt", "boom")
    try:
        packexport.import_pack(evil, os.path.join(_TMP, "evil_root"))
        check("import_pack 拒绝目录穿越", False, "未抛异常")
    except RuntimeError:
        check("import_pack 拒绝目录穿越", True)

    empty_out = os.path.join(_TMP, "empty.zip")
    packexport.export_pack(root, "1.20.1", empty_out, {})
    with zipfile.ZipFile(empty_out, "r") as zf:
        check("空选项也能导出", "pclpy_pack.json" in zf.namelist())

    cancel_out = os.path.join(_TMP, "cancel.zip")
    for index in range(3):
        with open(os.path.join(root, "mods", "extra%d.jar" % index), "wb") as f:
            f.write(b"jar")
    state = {"n": 0}

    def _cancel():
        state["n"] += 1
        return state["n"] > 2

    try:
        packexport.export_pack(root, "1.20.1", cancel_out, {"mods": True}, cancel_cb=_cancel)
        check("export_pack 取消抛 RuntimeError", False, "未抛异常")
    except RuntimeError as exc:
        check("export_pack 取消抛 RuntimeError", str(exc) == "已取消", str(exc))
    check("export_pack 取消删除半成品", not os.path.exists(cancel_out))
    try:
        packexport.import_pack(out, os.path.join(_TMP, "cancel_import"), cancel_cb=lambda: True)
        check("import_pack 取消抛 RuntimeError", False, "未抛异常")
    except RuntimeError as exc:
        check("import_pack 取消抛 RuntimeError", str(exc) == "已取消", str(exc))


def test_progress_callback_order():
    """核心层按 progress_cb(percent, text) 调用, 也要兼容 (text, percent) 写法。"""
    spec_calls = []
    text_calls = []

    def spec_cb(percent, text):
        spec_calls.append((percent, text))

    class Worker(object):
        def report(self, text, percent):
            text_calls.append((text, percent))

    worker = Worker()
    spec_out = paths.adapt_progress_callback(spec_cb)
    spec_out(10, "下载中")
    check("规格顺序回调保持不变", spec_calls == [(10, "下载中")], spec_calls)

    swapped = paths.adapt_progress_callback(worker.report)
    swapped(20, "下载中")
    check("(text, percent) 回调自动交换", text_calls == [("下载中", 20)], text_calls)

    check("None 回调安全", paths.adapt_progress_callback(None) is None)

    seen = []
    mods_dir = os.path.join(_TMP, "progress_root")
    os.makedirs(os.path.join(mods_dir, "mods"), exist_ok=True)
    with open(os.path.join(mods_dir, "mods", "a.jar"), "wb") as f:
        f.write(b"x")
    packexport.export_pack(mods_dir, "1.20.1", os.path.join(_TMP, "progress.zip"),
                           {"mods": True}, progress_cb=lambda p, t: seen.append((p, t)))
    check("export_pack 进度回调 (percent, text)",
          bool(seen) and all(isinstance(p, int) and isinstance(t, str) for p, t in seen), seen[:2])

    text_seen = []
    packexport.export_pack(mods_dir, "1.20.1", os.path.join(_TMP, "progress2.zip"),
                           {"mods": True}, progress_cb=worker.report)
    check("export_pack 兼容 (text, percent) 回调", bool(text_calls), text_calls[-1])


# 整合包回归用的固定 MC 版本: 只要 versions/<mc>/<mc>.json 存在, ensure_modpack_parent
# 就认为原版已就绪, 不会去联网安装原版(这也让整条用例可以完全离线跑)。
_PACK_MC = "1.20.1"


def test_modpack_install_regression():
    """整合包安装的离线回归。

    为什么要有这条: 曾经出过"整合包下载线程因为元组解包写错全部死掉、一个文件都没下,
    失败清单却是空的, 最后还报安装完成"这种事, 而当时的测试**完全没有 import
    pclpy.core.resources**, 所以一点都测不出来。

    覆盖(全程离线, 不真下载):
      * 合成索引 5 个文件 → 索引条数 == 进 pending 条数 == 真正落盘(sha1 对得上)条数;
      * 本机复用必须过 sha1: 同名同大小但内容不同 → 不许复用(要真下载);
        内容完全一致 → 必须复用(0 次下载);
      * 有文件下不下来 → 必须写 .pclpy_installing, 且状态文案含"未完成";
      * 目标文件在磁盘上被改坏(上次装坏的半成品) → 必须重下;
      * B2 跳过路径: 索引里 ``env.client == "unsupported"`` 的文件**不下载、不落盘、
        不算失败/未完成**(即使它同时还没有下载地址, 也只算"跳过"不算"缺地址"),
        ``optional`` 保持照装, 其余文件正常落盘, 版本**不许**被标成未完成。

    网络防护: 下载层换成 stub, urllib.request.urlopen 换成"一调用就抛",
    所以这条测试只要真发一次网络请求就会红。
    """
    real_urlopen = urllib.request.urlopen
    real_http_json = remote.http_json
    real_download_file = remote.download_file
    real_resolve_name = resources._resolve_modpack_name
    net = {"urlopen": 0, "http_json": 0}
    downloads = []          # stub 收到的 (url, dest)
    payloads = {}           # url -> 应该写进 dest 的内容
    fail_urls = set()       # 这些 url 永远下不下来

    def _no_urlopen(*args, **kwargs):
        net["urlopen"] += 1
        raise AssertionError("测试不允许联网: urllib.request.urlopen 被调用了")

    def _no_http_json(*args, **kwargs):
        net["http_json"] += 1
        return None

    def _stub_download(url, dest, source="official", progress_cb=None, cancel_cb=None,
                       timeout=30):
        """替身下载层: 不碰网络, 按 url 把预置内容写到 dest。"""
        downloads.append((str(url), str(dest)))
        if str(url) in fail_urls:
            return False
        data = payloads.get(str(url))
        if data is None:
            return False
        folder = os.path.dirname(os.path.abspath(str(dest)))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(str(dest), "wb") as handle:
            handle.write(data)
        return True

    def _sha1(data):
        return hashlib.sha1(data).hexdigest()

    def _file_sha1(path):
        if not os.path.isfile(path):
            return ""
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()

    def _entry(rel_path, data, env=None, with_download=True):
        """合成一条索引条目。

        ``env`` 写进条目的 ``env`` 字段(``{"client": ...}``, 用来测 B2 的跳过路径);
        ``with_download=False`` 造"没有 downloads 地址"的条目(典型是 CurseForge 托管的)。
        """
        item = {"path": rel_path,
                "hashes": {"sha1": _sha1(data)},
                "fileSize": len(data),
                "downloads": (["https://pclpy.invalid/" + rel_path.replace("/", "_")]
                              if with_download else [])}
        if env is not None:
            item["env"] = env
        return item

    def _make_pack(path, entries):
        index = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
                 "name": "pclpy-test-pack",
                 "dependencies": {"minecraft": _PACK_MC},
                 "files": entries}
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("modrinth.index.json", json.dumps(index))
            zf.writestr("overrides/config/pclpy.toml", "k = 1")
        return path

    def _install(root, entries, name, progress=None):
        # 先写一个原版 json: ensure_modpack_parent 认为原版已经装好, 于是不会去联网装原版
        mc_dir = os.path.join(root, "versions", _PACK_MC)
        os.makedirs(mc_dir, exist_ok=True)
        with open(os.path.join(mc_dir, _PACK_MC + ".json"), "w", encoding="utf-8") as handle:
            json.dump({"id": _PACK_MC, "type": "release", "libraries": [],
                       "mainClass": "net.minecraft.client.main.Main",
                       "arguments": {"game": []}}, handle)
        pack = _make_pack(os.path.join(root, name + ".mrpack"), entries)
        seen = progress if progress is not None else []
        version_id = resources.install_modpack(
            pack, root, name, cfg=None,
            progress_cb=lambda percent, text: seen.append((int(percent), str(text))))
        return version_id, seen

    def _dest(root, version_id, entry):
        return os.path.join(root, "versions", version_id,
                            str(entry["path"]).replace("/", os.sep))

    def _landed(root, version_id, entries):
        """真正落盘(存在且 sha1 对得上)的文件数。"""
        count = 0
        for item in entries:
            if _file_sha1(_dest(root, version_id, item)) == _sha1_of(item):
                count += 1
        return count

    def _sha1_of(entry):
        return str(((entry.get("hashes") or {}).get("sha1")) or "").lower()

    def _pending_total(progress):
        """进度文案是 "下载额外文件 n/总数" → 取最大分母就是 len(pending)。"""
        best = 0
        for _percent, text in progress:
            for _done, total in re.findall(r"(\d+)/(\d+)", text):
                best = max(best, int(total))
        return best

    def _part_leftovers(root):
        found = []
        for base, _dirs, names in os.walk(root):
            for name in names:
                if name.endswith(".part"):
                    found.append(os.path.join(base, name))
        return found

    def _mark(root, version_id):
        return os.path.join(root, "versions", version_id, ".pclpy_installing")

    try:
        remote.download_file = _stub_download
        remote.http_json = _no_http_json
        urllib.request.urlopen = _no_urlopen

        # ---------------------------------------------- ④-1 条数: 索引 == pending == 落盘
        root1 = os.path.join(_TMP, "pack_counts")
        specs1 = [("mods/pclpy_t1_%d.jar" % i, b"payload-%d" % i) for i in range(5)]
        entries1 = [_entry(rel, data) for rel, data in specs1]
        payloads.clear()
        downloads.clear()
        fail_urls.clear()
        for item, (_rel, data) in zip(entries1, specs1):
            payloads[item["downloads"][0]] = data
        version1, progress1 = _install(root1, entries1, "PackCounts")
        check("④-1 合成索引 5 个文件", len(entries1) == 5, len(entries1))
        check("④-1 索引条数 == 进 pending 条数", _pending_total(progress1) == 5,
              "pending=%r progress=%r" % (_pending_total(progress1), progress1[-3:]))
        check("④-1 进 pending 条数 == 落盘条数", _landed(root1, version1, entries1) == 5,
              _landed(root1, version1, entries1))
        check("④-1 每个 pending 都走了一次下载(stub 收到 5 次)", len(downloads) == 5,
              len(downloads))
        check("④-1 下齐后目录里没有 .part 残留", _part_leftovers(root1) == [],
              _part_leftovers(root1))
        check("④-1 下齐 → 不写未完成标记", not os.path.isfile(_mark(root1, version1)),
              _mark(root1, version1))

        # ---------------------------------------------- ④-2 复用必须过 sha1
        root2 = os.path.join(_TMP, "pack_reuse")
        real_bad = b"REAL-CONTENT-AAA"       # 16 字节
        fake_bad = b"FAKE-CONTENT-AAA"       # 同样 16 字节, 内容不同
        real_ok = b"REAL-CONTENT-BBB"
        entries2 = [_entry("mods/pclpy_decoy.jar", real_bad),
                    _entry("mods/pclpy_reuse.jar", real_ok)]
        payloads.clear()
        downloads.clear()
        fail_urls.clear()
        for item, data in zip(entries2, (real_bad, real_ok)):
            payloads[item["downloads"][0]] = data
        # 同名同大小但内容不同(模拟"别的包/别的版本里那个同名文件")
        decoy_dir = os.path.join(root2, "versions", "zz-decoy", "mods")
        os.makedirs(decoy_dir, exist_ok=True)
        with open(os.path.join(decoy_dir, "pclpy_decoy.jar"), "wb") as handle:
            handle.write(fake_bad)
        # 同名同大小且内容一致 → 应该被复用
        reuse_dir = os.path.join(root2, "versions", "zz-reuse", "mods")
        os.makedirs(reuse_dir, exist_ok=True)
        with open(os.path.join(reuse_dir, "pclpy_reuse.jar"), "wb") as handle:
            handle.write(real_ok)
        version2, progress2 = _install(root2, entries2, "PackReuse")
        decoy_url = entries2[0]["downloads"][0]
        reuse_url = entries2[1]["downloads"][0]
        decoy_dest = _dest(root2, version2, entries2[0])
        reuse_dest = _dest(root2, version2, entries2[1])
        check("④-2 同名同大小但 sha1 不同 → 不复用, 真下载",
              any(url == decoy_url for url, _dest_path in downloads)
              and _file_sha1(decoy_dest) == _sha1(real_bad),
              "%r sha1=%s" % ([u for u, _d in downloads], _file_sha1(decoy_dest)))
        check("④-2 内容一致 → 复用, 0 次下载",
              not any(url == reuse_url for url, _dest_path in downloads),
              [u for u, _d in downloads])
        check("④-2 复用过来的内容正确", _file_sha1(reuse_dest) == _sha1(real_ok),
              _file_sha1(reuse_dest))
        check("④-2 复用后两个文件都在盘上", _landed(root2, version2, entries2) == 2,
              _landed(root2, version2, entries2))
        check("④-2 复用的文件没有把错误内容带进来",
              _file_sha1(decoy_dest) != _sha1(fake_bad), _file_sha1(decoy_dest))

        # ---------------------------------------------- ④-3 有文件下不下来 → 未完成
        root3 = os.path.join(_TMP, "pack_fail")
        ok3 = b"OK-CONTENT-3"
        bad3 = b"BAD-CONTENT-3"
        entries3 = [_entry("mods/pclpy_ok.jar", ok3), _entry("mods/pclpy_bad.jar", bad3)]
        payloads.clear()
        downloads.clear()
        fail_urls.clear()
        payloads[entries3[0]["downloads"][0]] = ok3
        payloads[entries3[1]["downloads"][0]] = bad3
        fail_urls.add(entries3[1]["downloads"][0])          # 这个 url 永远失败
        version3, progress3 = _install(root3, entries3, "PackFail")
        check("④-3 有文件下不下来 → 写 .pclpy_installing",
              os.path.isfile(_mark(root3, version3)), _mark(root3, version3))
        check("④-3 状态文案含「未完成」",
              any("未完成" in text for _percent, text in progress3), progress3[-2:])
        check("④-3 失败不影响别的文件落盘", _landed(root3, version3, entries3) == 1,
              _landed(root3, version3, entries3))
        check("④-3 成功那个文件内容正确",
              _file_sha1(_dest(root3, version3, entries3[0])) == _sha1(ok3))

        # ---------------------------------------------- ④-4 目标文件被改坏 → 重下
        root4 = os.path.join(_TMP, "pack_broken")
        good4 = b"GOOD-CONTENT-4"
        broken4 = b"HALF-CONTENT-4"          # 同样 14 字节, 内容不同(半个文件)
        entries4 = [_entry("mods/pclpy_fixed.jar", good4)]
        payloads.clear()
        downloads.clear()
        fail_urls.clear()
        payloads[entries4[0]["downloads"][0]] = good4
        # 名字解析不是这条用例要测的: 固定成同一个名字, 好把"上次装坏的半成品"
        # 预先放进目标版本目录(否则已存在的版本目录会让安装器自动改名成 xxx-2)
        resources._resolve_modpack_name = lambda _root, wanted: (str(wanted), "")
        broken_dest = os.path.join(root4, "versions", "PackBroken", "mods",
                                   "pclpy_fixed.jar")
        os.makedirs(os.path.dirname(broken_dest), exist_ok=True)
        with open(broken_dest, "wb") as handle:
            handle.write(broken4)
        version4, progress4 = _install(root4, entries4, "PackBroken")
        check("④-4 磁盘上被改坏的文件 → 重新下载",
              any(url == entries4[0]["downloads"][0] for url, _dest_path in downloads),
              [u for u, _d in downloads])
        check("④-4 重下后内容正确", _file_sha1(broken_dest) == _sha1(good4),
              _file_sha1(broken_dest))
        check("④-4 重下成功 → 不写未完成标记",
              not os.path.isfile(_mark(root4, version4)), _mark(root4, version4))

        # ---------------------------------------------- ④-5 B2: env.client == "unsupported" 的跳过路径
        # 索引: 2 个正常/可选文件 + 2 个"客户端不支持"的文件(其中一个**连下载地址都没有**)。
        # 要求: unsupported 的不下载、不落盘、不算失败/未完成; optional 照装; 其余照落盘;
        #       版本不许被标成未完成(否则装好的包会在列表里消失)。
        root5 = os.path.join(_TMP, "pack_skip")
        normal5 = b"NORMAL-CONTENT-5"
        optional5 = b"OPTIONAL-CONTENT-5"
        server5 = b"SERVER-CONTENT-5"
        server5b = b"SERVER-CONTENT-5B"
        entries5 = [_entry("mods/pclpy_normal.jar", normal5),
                    _entry("mods/pclpy_optional.jar", optional5,
                           env={"client": "optional", "server": "optional"}),
                    _entry("mods/pclpy_serveronly.jar", server5,
                           env={"client": "unsupported", "server": "required"}),
                    _entry("mods/pclpy_serveronly_nourl.jar", server5b,
                           env={"client": "unsupported", "server": "required"},
                           with_download=False)]
        payloads.clear()
        downloads.clear()
        fail_urls.clear()
        payloads[entries5[0]["downloads"][0]] = normal5
        payloads[entries5[1]["downloads"][0]] = optional5
        payloads[entries5[2]["downloads"][0]] = server5      # 有地址也不许下载
        version5, progress5 = _install(root5, entries5, "PackSkip")
        normal_url5 = entries5[0]["downloads"][0]
        optional_url5 = entries5[1]["downloads"][0]
        skip_url5 = entries5[2]["downloads"][0]
        check("④-5 unsupported 的文件**不被下载**",
              not any(url == skip_url5 for url, _dest_path in downloads),
              [u for u, _d in downloads])
        check("④-5 只有 2 个非 unsupported 的文件走了下载",
              len(downloads) == 2, downloads)
        check("④-5 unsupported 的文件**不落盘**",
              not os.path.isfile(_dest(root5, version5, entries5[2])),
              _dest(root5, version5, entries5[2]))
        check("④-5 unsupported 的文件**不计入 pending**",
              _pending_total(progress5) == 2, _pending_total(progress5))
        check("④-5 optional 照旧安装(真下载 + 落盘)",
              any(url == optional_url5 for url, _dest_path in downloads)
              and _file_sha1(_dest(root5, version5, entries5[1])) == _sha1(optional5),
              "%r %s" % ([u for u, _d in downloads],
                         _file_sha1(_dest(root5, version5, entries5[1]))))
        check("④-5 其余文件正常落盘",
              _file_sha1(_dest(root5, version5, entries5[0])) == _sha1(normal5),
              _file_sha1(_dest(root5, version5, entries5[0])))
        check("④-5 unsupported 且**无下载地址**的文件不算「缺少下载地址」",
              not any("缺少下载地址" in text for _percent, text in progress5),
              progress5[-2:])
        check("④-5 跳过条数在进度文案里可见(不算失败)",
              any("跳过" in text and "客户端不支持" in text for _percent, text in progress5)
              and any("已跳过 2 个" in text for _percent, text in progress5),
              progress5[-2:])
        check("④-5 unsupported 的文件不算失败(文案里没有「未完成」)",
              not any("未完成" in text for _percent, text in progress5), progress5[-2:])
        check("④-5 版本**没有被标成未完成**",
              not os.path.isfile(_mark(root5, version5)), _mark(root5, version5))

        # ---------------------------------------------- 全程零网络
        check("④-0 全程 0 次真实网络请求", net["urlopen"] == 0 and net["http_json"] == 0,
              net)
    finally:
        remote.download_file = real_download_file
        remote.http_json = real_http_json
        urllib.request.urlopen = real_urlopen
        resources._resolve_modpack_name = real_resolve_name


def test_imports():
    for name in ("paths", "config", "accounts", "versions", "mods", "remote",
                 "install", "launch", "packexport", "catalog"):
        module = importlib.import_module("pclpy.core." + name)
        check("import pclpy.core.%s" % name, module is not None)


def main():
    tests = [
        test_imports,
        test_paths,
        test_config,
        test_parse_version_id,
        test_accounts,
        test_scan_folder,
        test_group_versions,
        test_catalog,
        test_remote,
        test_mods,
        test_install_helpers,
        test_launch_helpers,
        test_packexport,
        test_progress_callback_order,
        test_modpack_install_regression,
    ]
    for test in tests:
        run(test)
    print("")
    if _FAILURES:
        print("失败 %d 项:" % len(_FAILURES))
        for item in _FAILURES:
            print("  - %s" % item)
        try:
            shutil.rmtree(_TMP, ignore_errors=True)
        except Exception:
            pass
        sys.exit(1)
    print("ALL CORE TESTS PASSED")
    try:
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
