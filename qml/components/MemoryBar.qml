import QtQuick

// 内存占用条: 「已使用内存 x GB / y GB」+「游戏分配 z GB」
Item {
    id: bar

    property int totalMb: 8192
    property int usedMb: 4096
    property int allocMb: 4096
    property string usedText: ""
    property string allocText: "游戏分配"

    implicitHeight: 40

    function gb(mb) {
        return (mb / 1024.0).toFixed(1) + " GB";
    }

    Text {
        id: usedLabel
        anchors.left: parent.left
        anchors.top: parent.top
        text: (bar.usedText !== "" ? bar.usedText : "已使用内存")
              + "   " + gb(bar.usedMb) + " / " + gb(bar.totalMb)
        font.pixelSize: 11
        color: theme.textSub
    }

    Text {
        anchors.right: parent.right
        anchors.top: parent.top
        text: bar.allocText + "   " + gb(bar.allocMb)
        font.pixelSize: 11
        color: theme.textSub
    }

    Rectangle {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        height: 5
        radius: 2.5
        color: "#DDE7F4"

        Rectangle {
            height: parent.height
            radius: 2.5
            color: "#9CC0EA"
            width: Math.min(parent.width, parent.width * (bar.allocMb / Math.max(1, bar.totalMb)))
        }

        Rectangle {
            height: parent.height
            radius: 2.5
            color: theme.primary
            width: Math.min(parent.width, parent.width * (bar.usedMb / Math.max(1, bar.totalMb)))
        }
    }
}
