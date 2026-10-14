import QtQuick
import QtQuick.Controls.Basic
import "../../components"
import "../../components/Ui.js" as Ui

// 版本设置 - 概览
Item {
    id: page

    property var host: null

    // versionSettings 是运行时注入的 context property(版本设置后端)。关窗销毁阶段
    // QML 仍会对存活的绑定再求值一次, 那时它已经是 null, 直接读 .icon/.title/.favorite
    // 或调 .value() 会抛 "Cannot read property 'x' of null" / "Cannot call method
    // 'value' of null"。下面做成空安全(写法对齐 Main.qml 的 syncAnimationScale 与
    // VersionExportPage 的 vsProperty), 正常运行(versionSettings 有效)时取值路径
    // 与原来完全一致; 取不到时的回落值逐个按"后端此时本来会返回什么"来定:
    // icon → "cube_grass"(后端 icon 属性自带的默认图标), title/subtitle → ""
    // (VersionExportPage 同款), isDemo → false(取不到就不显示"示例数据"标记,
    // 与 VersionExportPage 一致), sizeText → "未知"(后端 sizeText 的默认值),
    // value(key) → ""(后端 value() 在配置里没有这一项时返回 "", 所以
    // "..." || "auto" 这类原有兜底照样生效)。
    readonly property bool vsReady: (typeof versionSettings !== "undefined"
                                    && versionSettings !== null)

    function vsProperty(name, fallback) {
        if (!page.vsReady)
            return fallback;
        var value = versionSettings[name];
        return value === undefined ? fallback : value;
    }

    function vsValue(key, fallback) {
        if (!page.vsReady || typeof versionSettings.value !== "function")
            return fallback;
        return versionSettings.value(key);
    }

    // 写操作: 取不到后端时按"什么都不做"处理(关窗阶段不可能有人点按钮, 这里只为
    // 彻底消除异常, 不改变正常运行时的写入行为)。
    function vsSet(key, value) {
        if (!page.vsReady || typeof versionSettings.setValue !== "function")
            return;
        versionSettings.setValue(key, value);
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
                    spacing: 12

                    Image {
                        width: 40
                        height: 40
                        anchors.verticalCenter: parent.verticalCenter
                        source: "image://icon/" + page.vsProperty("icon", "cube_grass")
                                + "?size=40"
                        sourceSize.width: 40
                        sourceSize.height: 40
                        smooth: true
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3

                        Text {
                            text: page.vsProperty("title", "")
                            font.pixelSize: 14
                            font.bold: true
                            color: theme.textTitle
                        }
                        Text {
                            text: page.vsProperty("subtitle", "")
                                  + (page.vsProperty("isDemo", false)
                                     ? "   ·   示例数据（未安装到磁盘）"
                                     : "   ·   " + page.vsProperty("sizeText", "未知"))
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }
                }
            }

            Card {
                title: "个性化"
                width: parent.width

                SettingRow {
                    width: parent.width
                    label: "图标"
                    PclComboBox {
                        width: parent.width
                        model: Ui.VERSION_ICON
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.VERSION_ICON,
                                      page.vsValue("display.icon", "") || "auto")
                        onActivated: page.vsSet("display.icon",
                                                Ui.valueAt(Ui.VERSION_ICON, currentIndex))
                    }
                }

                SettingRow {
                    width: parent.width
                    label: "分类"
                    PclComboBox {
                        width: parent.width
                        model: Ui.VERSION_CATEGORY
                        textRoleName: "label"
                        currentIndex: Ui.indexOfValue(Ui.VERSION_CATEGORY,
                                      page.vsValue("display.category", "") || "auto")
                        onActivated: page.vsSet("display.category",
                                                Ui.valueAt(Ui.VERSION_CATEGORY, currentIndex))
                    }
                }

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        text: "修改版本名"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: renameDialog.open()
                    }
                    PclButton {
                        text: "修改版本描述"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: descDialog.open()
                    }
                    PclButton {
                        text: page.vsProperty("favorite", false) ? "移出收藏夹" : "加入收藏夹"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.toggleFavorite()
                    }
                }
            }

            Card {
                title: "快捷方式"
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        text: "版本文件夹"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.openFolder("version")
                    }
                    PclButton {
                        text: "存档文件夹"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.openFolder("saves")
                    }
                    PclButton {
                        text: "Mod 文件夹"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.openFolder("mods")
                    }
                    PclButton {
                        text: "截图文件夹"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.openFolder("screenshots")
                    }
                }
            }

            Card {
                title: "高级管理"
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        text: "导出启动脚本"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.exportScript()
                    }
                    PclButton {
                        text: "补全文件"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.completeFiles()
                    }
                    PclButton {
                        kind: "danger"
                        text: "删除版本"
                        implicitWidth: 128
                        implicitHeight: 30
                        onClicked: if (page.vsReady) versionSettings.deleteVersion()
                    }
                }
            }
        }
    }

    PclDialog {
        id: renameDialog
        title: "修改版本名"
        text: "该名称只影响启动器里的显示，不会修改磁盘上的文件夹名。"
        showCancel: true
        okText: "保存"
        inputVisible: true
        inputPlaceholder: "新的版本名"
        onAccepted: if (page.vsReady) versionSettings.rename(inputText)
    }

    PclDialog {
        id: descDialog
        title: "修改版本描述"
        text: "描述会显示在版本列表中，便于区分不同整合包。"
        showCancel: true
        okText: "保存"
        inputVisible: true
        inputPlaceholder: "版本描述"
        onAccepted: if (page.vsReady) versionSettings.setDescription(inputText)
    }
}
