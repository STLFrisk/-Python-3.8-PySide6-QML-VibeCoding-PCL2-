import QtQuick
import FluentUI

// 卡片容器, 可带标题。
//
// 兼容层(与 PclButton/PclTextField/Accordion 同一套路): 对外接口 title / padding /
// titleHeight / hasTitle / 默认内容别名逐字不变 —— 8 个页面里的 22 处 `Card { }`
// 一行都不用改; 内部换成 FluentUI 的 FluArea(圆角 + 1px 描边的卡片容器)。
// 颜色 / 描边 / 圆角都显式指回原来的主题值, 所以外观与旧的自绘 Rectangle 完全一致。
FluArea {
    id: card

    property string title: ""
    property int padding: 16
    property int titleHeight: 34
    readonly property bool hasTitle: title !== ""
    default property alias content: body.data

    color: theme.card
    border.color: theme.border
    border.width: 1
    radius: 6
    implicitHeight: outer.implicitHeight + 2
    implicitWidth: 200

    Column {
        id: outer
        width: parent.width
        spacing: 0

        Item {
            width: parent.width
            height: card.hasTitle ? card.titleHeight : 0
            visible: card.hasTitle
            Text {
                text: card.title
                anchors.left: parent.left
                anchors.leftMargin: card.padding
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 6
                font.pixelSize: 13
                font.bold: true
                color: theme.textTitle
            }
        }

        Column {
            id: body
            width: parent.width - card.padding * 2
            x: card.padding
            spacing: 6
            bottomPadding: card.padding
        }
    }
}
