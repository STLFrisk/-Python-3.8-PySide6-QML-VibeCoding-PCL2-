import QtQuick
import QtQuick.Controls.Basic
import "../../components"

// 版本设置 - Mod 管理
Item {
    id: page

    property var host: null

    Column {
        anchors.fill: parent
        spacing: 0

        Item {
            width: parent.width
            height: 54

            Row {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Rectangle {
                    width: 260
                    height: 30
                    radius: 3
                    color: "white"
                    border.width: 1
                    border.color: searchField.activeFocus ? theme.primary : theme.borderInput

                    Image {
                        id: searchIcon
                        x: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: 14
                        height: 14
                        source: "image://icon/search?color=" + encodeURIComponent(theme.textSub) + "&size=14"
                        sourceSize.width: 14
                        sourceSize.height: 14
                    }

                    TextInput {
                        id: searchField
                        anchors.left: searchIcon.right
                        anchors.leftMargin: 6
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        font.pixelSize: 12
                        color: theme.text
                        clip: true
                        selectByMouse: true
                        selectionColor: theme.primaryLight
                        onTextChanged: backend.filterMods(text)

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: searchField.text === ""
                            text: "搜索 Mod 名称 / 描述 / 标签"
                            font.pixelSize: 12
                            color: theme.textHint
                        }
                    }
                }
            }
        }

        Item {
            width: parent.width
            height: 46

            Row {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                PclButton {
                    text: "打开文件夹"
                    implicitWidth: 104
                    implicitHeight: 30
                    onClicked: backend.openModsFolder()
                }
                PclButton {
                    text: "从文件安装"
                    implicitWidth: 104
                    implicitHeight: 30
                    onClicked: if (page.host) page.host.askInstallMod()
                }
                PclButton {
                    text: "下载 Mod"
                    implicitWidth: 104
                    implicitHeight: 30
                    onClicked: backend.downloadModHint()
                }
                PclButton {
                    text: "全选"
                    implicitWidth: 76
                    implicitHeight: 30
                    onClicked: backend.selectAllMods(true)
                }
                PclButton {
                    text: "取消全选"
                    implicitWidth: 88
                    implicitHeight: 30
                    onClicked: backend.selectAllMods(false)
                }
            }
        }

        Item {
            width: parent.width
            height: 44

            Row {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                Rectangle {
                    height: 24
                    width: countText.implicitWidth + 20
                    radius: 12
                    color: theme.primary
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        id: countText
                        anchors.centerIn: parent
                        text: "全部 (" + backend.modModel.count + ")"
                        color: "white"
                        font.pixelSize: 11
                    }
                }

                PclButton {
                    text: "启用所选"
                    implicitWidth: 88
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: backend.batchMods("enable")
                }
                PclButton {
                    text: "禁用所选"
                    implicitWidth: 88
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: backend.batchMods("disable")
                }
                PclButton {
                    kind: "danger"
                    text: "删除所选"
                    implicitWidth: 88
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: backend.batchMods("delete")
                }
            }
        }

        ScrollView {
            id: scroll
            width: parent.width
            height: parent.height - 144
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            Item {
                width: scroll.availableWidth
                height: Math.max(modList.height + 20, scroll.height)

                Column {
                    id: modList
                    x: 16
                    y: 6
                    width: parent.width - 32
                    spacing: 2

                    Repeater {
                        model: backend.modModel

                        ModRow {
                            width: parent.width
                            modName: model.name
                            subtitle: model.subtitle
                            enabled: model.enabled
                            selected: model.selected
                            onToggleEnabled: backend.toggleMod(index)
                            onToggleSelected: backend.setModSelected(index, !model.selected)
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: backend.modModel.count === 0
                    text: "还没有安装任何 Mod\n点击「从文件安装」选择本地的 .jar 文件，或把文件放进 Mod 文件夹"
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: 12
                    lineHeight: 1.4
                    color: theme.textHint
                }
            }
        }
    }
}
