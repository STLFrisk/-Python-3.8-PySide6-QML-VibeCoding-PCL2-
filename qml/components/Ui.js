.pragma library

// 设置项的可选项集合: { label, value }

var ISOLATION = [
    { label: "隔离所有版本", value: "open" },
    { label: "仅隔离含 Mod 的版本", value: "mod" },
    { label: "不隔离", value: "close" }
];

var VERSION_ISOLATION = [
    { label: "跟随全局设置", value: "follow" },
    { label: "开启", value: "open" },
    { label: "关闭", value: "close" }
];

var VISIBILITY = [
    { label: "游戏启动后仍保持不变", value: "keep" },
    { label: "游戏启动后隐藏启动器", value: "hide" },
    { label: "游戏启动后最小化启动器", value: "minimize" }
];

var PRIORITY = [
    { label: "低", value: "low" },
    { label: "中 (平衡)", value: "normal" },
    { label: "高", value: "high" },
    { label: "实时", value: "realtime" }
];

var WINDOW_SIZE = [
    { label: "默认", value: "default" },
    { label: "最大化", value: "max" },
    { label: "自定义", value: "custom" }
];

var DOWNLOAD_SOURCE = [
    { label: "优先使用官方源，在加载缓慢时换用镜像源", value: "official" },
    { label: "优先使用镜像源，在加载缓慢时换用官方源", value: "mirror" },
    { label: "仅使用官方源", value: "official_only" },
    { label: "仅使用镜像源", value: "mirror_only" }
];

var UPDATE_MODE = [
    { label: "有新版本时自动下载", value: "auto" },
    { label: "有新版本时提示我", value: "prompt" },
    { label: "不检查更新", value: "off" }
];

var ANNOUNCE = [
    { label: "显示所有公告", value: "all" },
    { label: "仅显示重要公告", value: "important" },
    { label: "不显示公告", value: "off" }
];

var SKIN_MODEL = [
    { label: "Steve (经典)", value: "steve" },
    { label: "Alex (纤细)", value: "alex" }
];

var LOGIN_MODE = [
    { label: "正版登录或离线登录", value: "both" },
    { label: "仅离线登录", value: "offline" }
];

var MEMORY_OPTION = [
    { label: "跟随全局设置", value: "follow" },
    { label: "开启", value: "on" },
    { label: "关闭", value: "off" }
];

var VERSION_ICON = [
    { label: "自动", value: "auto" },
    { label: "草方块", value: "cube_grass" },
    { label: "砂岩", value: "cube_sand" },
    { label: "熔炉", value: "cube_gray" },
    { label: "南瓜", value: "cube_orange" }
];

var VERSION_CATEGORY = [
    { label: "自动", value: "auto" },
    { label: "原版", value: "normal" },
    { label: "模组", value: "modded" },
    { label: "整合包", value: "pack" },
    { label: "远古版本", value: "uncommon" }
];

function indexOfValue(list, value) {
    for (var i = 0; i < list.length; i++) {
        if (list[i].value === value)
            return i;
    }
    return 0;
}

function valueAt(list, index) {
    if (index >= 0 && index < list.length)
        return list[index].value;
    return "";
}

function labelAt(list, index) {
    if (index >= 0 && index < list.length)
        return list[index].label;
    return "";
}

function gb(mb) {
    return (mb / 1024.0).toFixed(1) + " GB";
}

function limitText(kb) {
    if (!kb || kb <= 0)
        return "不限速";
    if (kb >= 1024)
        return (kb / 1024.0).toFixed(1) + " MB/s";
    return kb + " KB/s";
}

function speedLimitFromSlide(v) {
    // 滑块 0..100 映射到 0..102400 KB/s(非线性)
    if (v <= 0)
        return 0;
    return Math.round(Math.pow(v / 100.0, 3) * 102400);
}

function speedLimitToSlide(kb) {
    if (!kb || kb <= 0)
        return 0;
    return Math.round(Math.pow(kb / 102400.0, 1 / 3.0) * 100);
}
