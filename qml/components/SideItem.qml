import QtQuick
import QtQuick.Controls.Basic

// 左侧导航项(选中/悬停都有动画)
//
// 指标对齐 FluentUI 套件的 FluNavigationView(数值出处见
// vendor/FluentUI/qml/FluentUI/Controls/FluNavigationView.qml):
//   * 条目高度 cellHeight = 38       (FluNavigationView.qml:22)
//   * 条目背景内缩 left/right 6, top/bottom 2 (FluNavigationView.qml:485-488)
//   * 条目背景圆角 radius = 4        (FluNavigationView.qml:539)
//   * 图标容器 30x30, 距背景左侧 3   (FluNavigationView.qml:579-590)
//   * 图标字形 FluIcon.iconSize = 15 (FluNavigationView.qml:574)
//   * 选中指示条 3x18 圆角 1.5       (FluNavigationView.qml:267-271 / 1017-1019)
//   * 文字字号 FluTextStyle.Body = 13px(实测 FluTextStyle.Body.pixelSize == 13, 与本文件默认值一致)
//   * 选中/悬停填充用主题主色派生的 theme.selected / theme.hover,
//     与 Main.qml:212(FluTheme.primaryColor = theme.primary)同源, 不硬编码色值。
Button {
    id: item

    property string iconName: ""
    property int fontSize: 13
    property string iconColorOn: theme.primary
    property string iconColorOff: theme.text
    property real animationScale: 1

    // ---- FluentUI 指标(只做数值对齐: 不换控件、不改宽度/层级/交互) ----
    readonly property int navItemHeight: 38   // FluNavigationView.cellHeight
    readonly property int navInsetH: 6        // 条目背景左右内缩
    readonly property int navInsetV: 2        // 条目背景上下内缩
    readonly property int navRadius: 4        // 条目背景圆角
    readonly property int navIconBox: 30      // 图标容器边长
    readonly property int navIconSize: 15     // 图标字形边长
    readonly property int navIconLeft: 3      // 图标容器距背景左侧

    implicitHeight: item.navItemHeight
    implicitWidth: 140
    // 不能设 checkable: 那样"再点一次已选中的项"会把选中取消, 看起来像选中效果回退。
    // 选中状态由外部绑定 checked 决定(视觉也只看 checked)。
    checkable: false
    hoverEnabled: true

    // 选中/悬停填充: 两层都是主题主色的低透明度派生色
    // (选中 = theme.selected, 悬停 = 更轻的 theme.hover)。
    Rectangle {
        id: highlight
        anchors.fill: parent
        anchors.leftMargin: item.navInsetH
        anchors.rightMargin: item.navInsetH
        anchors.topMargin: item.navInsetV
        anchors.bottomMargin: item.navInsetV
        radius: item.navRadius
        color: item.checked ? theme.selected : theme.hover
        opacity: item.checked || item.hovered ? 1 : 0
        Behavior on opacity {
            NumberAnimation {
                duration: Math.round(160 * item.animationScale)
                easing.type: Easing.OutCubic
            }
        }
        Behavior on color {
            ColorAnimation { duration: Math.round(150 * item.animationScale) }
        }
    }

    // 左侧竖条: 选中时从中间"长"出来(FluentUI 是 3x18 / 圆角 1.5 的短条)
    Rectangle {
        id: marker
        width: 3
        radius: 1.5
        color: theme.primary
        anchors.left: parent.left
        anchors.leftMargin: item.navInsetH
        anchors.verticalCenter: parent.verticalCenter
        height: item.checked ? 18 : 0
        opacity: item.checked ? 1 : 0
        Behavior on height {
            NumberAnimation {
                duration: Math.round(200 * item.animationScale)
                easing.type: Easing.OutBack
            }
        }
        Behavior on opacity {
            NumberAnimation { duration: Math.round(120 * item.animationScale) }
        }
    }

    // z: 1 —— Qt 建 contentItem 时的子项顺序会随实现变化, 不固定的话状态填充可能盖住
    // 图标与文字(实测: 加高条目后 contentItem 被建在填充之前, 选中项会整行空白)。
    // 固定内容层在最上面, 与对齐前的观感一致。
    contentItem: Row {
        z: 1
        anchors.left: parent.left
        // 背景左内缩 + 图标容器左内缩 = FluentUI 的图标起点
        anchors.leftMargin: item.navInsetH + item.navIconLeft
        anchors.verticalCenter: parent.verticalCenter
        // 图标容器自带留白, 文字紧贴容器右侧(间距 = (30-15)/2 = 7.5)
        spacing: 0

        Item {
            id: iconBox
            width: item.navIconBox
            height: item.navIconBox
            anchors.verticalCenter: parent.verticalCenter

            Image {
                width: item.navIconSize
                height: item.navIconSize
                anchors.centerIn: parent
                source: item.iconName !== "" ? "image://icon/" + item.iconName + "?color="
                        + encodeURIComponent(item.checked ? item.iconColorOn : item.iconColorOff)
                        + "&size=" + item.navIconSize : ""
                sourceSize.width: item.navIconSize
                sourceSize.height: item.navIconSize
                scale: item.checked ? 1.08 : 1.0
                Behavior on scale {
                    NumberAnimation {
                        duration: Math.round(180 * item.animationScale)
                        easing.type: Easing.OutBack
                    }
                }
            }
        }

        Text {
            text: item.text
            font.pixelSize: item.fontSize
            color: item.checked ? theme.primary : theme.text
            anchors.verticalCenter: parent.verticalCenter
            Behavior on color {
                ColorAnimation { duration: Math.round(150 * item.animationScale) }
            }
        }
    }

    background: Rectangle {
        color: "transparent"
    }
}
