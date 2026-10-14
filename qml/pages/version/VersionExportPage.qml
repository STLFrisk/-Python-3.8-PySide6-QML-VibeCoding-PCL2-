import QtQuick
import QtQuick.Controls.Basic
import "../../components"

// 版本设置 - 导出(整合包)
Item {
    id: page

    property var host: null
    property bool optMods: true
    property bool optModConfigs: true
    property bool optResourcepacks: true
    property bool optScreenshots: false
    property bool optSaves: false
    property bool optServers: false
    property bool optLauncherConfig: true
    property bool optGameSettings: true

    // versionSettings 是运行时注入的 context property(版本设置后端)。关窗销毁阶段
    // QML 仍会对存活的绑定再求值一次, 那时它已经是 null, 直接读 .versionId /
    // .subtitle / .title 会抛 "Cannot read property 'xxx' of null"。这里做空安全,
    // 取不到时回落到"没有选择版本"时的原有文案(空串 / "整合包"), 正常运行
    // (versionSettings 有效)时取值路径与原来完全一致。
    function vsProperty(name, fallback) {
        if (typeof versionSettings === "undefined" || versionSettings === null)
            return fallback;
        var value = versionSettings[name];
        return value === undefined ? fallback : value;
    }

    function options() {
        return {
            "pack_name": nameField.text,
            "pack_version": versionField.text,
            "mods": page.optMods,
            "mod_configs": page.optModConfigs,
            "resourcepacks": page.optResourcepacks,
            "screenshots": page.optScreenshots,
            "saves": page.optSaves,
            "servers": page.optServers,
            "launcher_config": page.optLauncherConfig,
            "game_settings": page.optGameSettings
        };
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
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 10

                    Text {
                        text: "整合包名称"
                        font.pixelSize: 12
                        color: theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    PclTextField {
                        id: nameField
                        width: 260
                        text: page.vsProperty("versionId", "") !== "" ? page.vsProperty("versionId", "") : "整合包"
                    }
                    Text {
                        text: "整合包版本"
                        font.pixelSize: 12
                        color: theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    PclTextField {
                        id: versionField
                        width: 120
                        text: "1.0.0"
                    }
                }
            }

            Card {
                title: "导出内容列表"
                width: parent.width

                Column {
                    width: parent.width
                    spacing: 2

                    Row {
                        spacing: 8
                        PclCheckBox {
                            text: "游戏本体"
                            checked: true
                            enabled: false
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.vsProperty("subtitle", "") + "   （不包含在整合包内，由启动器重新下载）"
                            font.pixelSize: 11
                            color: theme.textHint
                        }
                    }

                    PclCheckBox {
                        x: 24
                        text: "游戏本体设置   键位、音量、视频设置等"
                        checked: page.optGameSettings
                        onClicked: page.optGameSettings = checked
                    }

                    PclCheckBox {
                        text: "Mod   模组"
                        checked: page.optMods
                        onClicked: page.optMods = checked
                    }

                    PclCheckBox {
                        x: 24
                        text: "Mod 设置"
                        checked: page.optModConfigs
                        onClicked: page.optModConfigs = checked
                    }

                    PclCheckBox {
                        text: "资源包   纹理包/材质包"
                        checked: page.optResourcepacks
                        onClicked: page.optResourcepacks = checked
                    }

                    PclCheckBox {
                        text: "截图"
                        checked: page.optScreenshots
                        onClicked: page.optScreenshots = checked
                    }

                    PclCheckBox {
                        text: "单人游戏存档   世界/地图"
                        checked: page.optSaves
                        onClicked: page.optSaves = checked
                    }

                    PclCheckBox {
                        text: "多人游戏服务器列表"
                        checked: page.optServers
                        onClicked: page.optServers = checked
                    }

                    PclCheckBox {
                        text: "启动器设置   一并导出本启动器的配置"
                        checked: page.optLauncherConfig
                        onClicked: page.optLauncherConfig = checked
                    }
                }
            }

            Accordion {
                width: parent.width
                title: "高级选项"
                expanded: false

                Text {
                    width: parent.width - 20
                    x: 10
                    text: "导出的压缩包内含 pclpy_pack.json 清单文件，记录了整合包名称、版本与包含的内容分类。\n"
                          + "整合包可通过「版本选择 → 导入整合包」重新导入。\n"
                          + "当前版本: " + page.vsProperty("title", "")
                          + (page.vsProperty("isDemo", false) ? "（示例数据，无法导出）" : "")
                    font.pixelSize: 11
                    color: theme.textSub
                    lineHeight: 1.4
                    wrapMode: Text.WordWrap
                }
            }

            Item {
                width: parent.width
                height: 48

                PclButton {
                    anchors.centerIn: parent
                    kind: "primary"
                    text: "开始导出"
                    iconName: "package"
                    implicitWidth: 160
                    implicitHeight: 34
                    onClicked: {
                        if (page.host)
                            page.host.askExportPack(page.options());
                    }
                }
            }
        }
    }
}
