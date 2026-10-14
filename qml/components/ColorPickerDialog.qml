import QtQuick
import QtQuick.Controls.Basic
import FluentUI

// 取色器(对话框外壳 + FluentUI 取色面)
//
// 对外接口与旧版**逐字不变**: currentColor / colorAccepted(value) / setFromRgb(r,g,b) /
// applyHex(text), 以及 Popup 自带的 open() / close() —— 页面里只用到 currentColor 和
// colorAccepted(见 pages/settings/PersonalizationSettings.qml:244)。
//
// 取色面换成 FluentUI 套件里的 ColorPicker(色板 SBPicker + 色相条 ColorSlider),
// 外面套 FluArea(圆角卡片 + 描边), 与内容区其它组件同一套设计语言。
// ColorPicker 自带的 setColor() 只写 colorValue, 不会移动"色相条游标 / 色板游标",
// 所以直接用 setColor() 会让色板停在初始位置(白)而与当前色不符 —— 这里按 FluentUI
// 自己的坐标语义把两个游标摆到位(见 syncView)。找不到内部对象时整体跳过, 只同步
// colorValue, 不影响对话框可用性。
Popup {
    id: dialog

    property color currentColor: "#2B7CDB"
    signal colorAccepted(color value)

    // 正在把色板的值写回 currentColor: 期间不再反向同步, 避免来回打架
    property bool _fromView: false

    readonly property real hue: {
        var h = currentColor.hsvHue;
        return h < 0 ? 0 : h;
    }

    function setFromRgb(r, g, b) {
        currentColor = Qt.rgba(r / 255, g / 255, b / 255, 1);
    }

    function applyHex(text) {
        var value = String(text).replace("#", "").trim();
        if (value.length === 3) {
            value = value[0] + value[0] + value[1] + value[1] + value[2] + value[2];
        }
        if (!/^[0-9a-fA-F]{6}$/.test(value))
            return false;
        setFromRgb(parseInt(value.substr(0, 2), 16),
                   parseInt(value.substr(2, 2), 16),
                   parseInt(value.substr(4, 2), 16));
        return true;
    }

    // ---------------------------------------------------------------- FluentUI 取色面同步
    // 深度遍历子对象(不依赖内部 id)。ColorSlider 有 setValue(), SBPicker 有 hueColor。
    function _walk(item, fn) {
        var kids = item.children;
        if (!kids)
            return;
        for (var i = 0; i < kids.length; i++) {
            fn(kids[i]);
            _walk(kids[i], fn);
        }
    }

    // 把 currentColor 摆到 FluentUI 色板上:
    //   * 色相条: ColorSlider.value = 色相(0..1) —— ColorPicker 内部就是 Qt.hsla(value,...),
    //     而 QML 的 color.hsvHue 返回的也是 0..1(实测 0.58997 = 212.4°), 两边同一量纲。
    //   * 色板游标: x = HSV 饱和度, y = 1 - HSV 明度(× 可移动范围, 与 SBPicker 的绑定式一致)
    //
    // 注意: QML 的 color 属性是**按引用**参与 JS 运算的(值类型), 直接 `var t = currentColor`
    // 会在中途 currentColor 被改写时跟着变(实测: 摆色相条时 currentColor 被同步成白色,
    // 于是后面的游标位置全按白色算)。所以先把要用的分量拆成数字(值拷贝)再动手。
    function syncView() {
        if (!dialog.opened)
            return;
        var src = dialog.currentColor;
        var hue = dialog.hue;                       // 数字(0..1), 值拷贝
        var sat = src.hsvSaturation;
        var val = src.hsvValue;
        var frozen = Qt.rgba(src.r, src.g, src.b, src.a);

        var sliders = [];
        var square = null;
        _walk(picker, function (item) {
            if (typeof item.setValue === "function" && item.cursorHeight !== undefined)
                sliders.push(item);
            else if (item.hueColor !== undefined && item.saturation !== undefined)
                square = item;
        });
        if (sliders.length > 0)
            sliders[0].setValue(hue);
        if (square) {
            var cursor = null;
            var kids = square.children;
            for (var i = 0; i < kids.length; i++) {
                var kid = kids[i];
                // 色板内部: 两个带 gradient 的 Rectangle + 游标 Item + MouseArea
                if (kid.gradient === undefined && typeof kid.handleMouse !== "function"
                        && kid.width !== undefined)
                    cursor = kid;
            }
            if (cursor) {
                var radius = square.r === undefined ? 0 : square.r;
                cursor.x = sat * (square.width - 2 * radius);
                cursor.y = (1 - val) * (square.height - 2 * radius);
            }
        }
        picker.colorValue = frozen;
    }

    onCurrentColorChanged: {
        if (!_fromView)
            syncView();
    }
    // 尺寸要在"打开并完成布局"之后才有效(游标位置由色板宽高算出来)
    onOpened: syncView()

    modal: true
    focus: true
    width: 460
    padding: 0
    closePolicy: Popup.NoAutoClose
    anchors.centerIn: Overlay.overlay

    background: FluArea {
        radius: 8
    }

    contentItem: Column {
        width: dialog.width
        spacing: 0

        // 标题
        Item {
            width: parent.width
            height: 44
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: "自定义主题颜色"
                font.pixelSize: 13
                font.bold: true
                color: theme.textTitle
            }
        }
        Rectangle { width: parent.width; height: 1; color: theme.border }

        Row {
            width: parent.width - 36
            x: 18
            topPadding: 16
            spacing: 16

            // ---- FluentUI 取色面(色板 + 色相条)
            FluArea {
                id: pickerArea
                width: 236
                height: 200
                radius: 5

                ColorPicker {
                    id: picker
                    anchors.fill: parent
                    // 主题色不带透明度, 详情列由本对话框自己呈现(预览 + 十六进制输入)
                    enableAlphaChannel: false
                    enableDetails: false

                    onColorValueChanged: {
                        if (!dialog.opened || dialog._fromView)
                            return;
                        dialog._fromView = true;
                        dialog.currentColor = colorValue;
                        dialog._fromView = false;
                    }
                }
            }

            // ---- 预览 + 色值
            Column {
                width: parent.width - pickerArea.width - 16
                spacing: 10

                Rectangle {
                    width: parent.width
                    height: 56
                    radius: 6
                    color: dialog.currentColor
                    border.width: 1
                    border.color: theme.borderInput
                }

                PclTextField {
                    id: hexField
                    width: parent.width
                    text: dialog.currentColor.toString().toUpperCase()
                    placeholderText: "#RRGGBB"
                    onEditingFinished: dialog.applyHex(text)
                }

                Text {
                    width: parent.width
                    text: "输入十六进制色值后按回车确 定\n或在左侧色板 / 色相条上拖动取色"
                    font.pixelSize: 11
                    lineHeight: 1.3
                    color: theme.textHint
                    wrapMode: Text.WordWrap
                }
            }
        }

        // ---- 预设 + 按钮
        Row {
            width: parent.width - 36
            x: 18
            topPadding: 14
            spacing: 8

            Repeater {
                model: theme.presets

                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    color: modelData.color
                    border.width: 1
                    border.color: theme.borderInput
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dialog.applyHex(modelData.color)
                    }
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 16
            topPadding: 14
            bottomPadding: 16
            spacing: 10

            PclButton {
                text: "取消"
                implicitWidth: 84
                onClicked: dialog.close()
            }
            PclButton {
                kind: "primary"
                text: "确定"
                implicitWidth: 84
                onClicked: {
                    dialog.close();
                    dialog.colorAccepted(dialog.currentColor);
                }
            }
        }
    }
}
