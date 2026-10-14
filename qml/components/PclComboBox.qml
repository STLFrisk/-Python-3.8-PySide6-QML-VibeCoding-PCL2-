import QtQuick
import FluentUI

// 兼容层: 下拉框换成 FluentUI 的 FluComboBox。
// 保留原有扩展属性(textRoleName/placeholder/fontSize), 其余沿用 ComboBox 接口。
FluComboBox {
    id: control

    property string textRoleName: ""
    property string placeholder: ""
    property int fontSize: 13

    implicitHeight: 32
    implicitWidth: 180
    font.pixelSize: fontSize
    textRole: textRoleName
}
