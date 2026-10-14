import QtQuick
import FluentUI

// 兼容层: 对外接口(kind/iconName/text/implicitWidth...)保持不变, 内部换成 FluentUI 按钮,
// 这样所有页面不用改动就能整体切换成 Fluent 外观。
// kind: primary | ghost | nav | plain | danger | link | toggle
FluButton {
    id: control

    property string kind: "ghost"
    property string iconName: ""
    property int iconSize: 16
    property int fontSize: 13
    property int buttonRadius: 3
    property color textColorOverride: "transparent"
    property bool hasTextColorOverride: false

    readonly property bool isPrimary: kind === "primary"
    readonly property bool isDanger: kind === "danger"
    readonly property bool isToggle: kind === "toggle"
    readonly property bool isFlat: kind === "nav" || kind === "link" || kind === "plain"
                                   || isToggle

    // 取色规则与原版保持一致(深色文字用在浅色按钮上, 标题栏/主按钮用白字)
    readonly property color _fg: {
        if (!control.enabled)
            return theme.textHint;
        if (control.hasTextColorOverride)
            return control.textColorOverride;
        if (control.isToggle)
            return control.checked ? "white" : theme.primary;
        if (control.isPrimary)
            return "white";
        if (control.isDanger)
            return theme.danger;
        if (control.kind === "nav")
            return "white";
        if (control.kind === "link")
            return theme.textSub;
        return theme.textTitle;
    }

    readonly property color _iconColor: {
        if (control.isToggle)
            return control.checked ? "white" : theme.primary;
        if (control.kind === "nav" || control.isPrimary)
            return "white";
        if (control.isDanger)
            return theme.danger;
        return theme.primary;
    }

    implicitHeight: 28
    implicitWidth: Math.max(64, contentRow.implicitWidth + 26)

    // 主按钮/选中的分段按钮: 实心主题色; 扁平按钮: 透明
    normalColor: (isPrimary || (isToggle && control.checked)) ? theme.primary
                 : (isFlat ? "transparent" : theme.card)
    hoverColor: (isPrimary || (isToggle && control.checked)) ? Qt.lighter(theme.primary, 1.12)
                : theme.hover
    textColor: _fg

    // 注意: Qt Quick Controls 会把 contentItem 拉伸到整个内容区, 必须再套一层 Item,
    // 里面的 Row 用 centerIn 才能真正居中(直接把 Row 当 contentItem 会让内容贴左边)。
    contentItem: Item {
        implicitWidth: contentRow.implicitWidth
        implicitHeight: contentRow.implicitHeight

        Row {
            id: contentRow
            anchors.centerIn: parent
            spacing: 6

            Image {
                visible: control.iconName !== ""
                width: control.iconSize
                height: control.iconSize
                anchors.verticalCenter: parent.verticalCenter
                source: "image://icon/" + control.iconName + "?color="
                        + encodeURIComponent(String(control._iconColor)) + "&size="
                        + control.iconSize
                sourceSize.width: control.iconSize
                sourceSize.height: control.iconSize
            }
            Text {
                visible: control.text !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: control.text
                font.pixelSize: control.fontSize
                color: control._fg
            }
        }
    }
}
