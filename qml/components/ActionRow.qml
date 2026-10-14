import QtQuick

// 左对齐的「动作行」(图标 + 文字), 用于 添加/导入 等操作
Item {
    id: row

    property string iconName: "folder"
    property string text: ""
    property int iconSize: 18
    property int fontSize: 12

    signal clicked()

    implicitHeight: 32
    implicitWidth: 160

    Rectangle {
        anchors.fill: parent
        radius: 3
        color: mouse.containsMouse ? theme.hover : "transparent"
    }

    Image {
        x: 12
        width: row.iconSize
        height: row.iconSize
        anchors.verticalCenter: parent.verticalCenter
        source: "image://icon/" + row.iconName + "?color=" + encodeURIComponent(theme.text)
                + "&size=" + row.iconSize
        sourceSize.width: row.iconSize
        sourceSize.height: row.iconSize
    }

    Text {
        x: 12 + row.iconSize + 8
        anchors.verticalCenter: parent.verticalCenter
        text: row.text
        font.pixelSize: row.fontSize
        color: theme.text
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: row.clicked()
    }
}
