import QtQuick

// Mod 列表行: 勾选框 + 图标 + 名称 + 状态
Item {
    id: row

    property string modName: ""
    property string subtitle: ""
    property bool enabled: true
    property bool selected: false

    signal toggleEnabled()
    signal toggleSelected()

    implicitHeight: 44
    implicitWidth: 200

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: mouse.containsMouse ? theme.hover : "transparent"
    }

    PclCheckBox {
        id: check
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        checked: row.selected
        onClicked: row.toggleSelected()
    }

    Image {
        id: icon
        x: 34
        anchors.verticalCenter: parent.verticalCenter
        width: 26
        height: 26
        opacity: row.enabled ? 1.0 : 0.45
        source: "image://icon/cube_sand?size=26"
        sourceSize.width: 26
        sourceSize.height: 26
        smooth: true
    }

    Column {
        anchors.left: icon.right
        anchors.leftMargin: 10
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        opacity: row.enabled ? 1.0 : 0.5

        Text {
            width: parent.width
            text: row.modName + (row.enabled ? "" : "  (已禁用)")
            font.pixelSize: 13
            color: theme.textTitle
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: row.subtitle
            font.pixelSize: 11
            color: theme.textSub
            elide: Text.ElideMiddle
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        anchors.leftMargin: 30
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: row.toggleEnabled()
    }
}
