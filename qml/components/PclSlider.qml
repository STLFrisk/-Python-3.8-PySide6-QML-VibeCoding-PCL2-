import QtQuick
import FluentUI

// 兼容层: 滑块换成 FluentUI 的 FluSlider(from/to/value/onMoved 等接口不变)
FluSlider {
    id: control

    implicitHeight: 28
}
