import QtQuick
import QtQuick.Controls.Basic
import "../../components"
import "../../components/Ui.js" as Ui

// 版本设置 - 设置(该版本独立设置)
Item {
    id: page

    property var host: null
    property bool showBanner: true

    // versionSettings / settings 都是运行时注入的 context property。关窗销毁阶段 QML 仍会
    // 对存活的绑定再求值一次, 那时它们已经是 null, 直接读属性或调 .isFollow()/.value()/
    // .javaHint() 会抛 "Cannot read property 'x' of null" / "Cannot call method 'y' of
    // null"。下面做成空安全(写法对齐 Main.qml 的 syncAnimationScale 与 OtherSettings.qml
    // 的 settingValue), 正常运行(后端有效)时取值路径与原来完全一致。
    readonly property bool vsReady: (typeof versionSettings !== "undefined"
                                    && versionSettings !== null)
    readonly property bool gsReady: (typeof settings !== "undefined" && settings !== null)

    // 取不到后端时的回落值逐个按"后端此时本来会返回什么"来定:
    //   value(key)        → ""(配置里没有这一项时后端返回 "", 所以原有的
    //                        `|| "auto"` / `Number(...)` 兜底语义不变)
    //   isFollow(key)     → true(该版本没有写过这一项时后端就是 true, 即"跟随全局设置")
    //   javaList          → [](只影响两个函数里的循环, 下标语义与原来一致)
    //   javaHint()        → ""(不显示"将会使用: …"这句提示)
    //   totalMemoryMb / autoMemoryMb → 1024(后端 autoMemoryMb 的下限值, 也保证滑条的
    //                        to 仍然 >= 1024), usedMemoryMb → 0
    function vsValue(key, fallback) {
        if (!page.vsReady || typeof versionSettings.value !== "function")
            return fallback;
        return versionSettings.value(key);
    }

    function vsFollow(key, fallback) {
        if (!page.vsReady || typeof versionSettings.isFollow !== "function")
            return fallback;
        return versionSettings.isFollow(key);
    }

    function javaList() {
        if (!page.gsReady)
            return [];
        return settings.javaList;
    }

    function javaHintText() {
        if (!page.gsReady || typeof settings.javaHint !== "function")
            return "";
        return settings.javaHint().replace("将会使用:  ", "将会使用: ");
    }

    function totalMemoryMb() {
        return page.gsReady ? settings.totalMemoryMb : 1024;
    }

    function usedMemoryMb() {
        return page.gsReady ? settings.usedMemoryMb : 0;
    }

    function autoMemoryMb() {
        return page.gsReady ? settings.autoMemoryMb : 1024;
    }

    function javaOptions() {
        var list = ["跟随全局设置", "自动选择"];
        var javas = page.javaList();
        for (var i = 1; i < javas.length; i++)
            list.push(javas[i].label);
        return list;
    }

    function javaIndex() {
        if (page.vsFollow("launch.java_path", true))
            return 0;
        var current = page.vsValue("launch.java_path", "") || "auto";
        if (current === "auto")
            return 1;
        var javas = page.javaList();
        for (var i = 1; i < javas.length; i++) {
            if (javas[i].path === current)
                return i + 1;
        }
        return 0;
    }

    function memoryMode() {
        if (page.vsFollow("launch.memory_mode", true))
            return "follow";
        return page.vsValue("launch.memory_mode", "") || "follow";
    }

    function isolationIndex() {
        if (page.vsFollow("launch.isolation", true))
            return 0;
        return page.vsValue("launch.isolation", "") === "close" ? 2 : 1;
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

            Rectangle {
                width: parent.width
                height: 38
                visible: page.showBanner
                color: theme.primarySoft
                radius: 4
                border.width: 1
                border.color: "#CFE2FA"

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: "这些设置只对该游戏版本生效，不影响其他版本。"
                    font.pixelSize: 12
                    color: theme.primary
                }
                Image {
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    width: 14
                    height: 14
                    source: "image://icon/close?color=" + encodeURIComponent(theme.primary) + "&size=14"
                    sourceSize.width: 14
                    sourceSize.height: 14
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.showBanner = false
                    }
                }
            }

            Card {
                title: "启动选项"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "版本隔离"
                    PclComboBox {
                        width: parent.width
                        model: Ui.VERSION_ISOLATION
                        textRoleName: "label"
                        currentIndex: page.isolationIndex()
                        onActivated: if (page.vsReady)
                                         versionSettings.setValue("launch.isolation",
                                             Ui.valueAt(Ui.VERSION_ISOLATION, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "游戏窗口标题"
                    PclTextField {
                        width: parent.width
                        placeholderText: "跟随全局设置"
                        text: page.vsFollow("launch.window_title", true)
                              ? "" : page.vsValue("launch.window_title", "")
                        onEditingFinished: {
                            if (!page.vsReady)
                                return;
                            if (text === "")
                                versionSettings.setValue("launch.window_title", "follow");
                            else
                                versionSettings.setValue("launch.window_title", text);
                        }
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "自定义信息"
                    PclTextField {
                        width: parent.width
                        placeholderText: "跟随全局设置"
                        text: page.vsFollow("launch.custom_info", true)
                              ? "" : page.vsValue("launch.custom_info", "")
                        onEditingFinished: {
                            if (!page.vsReady)
                                return;
                            if (text === "")
                                versionSettings.setValue("launch.custom_info", "follow");
                            else
                                versionSettings.setValue("launch.custom_info", text);
                        }
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "Java"
                    PclComboBox {
                        width: parent.width
                        model: page.javaOptions()
                        currentIndex: page.javaIndex()
                        onActivated: {
                            if (!page.vsReady)
                                return;
                            if (currentIndex === 0) {
                                versionSettings.setValue("launch.java_path", "follow");
                            } else if (currentIndex === 1) {
                                versionSettings.setValue("launch.java_path", "auto");
                            } else {
                                versionSettings.setValue("launch.java_path",
                                                         page.javaList()[currentIndex - 1].path);
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 30
                    color: theme.primarySoft
                    radius: 3

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.javaHintText()
                        font.pixelSize: 11
                        color: theme.primary
                        elide: Text.ElideMiddle
                        width: parent.width - 20
                    }
                }
            }

            Card {
                title: "内存分配"
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 10

                    Column {
                        width: 180
                        spacing: 6

                        PclRadioButton {
                            text: "跟随全局设置"
                            checked: page.memoryMode() === "follow"
                            onClicked: if (page.vsReady)
                                           versionSettings.setValue("launch.memory_mode", "follow")
                        }
                        PclRadioButton {
                            text: "自动配置"
                            checked: page.memoryMode() === "auto"
                            onClicked: if (page.vsReady)
                                           versionSettings.setValue("launch.memory_mode", "auto")
                        }
                        PclRadioButton {
                            id: customRadio
                            text: "自定义"
                            checked: page.memoryMode() === "custom"
                            onClicked: {
                                if (!page.vsReady)
                                    return;
                                versionSettings.setValue("launch.memory_mode", "custom");
                                versionSettings.setValue("launch.memory_mb", page.autoMemoryMb());
                            }
                        }
                    }

                    Column {
                        width: parent.width - 190
                        spacing: 4

                        PclSlider {
                            id: memorySlider
                            width: parent.width
                            enabled: customRadio.checked
                            from: 512
                            to: Math.max(1024, page.totalMemoryMb())
                            stepSize: 256
                            value: customRadio.checked
                                   ? Number(page.vsValue("launch.memory_mb", ""))
                                   : page.autoMemoryMb()
                            onPressedChanged: {
                                if (!pressed && customRadio.checked && page.vsReady)
                                    versionSettings.setValue("launch.memory_mb", Math.round(value));
                            }
                        }
                        Text {
                            text: customRadio.checked
                                  ? "分配内存: " + Ui.gb(Number(page.vsValue("launch.memory_mb", "")))
                                  : "分配内存: 由全局设置决定"
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "启动游戏前进行内存优化"
                    PclComboBox {
                        width: parent.width
                        model: Ui.MEMORY_OPTION
                        textRoleName: "label"
                        currentIndex: page.vsFollow("launch.optimize_memory", true)
                                      ? 0 : Ui.indexOfValue(Ui.MEMORY_OPTION,
                                            page.vsValue("launch.optimize_memory", "") ? "on" : "off")
                        onActivated: {
                            if (!page.vsReady)
                                return;
                            var value = Ui.valueAt(Ui.MEMORY_OPTION, currentIndex);
                            if (value === "follow")
                                versionSettings.setValue("launch.optimize_memory", "follow");
                            else
                                versionSettings.setValue("launch.optimize_memory", value === "on");
                        }
                    }
                }

                MemoryBar {
                    width: parent.width
                    totalMb: page.totalMemoryMb()
                    usedMb: page.usedMemoryMb()
                    allocMb: customRadio.checked
                             ? Number(page.vsValue("launch.memory_mb", ""))
                             : page.autoMemoryMb()
                }
            }

            Card {
                title: "服务器"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "登录方式"
                    PclComboBox {
                        width: parent.width
                        model: Ui.LOGIN_MODE
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.LOGIN_MODE,
                                      page.vsValue("server.login_mode", "") || "both")
                        onActivated: if (page.vsReady)
                                         versionSettings.setValue("server.login_mode",
                                             Ui.valueAt(Ui.LOGIN_MODE, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "自动进入服务器"
                    PclTextField {
                        width: parent.width
                        placeholderText: "留空则不自动进入"
                        text: page.vsFollow("server.auto_join", true)
                              ? "" : page.vsValue("server.auto_join", "")
                        onEditingFinished: if (page.vsReady)
                                               versionSettings.setValue("server.auto_join", text)
                    }
                }
            }

            Accordion {
                width: parent.width
                title: "高级选项"
                expanded: false

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "JVM 参数"
                    PclTextField {
                        width: parent.width
                        placeholderText: "跟随全局设置"
                        text: page.vsFollow("launch.jvm_args", true)
                              ? "" : page.vsValue("launch.jvm_args", "")
                        onEditingFinished: {
                            if (!page.vsReady)
                                return;
                            if (text === "")
                                versionSettings.setValue("launch.jvm_args", "follow");
                            else
                                versionSettings.setValue("launch.jvm_args", text);
                        }
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "游戏参数"
                    PclTextField {
                        width: parent.width
                        placeholderText: "跟随全局设置"
                        text: page.vsFollow("launch.game_args", true)
                              ? "" : page.vsValue("launch.game_args", "")
                        onEditingFinished: {
                            if (!page.vsReady)
                                return;
                            if (text === "")
                                versionSettings.setValue("launch.game_args", "follow");
                            else
                                versionSettings.setValue("launch.game_args", text);
                        }
                    }
                }
            }

            Item {
                width: parent.width
                height: 48

                PclButton {
                    anchors.centerIn: parent
                    kind: "primary"
                    text: "全局设置"
                    iconName: "next"
                    implicitWidth: 160
                    implicitHeight: 34
                    onClicked: if (page.vsReady) versionSettings.openGlobalSettings()
                }
            }
        }
    }
}
