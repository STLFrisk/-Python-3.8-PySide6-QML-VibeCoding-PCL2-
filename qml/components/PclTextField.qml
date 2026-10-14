import QtQuick
import FluentUI

// 兼容层: 输入框换成 FluentUI 的 FluTextBox。
// 页面用到的 text / placeholderText / readOnly / onAccepted / onTextChanged 都由基类提供。
FluTextBox {
    id: control

    property int fontSize: 13

    implicitHeight: 32
    font.pixelSize: fontSize
}
