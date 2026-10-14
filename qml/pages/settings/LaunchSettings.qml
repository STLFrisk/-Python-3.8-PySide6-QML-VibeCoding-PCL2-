import QtQuick
import QtQuick.Controls.Basic
import "../../components"
import "../../components/Ui.js" as Ui

// 设置 - 启动
Item {
    id: page

    property var host: null

    function isolationIndex() {
        return Ui.indexOfValue(Ui.ISOLATION, settings.value("launch.default_isolation") || "open");
    }

    function visibilityIndex() {
        return Ui.indexOfValue(Ui.VISIBILITY, settings.value("launch.launcher_visibility") || "keep");
    }

    function priorityIndex() {
        return Ui.indexOfValue(Ui.PRIORITY, settings.value("launch.process_priority") || "normal");
    }

    function windowSizeIndex() {
        return Ui.indexOfValue(Ui.WINDOW_SIZE, settings.value("launch.window_size_mode") || "default");
    }

    function javaIndex() {
        var list = settings.javaList;
        var current = settings.value("launch.java_path") || "auto";
        for (var i = 0; i < list.length; i++) {
            if (list[i].path === current)
                return i;
        }
        return 0;
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

            Card {
                title: "启动选项"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "默认版本隔离"
                    PclComboBox {
                        width: parent.width
                        model: Ui.ISOLATION
                        textRoleName: "label"
                        currentIndex: page.isolationIndex()
                        onActivated: settings.setValue("launch.default_isolation",
                                                       Ui.valueAt(Ui.ISOLATION, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "游戏窗口标题"
                    PclTextField {
                        width: parent.width
                        placeholderText: "默认"
                        text: settings.value("launch.window_title")
                        onEditingFinished: settings.setValue("launch.window_title", text)
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "自定义信息"
                    PclTextField {
                        width: parent.width
                        placeholderText: "默认"
                        text: settings.value("launch.custom_info")
                        onEditingFinished: settings.setValue("launch.custom_info", text)
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "启动器可见性"
                    PclComboBox {
                        width: parent.width
                        model: Ui.VISIBILITY
                        textRoleName: "label"
                        currentIndex: page.visibilityIndex()
                        onActivated: settings.setValue("launch.launcher_visibility",
                                                       Ui.valueAt(Ui.VISIBILITY, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "进程优先级"
                    PclComboBox {
                        width: parent.width
                        model: Ui.PRIORITY
                        textRoleName: "label"
                        currentIndex: page.priorityIndex()
                        onActivated: settings.setValue("launch.process_priority",
                                                       Ui.valueAt(Ui.PRIORITY, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "窗口大小"
                    PclComboBox {
                        id: windowSizeCombo
                        width: parent.width
                        model: Ui.WINDOW_SIZE
                        textRoleName: "label"
                        currentIndex: page.windowSizeIndex()
                        onActivated: settings.setValue("launch.window_size_mode",
                                                       Ui.valueAt(Ui.WINDOW_SIZE, currentIndex))
                    }
                }

                // 选「自定义」时给出宽高输入框
                SettingRow {
                    width: parent.width
                    visible: Ui.valueAt(Ui.WINDOW_SIZE, windowSizeCombo.currentIndex) === "custom"
                    label: "窗口分辨率"
                    Row {
                        width: parent.width
                        spacing: 8

                        PclTextField {
                            width: (parent.width - 34) / 2
                            placeholderText: "宽度"
                            text: String(settings.value("window_size.w") || 1280)
                            onEditingFinished: {
                                var v = parseInt(text);
                                settings.setValue("window_size.w", (isNaN(v) || v < 320) ? 1280 : v);
                                text = String(settings.value("window_size.w"));
                            }
                        }
                        Text {
                            text: "×"
                            font.pixelSize: 12
                            color: theme.textSub
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        PclTextField {
                            width: (parent.width - 34) / 2
                            placeholderText: "高度"
                            text: String(settings.value("window_size.h") || 720)
                            onEditingFinished: {
                                var v = parseInt(text);
                                settings.setValue("window_size.h", (isNaN(v) || v < 240) ? 720 : v);
                                text = String(settings.value("window_size.h"));
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: Ui.valueAt(Ui.WINDOW_SIZE, windowSizeCombo.currentIndex) === "custom"
                    text: "游戏内也可以在「选项 → 显示设置」里随时改分辨率。"
                    font.pixelSize: 11
                    color: theme.textHint
                }
            }

            Card {
                title: "内存分配"
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 10

                    Column {
                        width: 150
                        spacing: 6

                        PclRadioButton {
                            text: "自动配置"
                            checked: settings.value("launch.memory_mode") !== "custom"
                            onClicked: {
                                settings.setValue("launch.memory_mode", "auto");
                                memorySlider.syncFromSettings();
                            }
                        }
                        PclRadioButton {
                            id: customRadio
                            text: "自定义"
                            checked: settings.value("launch.memory_mode") === "custom"
                            onClicked: {
                                settings.setValue("launch.memory_mode", "custom");
                                if (!settings.value("launch.memory_mb"))
                                    settings.setValue("launch.memory_mb",
                                                      Math.max(1024, settings.autoMemoryMb));
                                memorySlider.syncFromSettings();
                            }
                        }
                    }

                    Column {
                        width: parent.width - 160
                        spacing: 4

                        PclSlider {
                            id: memorySlider
                            width: parent.width
                            enabled: customRadio.checked
                            from: 512
                            to: Math.max(1024, settings.totalMemoryMb)
                            stepSize: 256

                            // 用绑定读值(切模式/外部改动都会跟着变), 只在用户拖动时
                            // 用 onMoved 写回 —— 程序化赋值不会反过来污染配置。
                            value: customRadio.checked ? settings.customMemoryMb
                                                       : settings.autoMemoryMb
                            onMoved: settings.setCustomMemoryMb(Math.round(value))
                        }
                        Text {
                            text: "分配内存: " + Ui.gb(customRadio.checked ? memorySlider.value
                                                                          : settings.autoMemoryMb)
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }

                PclCheckBox {
                    text: "启动游戏前进行内存优化"
                    checked: settings.flag("launch.optimize_memory")
                    onClicked: settings.setValue("launch.optimize_memory", checked)
                }

                MemoryBar {
                    width: parent.width
                    totalMb: settings.totalMemoryMb
                    usedMb: settings.usedMemoryMb
                    allocMb: customRadio.checked ? memorySlider.value : settings.autoMemoryMb
                    usedText: "已使用内存"
                }
            }

            Accordion {
                width: parent.width
                title: "离线皮肤"
                expanded: false

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "皮肤模型"
                    PclComboBox {
                        width: parent.width
                        model: Ui.SKIN_MODEL
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.SKIN_MODEL, settings.value("skin.model") || "steve")
                        onActivated: settings.setValue("skin.model", Ui.valueAt(Ui.SKIN_MODEL, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "皮肤文件"
                    Row {
                        width: parent.width
                        spacing: 8
                        PclButton {
                            text: "选择文件"
                            implicitWidth: 96
                            onClicked: if (page.host) page.host.askSkinFile()
                        }
                        Text {
                            width: parent.width - 110
                            anchors.verticalCenter: parent.verticalCenter
                            text: settings.value("skin.path") !== "" ? settings.value("skin.path")
                                                                     : "未选择（使用默认皮肤）"
                            font.pixelSize: 11
                            color: theme.textSub
                            elide: Text.ElideMiddle
                        }
                    }
                }

                Item {
                    width: parent.width - 20
                    x: 10
                    height: 68
                    Image {
                        anchors.left: parent.left
                        anchors.leftMargin: 110
                        width: 56
                        height: 56
                        source: "image://avatar/" + backend.accountName + "?size=56&model="
                                + (settings.value("skin.model") || "steve")
                        sourceSize.width: 56
                        sourceSize.height: 56
                        smooth: false
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
                    label: "Java 路径"
                    Row {
                        width: parent.width
                        spacing: 8
                        PclComboBox {
                            id: javaCombo
                            width: parent.width - 110
                            model: settings.javaList.map(function (j) { return j.label; })
                            currentIndex: page.javaIndex()
                            onActivated: settings.setValue("launch.java_path",
                                                           settings.javaList[currentIndex].path)
                        }
                        PclButton {
                            text: "浏览…"
                            implicitWidth: 92
                            onClicked: if (page.host) page.host.askJavaFile()
                        }
                    }
                }

                Text {
                    width: parent.width - 20
                    x: 10
                    text: settings.javaHint()
                    font.pixelSize: 11
                    color: theme.textSub
                    wrapMode: Text.WrapAnywhere
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "JVM 参数"
                    PclTextField {
                        width: parent.width
                        placeholderText: "例如 -XX:+UseG1GC"
                        text: settings.value("launch.jvm_args")
                        onEditingFinished: settings.setValue("launch.jvm_args", text)
                    }
                }

                SettingRow {
                    width: parent.width - 20
                    x: 10
                    label: "游戏参数"
                    PclTextField {
                        width: parent.width
                        placeholderText: "例如 --fullscreen"
                        text: settings.value("launch.game_args")
                        onEditingFinished: settings.setValue("launch.game_args", text)
                    }
                }
            }

            Item {
                width: parent.width
                height: 48

                PclButton {
                    anchors.centerIn: parent
                    kind: "primary"
                    text: "版本独立设置"
                    iconName: "cube_grass"
                    implicitWidth: 168
                    implicitHeight: 34
                    onClicked: if (page.host) page.host.openVersionSettings()
                }
            }
        }
    }
}
