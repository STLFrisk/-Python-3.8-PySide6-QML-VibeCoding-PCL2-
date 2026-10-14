import QtQuick
import QtQuick.Window

// 无边框窗口的自绘标题栏
Rectangle {
    id: bar

    property string title: "PCL"
    property bool showNav: true
    property bool showBack: false
    property int navIndex: 0
    property real animationScale: 1
    property var navLabels: ["启动", "下载", "设置"]
    property var navIcons: ["play", "download", "gear"]
    property Window targetWindow: null
    property bool maximized: targetWindow ? (targetWindow.visibility === Window.Maximized) : false

    signal navClicked(int index)
    signal backClicked()
    signal minimizeClicked()
    signal maximizeClicked()
    signal closeClicked()

    height: theme.titleBarHeight
    color: "transparent"
    clip: true

    // 顶部圆角背景(与窗口圆角一致)
    RoundedPanel {
        anchors.fill: parent
        radius: theme.cornerRadius
        roundTop: true
        roundBottom: false
        color: theme.titleTop
        gradient: Gradient {
            GradientStop { position: 0.0; color: theme.titleTop }
            GradientStop { position: 1.0; color: theme.titleBottom }
        }
    }

    // 拖动 / 双击最大化
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: if (bar.targetWindow) bar.targetWindow.startSystemMove()
        onDoubleClicked: bar.maximizeClicked()
    }

    // 左侧: Logo + 标题 或 返回箭头 + 标题
    Item {
        id: leftArea
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.max(140, leftRow.implicitWidth + 12)

        Row {
            id: leftRow
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            Item {
                width: 22
                height: 22
                anchors.verticalCenter: parent.verticalCenter
                visible: bar.showBack

                Image {
                    anchors.centerIn: parent
                    width: 16
                    height: 16
                    source: "image://icon/back?color=%23FFFFFF&size=16"
                    sourceSize.width: 16
                    sourceSize.height: 16
                }
                Rectangle {
                    anchors.fill: parent
                    radius: 3
                    color: backMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.22) : "transparent"
                }
                MouseArea {
                    id: backMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bar.backClicked()
                }
            }

            Image {
                width: 18
                height: 18
                anchors.verticalCenter: parent.verticalCenter
                visible: !bar.showBack
                source: "image://icon/pcl?color=%23FFFFFF&size=18"
                sourceSize.width: 18
                sourceSize.height: 18
            }

            Text {
                text: bar.title
                color: "white"
                font.pixelSize: 13
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    // 中间: 导航按钮(进入二级页面时收缩并淡出, 返回时再展开)
    Item {
        id: navArea
        anchors.centerIn: parent
        height: parent.height
        width: bar.showNav ? navRow.implicitWidth : 0
        opacity: bar.showNav ? 1 : 0
        clip: true

        Behavior on width {
            NumberAnimation {
                duration: Math.round(220 * bar.animationScale)
                easing.type: Easing.OutCubic
            }
        }
        Behavior on opacity {
            NumberAnimation { duration: Math.round(150 * bar.animationScale) }
        }

        Row {
            id: navRow
            anchors.centerIn: parent
            spacing: 4

            Repeater {
                model: bar.navLabels.length

                PclButton {
                    required property int index
                    kind: "nav"
                    text: bar.navLabels[index]
                    iconName: bar.navIcons[index]
                    iconSize: 15
                    fontSize: 13
                    implicitHeight: 30
                    checkable: false
                    onClicked: bar.navClicked(index)
                    background: Rectangle {
                        radius: 4
                        color: bar.navIndex === index ? Qt.rgba(1, 1, 1, 0.28)
                             : (parent.hovered ? Qt.rgba(1, 1, 1, 0.18) : "transparent")
                    }
                }
            }
        }
    }

    // 右侧: 窗口按钮
    Row {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom

        Repeater {
            model: [
                { icon: bar.maximized ? "restore" : "maximize", tip: bar.maximized ? "还原" : "最大化" },
                { icon: "minimize", tip: "最小化" },
                { icon: "close", tip: "关闭" }
            ]

            Item {
                required property var modelData
                required property int index
                width: 44
                height: bar.height

                Rectangle {
                    anchors.fill: parent
                    color: mouse.containsMouse
                           ? (index === 2 ? "#E81123" : Qt.rgba(1, 1, 1, 0.22))
                           : "transparent"
                }
                Image {
                    anchors.centerIn: parent
                    width: 16
                    height: 16
                    source: "image://icon/" + modelData.icon + "?color=%23FFFFFF&size=16"
                    sourceSize.width: 16
                    sourceSize.height: 16
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (index === 0)
                            bar.maximizeClicked();
                        else if (index === 1)
                            bar.minimizeClicked();
                        else
                            bar.closeClicked();
                    }
                }
            }
        }
    }
}
