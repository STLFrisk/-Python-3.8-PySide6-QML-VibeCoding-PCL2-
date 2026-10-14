import QtQuick
import QtQuick.Controls.Basic

// PCL 风格单选框
RadioButton {
    id: control

    property int fontSize: 12

    implicitHeight: 22
    spacing: 6
    font.pixelSize: fontSize
    hoverEnabled: true

    indicator: Rectangle {
        implicitWidth: 14
        implicitHeight: 14
        x: 0
        y: (control.height - height) / 2
        radius: 7
        color: "white"
        border.width: control.checked ? 4 : 1
        border.color: control.checked ? theme.primary
                    : (control.hovered ? theme.primary : theme.borderInput)
    }

    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        font.pixelSize: control.fontSize
        color: control.enabled ? theme.text : theme.textHint
        verticalAlignment: Text.AlignVCenter
    }
}
