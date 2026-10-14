import QtQuick
import QtQuick.Window

// 窗口圆角 + 描边外框: 内容放在里面, clip 保证子项不会溢出圆角
Rectangle {
    id: frame

    property Window targetWindow: null
    property int cornerRadius: 10
    readonly property bool maximized: targetWindow
                                        ? targetWindow.visibility === Window.Maximized
                                        : false

    anchors.fill: parent
    anchors.margins: maximized ? 0 : 1
    radius: maximized ? 0 : cornerRadius
    color: theme.bg
    border.width: 1
    border.color: theme.border
    clip: true

    Behavior on radius {
        NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
    }
}
