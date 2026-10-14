import QtQuick
import QtQuick.Controls.Basic
import "../../components"
import "../../components/Ui.js" as Ui

// 设置 - 其他
// 注意: 按需求, 原模板中的「社区资源」设置分组未实现。
Item {
    id: page

    property var host: null

    // settings 是运行时注入的 context property: 求值早于注入、以及关窗销毁阶段
    // (QML 仍会对存活的绑定再求值一次)时它是 null, 直接取 .value/.flag 会抛
    // "Cannot call method 'value' of null"。这里做空安全, 取不到时回落到默认值
    // (即 pclpy/core/config.py 里 DEFAULTS 中该项的值, 也就是"配置里没有这一项"
    // 时后端本来会返回的值), 正常运行(settings 有效)时取值路径与原来完全一致。
    function settingValue(key, fallback) {
        if (typeof settings === "undefined" || settings === null
                || typeof settings.value !== "function")
            return fallback;
        return settings.value(key);
    }

    function settingFlag(key, fallback) {
        if (typeof settings === "undefined" || settings === null
                || typeof settings.flag !== "function")
            return fallback;
        return settings.flag(key);
    }

    function sourceIndex(key) {
        // 取不到时给 "", 由后面的 || "official" 决定下拉框落到"官方源"(与原来一致)
        return Ui.indexOfValue(Ui.DOWNLOAD_SOURCE, page.settingValue(key, "") || "official");
    }

    // ---------------------------------------------------------------- 下载分片调参
    // 这一段的默认值 / 取值范围与后端严格对齐, 三处必须一致:
    //   1. pclpy/core/remote.py 顶部  MULTI_MAX_SEGMENTS / MULTI_START_SEGMENTS /
    //      MULTI_MAX_CONNECTIONS / MULTI_MIN_SIZE / MULTI_LOW_SPEED_BPS 与 *_RANGE;
    //   2. pclpy/core/config.py 的 DEFAULTS["download"]:
    //        segments_enabled=True / segments_max=8 / segments_start=4 /
    //        connections=32 / min_size_mb=1 / slow_kbps=1024 / debug_log=False;
    //   3. 本文件的 downloadTuningDefault() / downloadTuningRange()。
    // 生效顺序: 环境变量 > 设置项 > 代码默认值; 每次下载开始前重读一次设置项,
    // 所以这里改完「下一次下载」就生效, 不用重启进程。
    readonly property var downloadTuningKeys: [
        "segments_enabled", "segments_max", "segments_start",
        "connections", "min_size_mb", "slow_kbps", "debug_log"
    ]

    function downloadTuningDefault(name) {
        switch (name) {
        case "segments_enabled": return true;
        case "segments_max": return 8;
        case "segments_start": return 4;
        case "connections": return 32;
        case "min_size_mb": return 1;
        case "slow_kbps": return 1024;
        case "debug_log": return false;
        }
        return 0;
    }

    // [最小值, 最大值]; 与 remote.py 里的 *_RANGE 一致
    function downloadTuningRange(name) {
        switch (name) {
        case "segments_max": return [1, 64];
        case "segments_start": return [1, 64];
        case "connections": return [1, 256];
        case "min_size_mb": return [0, 1024];
        case "slow_kbps": return [0, 1048576];
        }
        return [0, 0];
    }

    // 读一个数值设置项: 缺失 / 非数字 / 越界时回落到默认值。
    // 画面上显示的永远是"可以被下载层接受"的数, 非法值不会留在输入框里。
    function downloadTuningNumber(name) {
        var fallback = page.downloadTuningDefault(name);
        var range = page.downloadTuningRange(name);
        var raw = page.settingValue("download." + name, fallback);
        var value = (typeof raw === "number") ? raw : parseInt(String(raw), 10);
        if (isNaN(value) || value < range[0] || value > range[1])
            return fallback;
        return value;
    }

    // 写一个数值设置项: 解析失败或越界一律回落到默认值(下载层绝不会拿到 0/负数)。
    function saveDownloadTuningNumber(name, text) {
        var fallback = page.downloadTuningDefault(name);
        var range = page.downloadTuningRange(name);
        var value = parseInt(String(text), 10);
        if (isNaN(value) || value < range[0] || value > range[1])
            value = fallback;
        settings.setValue("download." + name, value);
        return value;
    }

    // 「当前实际生效值」: 直接问后端(它读的是下载层算出来的值, 含环境变量覆盖)
    function tuningText() {
        if (typeof settings === "undefined" || settings === null)
            return "…";
        var text = settings.downloadTuning;
        return (text === undefined || text === null || text === "") ? "…" : String(text);
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Column {
            x: 16
            y: 12
            width: scroll.availableWidth - 32
            spacing: 10
            bottomPadding: 18
            // 显式给出内容高度: 否则 ScrollView 的 contentHeight 只在初次布局时
            // 算一次, 之后展开手风琴长出来的部分滚不到 —— 实测调试选项从 false 展成
            // true 后 contentHeight 一直停在 797.4, 新增的行被裁在视口外; 绑定
            // childrenRect 后同一操作变成 1236.4, 新行可滚到(REACHABLE=True)。
            height: childrenRect.height + bottomPadding

            Card {
                title: "下载"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "文件下载源"
                    PclComboBox {
                        width: parent.width
                        model: Ui.DOWNLOAD_SOURCE
                        textRoleName: "label"
                        currentIndex: page.sourceIndex("download.source")
                        onActivated: settings.setValue("download.source",
                                                       Ui.valueAt(Ui.DOWNLOAD_SOURCE, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "版本列表源"
                    PclComboBox {
                        width: parent.width
                        model: Ui.DOWNLOAD_SOURCE
                        textRoleName: "label"
                        currentIndex: page.sourceIndex("download.list_source")
                        onActivated: settings.setValue("download.list_source",
                                                       Ui.valueAt(Ui.DOWNLOAD_SOURCE, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "最大线程数"
                    Column {
                        width: parent.width
                        spacing: 2
                        PclSlider {
                            id: threadSlider
                            width: parent.width
                            from: 1
                            to: 64
                            stepSize: 1
                            value: Number(page.settingValue("download.max_threads", 32)) || 32
                            onPressedChanged: if (!pressed) settings.setValue("download.max_threads", Math.round(value))
                        }
                        Text {
                            text: Math.round(threadSlider.value) + " 线程"
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "速度限制"
                    Column {
                        width: parent.width
                        spacing: 2
                        PclSlider {
                            id: speedSlider
                            width: parent.width
                            from: 0
                            to: 100
                            stepSize: 1
                            value: Ui.speedLimitToSlide(Number(page.settingValue("download.speed_limit_kb", 0)))
                            onPressedChanged: if (!pressed) settings.setValue("download.speed_limit_kb",
                                                                             Ui.speedLimitFromSlide(value))
                        }
                        Text {
                            text: Ui.limitText(Ui.speedLimitFromSlide(speedSlider.value))
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: "请在  启动 → 版本选择 → 文件夹列表  中更改下载目标文件夹。\n在某个文件夹或游戏版本上右键，即可选择打开对应文件夹。"
                    font.pixelSize: 11
                    color: theme.textHint
                    lineHeight: 1.3
                }

                PclCheckBox {
                    text: "在正版登录时验证 SSL 证书"
                    checked: page.settingFlag("download.verify_ssl", true)
                    onClicked: settings.setValue("download.verify_ssl", checked)
                }
            }

            Card {
                title: "辅助功能"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "游戏更新提示"
                    Row {
                        spacing: 24
                        PclCheckBox {
                            text: "正式版更新提示"
                            checked: page.settingFlag("update.release", true)
                            onClicked: settings.setValue("update.release", checked)
                        }
                        PclCheckBox {
                            text: "测试版更新提示"
                            checked: page.settingFlag("update.snapshot", false)
                            onClicked: settings.setValue("update.snapshot", checked)
                        }
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "游戏语言"
                    PclCheckBox {
                        text: "自动设置为中文"
                        checked: page.settingFlag("launch.game_language_zh", true)
                        onClicked: settings.setValue("launch.game_language_zh", checked)
                    }
                }
            }

            Card {
                title: "启动器"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "启动器更新"
                    PclComboBox {
                        width: parent.width
                        model: Ui.UPDATE_MODE
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.UPDATE_MODE, page.settingValue("launcher.update_mode", "auto") || "auto")
                        onActivated: settings.setValue("launcher.update_mode",
                                                       Ui.valueAt(Ui.UPDATE_MODE, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "启动器公告"
                    PclComboBox {
                        width: parent.width
                        model: Ui.ANNOUNCE
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.ANNOUNCE, page.settingValue("launcher.announce", "all") || "all")
                        onActivated: settings.setValue("launcher.announce",
                                                       Ui.valueAt(Ui.ANNOUNCE, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "缓存文件夹"
                    PclTextField {
                        width: parent.width
                        placeholderText: "默认"
                        text: page.settingValue("launcher.cache_dir", "")
                        onEditingFinished: settings.setValue("launcher.cache_dir", text)
                    }
                }

                PclCheckBox {
                    text: "匿名数据收集"
                    checked: page.settingFlag("ui.anonymous_stats", true)
                    onClicked: settings.setValue("ui.anonymous_stats", checked)
                }

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        text: "检查更新"
                        implicitWidth: 104
                        onClicked: settings.checkUpdate()
                    }
                    PclButton {
                        text: "导出设置"
                        implicitWidth: 104
                        onClicked: if (page.host) page.host.askExportSettings()
                    }
                    PclButton {
                        text: "导入设置"
                        implicitWidth: 104
                        onClicked: if (page.host) page.host.askImportSettings()
                    }
                }
            }

            Accordion {
                width: parent.width
                title: "调试选项"
                expanded: false
                // Accordion.qml 已经把 height 固定成"全展开高度", 这里不用再绑
                // implicitHeight(它是收起时的 45px)。

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "动画速度"
                    Column {
                        width: parent.width
                        spacing: 2
                        PclSlider {
                            id: animationSlider
                            width: parent.width
                            from: 0
                            to: 2
                            stepSize: 0.1
                            value: Number(page.settingValue("ui.animation_speed", 1.0))
                            onPressedChanged: if (!pressed) settings.setValue("ui.animation_speed", value)
                        }
                        Text {
                            text: Number(animationSlider.value).toFixed(1) + " 倍"
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }

                Row {
                    width: parent.width - 20
                    x: 10
                    spacing: 24

                    PclCheckBox {
                        text: "禁止在下载时从其他文件夹复制文件"
                        checked: page.settingFlag("download.keep_launcher_files", false)
                        onClicked: settings.setValue("download.keep_launcher_files", checked)
                    }
                    PclCheckBox {
                        text: "调试模式"
                        checked: page.settingFlag("ui.debug_mode", false)
                        onClicked: settings.setValue("ui.debug_mode", checked)
                    }
                    PclCheckBox {
                        text: "添加延迟"
                        checked: page.settingFlag("ui.add_delay", false)
                        onClicked: settings.setValue("ui.add_delay", checked)
                    }
                }

                // ---------------------------------------------------- 下载分片调参
                // 环境变量(见 pclpy/core/remote.py)仍然优先: 这里的设置是"没设
                // 环境变量时"用的值, 改完下一次下载生效, 不需要重启进程。
                Text {
                    width: parent.width - 20
                    x: 10
                    topPadding: 8
                    text: "— 下载分片调参 —"
                    font.pixelSize: 12
                    font.bold: true
                    color: theme.textTitle
                }

                Text {
                    width: parent.width - 20
                    x: 10
                    text: "只影响分片(多线程 Range)下载。生效顺序: 环境变量 > 此处设置 > 代码默认值, "
                          + "环境变量会覆盖此处设置; 改完下一次下载就生效, 不用重启。"
                    font.pixelSize: 11
                    color: theme.textHint
                    lineHeight: 1.3
                    wrapMode: Text.WordWrap
                }

                PclCheckBox {
                    x: 10
                    text: "启用分片下载 (多线程 Range)"
                    checked: page.settingFlag("download.segments_enabled", true)
                    onClicked: settings.setValue("download.segments_enabled", checked)
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "每文件最大段数"
                    Row {
                        spacing: 8
                        PclTextField {
                            id: segMaxField
                            width: 110
                            text: String(page.downloadTuningNumber("segments_max"))
                            onEditingFinished: text = String(page.saveDownloadTuningNumber("segments_max", text))
                        }
                        Text {
                            text: "1 - 64 (1 = 单流)"
                            font.pixelSize: 11
                            color: theme.textHint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "起步段数"
                    Row {
                        spacing: 8
                        PclTextField {
                            id: segStartField
                            width: 110
                            text: String(page.downloadTuningNumber("segments_start"))
                            onEditingFinished: text = String(page.saveDownloadTuningNumber("segments_start", text))
                        }
                        Text {
                            text: "1 - 64 (实测慢才一段段加满)"
                            font.pixelSize: 11
                            color: theme.textHint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "全局并发上限"
                    Row {
                        spacing: 8
                        PclTextField {
                            id: connsField
                            width: 110
                            text: String(page.downloadTuningNumber("connections"))
                            onEditingFinished: text = String(page.saveDownloadTuningNumber("connections", text))
                        }
                        Text {
                            text: "1 - 256 条 Range 连接(超出排队)"
                            font.pixelSize: 11
                            color: theme.textHint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "分片阈值"
                    Row {
                        spacing: 8
                        PclTextField {
                            id: minMbField
                            width: 110
                            text: String(page.downloadTuningNumber("min_size_mb"))
                            onEditingFinished: text = String(page.saveDownloadTuningNumber("min_size_mb", text))
                        }
                        Text {
                            text: "MB, 0 表示支持 Range 就切"
                            font.pixelSize: 11
                            color: theme.textHint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "低速阈值"
                    Row {
                        spacing: 8
                        PclTextField {
                            id: slowField
                            width: 110
                            text: String(page.downloadTuningNumber("slow_kbps"))
                            onEditingFinished: text = String(page.saveDownloadTuningNumber("slow_kbps", text))
                        }
                        Text {
                            text: "KB/s, 低于它才继续加段"
                            font.pixelSize: 11
                            color: theme.textHint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                PclCheckBox {
                    x: 10
                    text: "下载调试日志"
                    checked: page.settingFlag("download.debug_log", false)
                    onClicked: settings.setValue("download.debug_log", checked)
                }

                Text {
                    width: parent.width - 20
                    x: 10
                    text: "当前实际生效:  " + page.tuningText()
                    font.pixelSize: 11
                    color: theme.textSub
                    lineHeight: 1.3
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width - 20
                    x: 10
                    bottomPadding: 8
                    text: "非法或超出范围的输入会回落到默认值, 下载层拿不到 0 / 负数。"
                    font.pixelSize: 11
                    color: theme.textHint
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
