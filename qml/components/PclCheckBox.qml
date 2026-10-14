import QtQuick
import FluentUI

// 兼容层: 复选框换成 FluentUI 实现(checked/text/enabled/spacing 等接口不变)
FluCheckBox {
    id: control

    property int fontSize: 12

    implicitHeight: 26
}
