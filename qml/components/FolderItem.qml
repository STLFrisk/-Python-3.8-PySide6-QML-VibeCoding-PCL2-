import QtQuick

// 文件夹列表项: 名称 + 路径
Item {
    id: item

    property string folderName: ""
    property string folderPath: ""
    property bool active: false

    signal clicked()

    implicitHeight: 42
    implicitWidth: 180

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: item.active ? theme.selected : (mouse.containsMouse ? theme.hover : "transparent")
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        Text {
            text: item.folderName
            width: parent.width
            font.pixelSize: 12
            font.bold: item.active
            color: item.active ? theme.primary : theme.textTitle
            elide: Text.ElideRight
        }
        Text {
            text: item.folderPath
            width: parent.width
            font.pixelSize: 10
            color: theme.textSub
            elide: Text.ElideMiddle
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: item.clicked()
    }
}
