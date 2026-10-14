import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 主界面 - 启动页
Item {
    id: page

    property var host: null
    property bool offlineMode: true

    Row {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------- 左列: 账号与启动
        Item {
            id: leftCol
            width: 300
            height: parent.height

            // 正版 / 离线: 整体居中放在账号栏上方; 未选中时只有文字(底色透明)
            Row {
                id: modeRow
                anchors.horizontalCenter: parent.horizontalCenter
                y: 30
                spacing: 4

                PclButton {
                    kind: "toggle"
                    checkable: true
                    checked: !page.offlineMode
                    text: "正版"
                    iconName: "shield_check"
                    iconSize: 15
                    fontSize: 13
                    implicitWidth: 98
                    implicitHeight: 30
                    onClicked: {
                        page.offlineMode = false;
                        backend.loginMicrosoft();
                        page.offlineMode = true;
                    }
                }

                PclButton {
                    kind: "toggle"
                    checkable: true
                    checked: page.offlineMode
                    text: "离线"
                    iconName: "offline"
                    iconSize: 15
                    fontSize: 13
                    implicitWidth: 98
                    implicitHeight: 30
                    onClicked: page.offlineMode = true
                }
            }

            Image {
                id: avatar
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: accountCombo.top
                anchors.bottomMargin: 14
                width: 64
                height: 64
                source: backend.accountAvatar
                sourceSize.width: 64
                sourceSize.height: 64
                smooth: false
            }

            PclComboBox {
                id: accountCombo
                anchors.horizontalCenter: parent.horizontalCenter
                // 账号区(头像 + 下拉框 + 两个链接)整体在左栏**居中**:
                // 先把下拉框放到中心, 再补偿两个偏移 ——
                //   +12 : 让"头像+下拉框+链接"这个整体的中心落在下拉框中心(头像在上面)
                //   -标题栏高度/2 : 左栏在标题栏**下面**, 它的中心比窗口中心低半个标题栏,
                //                  所以往上挪回来, 视觉上才是整窗居中。
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: 12 - theme.titleBarHeight / 2
                width: 264
                implicitHeight: 30
                model: backend.accounts.map(function (a) { return a.display; })
                currentIndex: backend.accountIndex
                onActivated: backend.setAccountIndex(currentIndex)
            }

            Row {
                id: linksRow
                anchors.horizontalCenter: parent.horizontalCenter
                // 挂在账号下拉框下面(整块账号区因此可整体居中), 不再从底部按钮往上钉。
                anchors.top: accountCombo.bottom
                anchors.topMargin: 4
                spacing: 2

                PclButton {
                    kind: "link"
                    text: "添加离线账号"
                    fontSize: 11
                    implicitHeight: 20
                    onClicked: addAccountDialog.open()
                }
                PclButton {
                    kind: "link"
                    text: "移除当前账号"
                    fontSize: 11
                    implicitHeight: 20
                    onClicked: {
                        if (backend.accounts.length > 1)
                            backend.removeAccount(backend.accountIndex);
                    }
                }
            }

            PclButton {
                id: launchButton
                x: 18
                anchors.bottom: buttonsRow.top
                anchors.bottomMargin: 10
                width: 264
                implicitHeight: 54
                onClicked: backend.launchGame()

                background: Rectangle {
                    radius: 5
                    color: launchButton.pressed ? "#D7E7FB"
                         : (launchButton.hovered ? theme.primarySoft : "white")
                    border.width: 1
                    border.color: theme.primary
                }

                // ⚠️ 不能用 contentItem: Qt Quick Controls 会**自己**给 contentItem 设位置/大小,
                // 在里面写 anchors 是无效的(所以文字看着是靠上而不是居中)。
                // 改成按钮的普通子项 —— 子项不受控件管理, anchors 生效, 上下左右都居中。
                Column {
                    anchors.centerIn: parent
                    spacing: 3

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: backend.launchState === "running" ? "游戏运行中" : "启动游戏"
                        color: theme.primary
                        font.pixelSize: 15
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: backend.selectedVersionId !== "" ? backend.selectedVersionId : "未选择版本"
                        color: theme.textSub
                        font.pixelSize: 11
                        width: launchButton.width - 24
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                }
            }

            Row {
                id: buttonsRow
                x: 18
                // 吸附左下角(PCL2 也是这样): 窗口变高时整块跟着下移, 而不是钉在原处
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                width: 264
                spacing: 8

                PclButton {
                    width: (264 - 8) / 2
                    implicitHeight: 30
                    text: "版本选择"
                    onClicked: if (page.host) page.host.openVersionSelect()
                }
                PclButton {
                    width: (264 - 8) / 2
                    implicitHeight: 30
                    text: "版本设置"
                    onClicked: if (page.host) page.host.openVersionSettings()
                }
            }
        }

        // ---------------------------------------------------- 右侧: 背景画布
        RoundedPanel {
            id: canvas
            width: parent.width - leftCol.width
            height: parent.height
            roundTop: false
            roundBottom: true
            radius: theme.cornerRadius
            color: "#F6FAFF"
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#F6FAFF" }
                GradientStop { position: 1.0; color: "#E3EDFA" }
            }

            Rectangle {
                width: 1
                height: parent.height
                color: theme.border
            }

            Rectangle {
                width: parent.width * 0.55
                height: parent.height * 0.55
                x: parent.width * 0.16
                y: parent.height * 0.14
                radius: width / 2
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#FFFFFF" }
                    GradientStop { position: 1.0; color: "#F2F7FE" }
                }
                opacity: 0.28
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                spacing: 4

                PclButton {
                    kind: "link"
                    text: "查看启动日志"
                    iconName: "clock"
                    iconSize: 13
                    fontSize: 11
                    implicitHeight: 20
                    onClicked: if (page.host) page.host.openLog()
                }
                Text {
                    text: backend.statusText
                    font.pixelSize: 11
                    color: theme.textSub
                }
                Text {
                    visible: backend.demoMode
                    text: "示例数据模式: 未检测到本地版本, 显示的版本来自内置示例目录"
                    font.pixelSize: 11
                    color: "#C79A3A"
                }
            }
        }
    }

    // 添加离线账号对话框
    PclDialog {
        id: addAccountDialog
        title: "添加离线账号"
        text: "离线模式使用本地生成的 UUID 启动游戏，无需正版账号。请输入玩家名："
        showCancel: true
        okText: "添加"
        inputVisible: true
        inputPlaceholder: "玩家名"
        onAccepted: backend.addOfflineAccount(inputText)
    }
}
