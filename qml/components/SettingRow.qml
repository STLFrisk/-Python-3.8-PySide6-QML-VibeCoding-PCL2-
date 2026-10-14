import QtQuick

// 「设置项」一行: 左侧标题 + 右侧控件
Item {
    id: row

    property string label: ""
    property int labelWidth: 104
    property int gap: 14
    property int verticalPadding: 4
    default property alias content: holder.data

    implicitHeight: Math.max(30, holder.implicitHeight + verticalPadding * 2)
    implicitWidth: 200

    Text {
        id: labelText
        text: row.label
        width: row.label.length > 0 ? row.labelWidth : 0
        visible: row.label.length > 0
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        font.pixelSize: 12
        color: theme.text
        elide: Text.ElideRight
    }

    Item {
        id: holder
        anchors.left: labelText.visible ? labelText.right : parent.left
        anchors.leftMargin: labelText.visible ? row.gap : 0
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        implicitHeight: childrenRect.height
        height: implicitHeight
    }
}
