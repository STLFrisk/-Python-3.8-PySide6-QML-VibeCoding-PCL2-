import QtQuick

// 只圆「指定角」的背景板。
//
// 背景: Qt 的 clip 是矩形裁剪, 所以父级 Rectangle 的 radius 挡不住子项
// (标题栏蓝条、侧栏会盖住圆角, 看起来就是直角)。这里的做法是把背景板画得
// 比可视区高一个 radius 并把多余部分挪到裁剪区外, 等效只保留需要的圆角,
// 不依赖任何 GPU shader(软件渲染也正常)。
Item {
    id: panel

    property color color: "transparent"
    // Gradient 是值类型, 必须用 alias 直连到内部矩形, 否则不会生效。
    // 另外: 软件渲染下 Rectangle 的 color 若完全透明会抑制 gradient 绘制,
    // 所以使用 gradient 时请同时给一个不透明 color(会被渐变覆盖)。
    property alias gradient: plate.gradient
    property int radius: 10
    property bool roundTop: true
    property bool roundBottom: true

    default property alias content: holder.data

    clip: true

    Rectangle {
        id: plate
        width: panel.width
        height: panel.height + (panel.roundTop === panel.roundBottom ? 0 : panel.radius)
        y: (!panel.roundTop && panel.roundBottom) ? -panel.radius : 0
        radius: (panel.roundTop || panel.roundBottom) ? panel.radius : 0
        color: panel.color
    }

    Item {
        id: holder
        anchors.fill: parent
    }
}
