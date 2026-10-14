import QtQuick
import QtQuick.Controls.Basic
import FluentUI

// 兼容层: 对外接口(title / text / kind / showCancel / okText / cancelText /
// inputVisible / inputText / inputPlaceholder / inputError / open() / close() /
// accepted / rejected)完全不变, 内部换成 PySide6-FluentUI-QML 的 FluContentDialog,
// 因此所有页面不需要改动就能切到 Fluent 外观。
FluContentDialog {
    id: dialog

    // ---- 原有接口 ----
    property string text: ""
    property string kind: "info"          // info | warn | error | success | question
    property bool showCancel: false
    property string okText: "确定"
    property string cancelText: "取消"
    property bool inputVisible: false
    property string inputPlaceholder: ""
    property string inputError: ""
    // 注意: 不能写成 alias inputField.text —— inputField 在 Component 内部, 别名取不到。
    // 这里用一个独立属性, 与输入框双向同步。
    property string inputText: ""

    signal accepted()
    signal rejected()

    // ---- 确认时序状态(修「对话框一打开输入框就是空的, 且已经报名称不能为空」) ----
    // confirmArmed: 只有对话框**真正打开之后**(onOpened, 打开动画播完)才把按钮点击当成
    //   用户确认 —— 保证"默认名先就位, 再有确认"(见 onOpened / _handleConfirm)。
    // _dispatchingAccept: 正在派发 accepted(); 调用方的校验逻辑与"校验失败立刻重开"
    //   全都发生在这一段区间里, 用它可以分辨"重开"与"用户重新发起的一次打开"。
    // _errorBeforeAccept: 派发 accepted() 之前的 inputError, 用来判断调用方这次有没有报错。
    property bool confirmArmed: false
    property bool _dispatchingAccept: false
    property string _errorBeforeAccept: ""

    // 派发"确认"。**必须**用它而不是直接 accepted(), 否则 onAboutToShow 无法分辨
    // "校验失败后调用方立刻重开"(要保留错误提示与用户输入)。
    function _emitAccepted() {
        dialog._errorBeforeAccept = dialog.inputError;
        dialog._dispatchingAccept = true;
        dialog.accepted();
        dialog._dispatchingAccept = false;
        dialog._errorBeforeAccept = "";
    }

    readonly property string kindIcon: {
        if (kind === "warn")
            return "warn";
        if (kind === "error")
            return "error";
        if (kind === "success")
            return "check";
        if (kind === "question")
            return "question";
        return "info";
    }
    readonly property string kindColor: {
        if (kind === "warn")
            return "#E8A33D";
        if (kind === "error")
            return theme.danger;
        if (kind === "success")
            return theme.success;
        return theme.primary;
    }

    // ---- 映射到 FluentUI ----
    message: dialog.text
    positiveText: dialog.okText
    negativeText: dialog.cancelText
    buttonFlags: dialog.showCancel
                 ? (FluContentDialogType.NegativeButton | FluContentDialogType.PositiveButton)
                 : FluContentDialogType.PositiveButton

    // ---- 按钮点击: 必须**接管套件的 listener**, 只挂信号是不够的 ----
    // ⚠️ 历史坑一(上一轮修掉): 这里原本写着两条
    //     onPositiveClickListener: { dialog.close(); dialog.accepted(); }
    //     onNegativeClickListener: { dialog.close(); dialog.rejected(); }
    // FluContentDialog 本来就声明了 `property var onPositiveClickListener`, 所以
    // `onXxxClickListener: { ... }` 不是"信号处理器"而是**属性绑定**, 而绑定在
    // **对象构造时**就求值 → 构造 PclDialog 的一瞬间就把 accepted() 发了一遍
    // (调用方还没在 onOpened 里填默认名) → 校验失败写下 "名称不能为空" →
    // 之后真正打开时默认名被 inputError 挡住 → "一打开就是空的, 还already报错"。
    //
    // ⚠️ 历史坑二(本轮修的, 是上一个坑的反面, 两者都出在"谁负责关对话框"上):
    // vendor/FluentUI/qml/FluentUI/Controls/FluContentDialog.qml:143-150 的按钮点击是
    //     if (control.onPositiveClickListener) { control.onPositiveClickListener() }
    //     else { positiveClicked(); control.close() }
    // 只挂信号(不设 listener)就走 else: 我们的 onPositiveClicked 里, 调用方
    // (InstallVersionPage.confirmName)可能已经因为校验失败而 `renameDialog.open()`
    // 把对话框**重新打开**了, 但信号派发返回之后 vendor 那句 `control.close()` 才执行
    // —— 于是刚重开的对话框又被关掉。表现就是"命名重复/非法时对话框直接消失,
    // 那句红字根本来不及看见"(实测 opened=False visible=False)。
    // 所以这里用**函数字面量**接管 listener: vendor 不再自己 close, 关不关由
    // _handleConfirm()/_handleCancel() 按"调用方有没有报错"决定。
    // 🔑 关键区别(别再踩): `function () { ... }` 是**函数字面量**, 绑定在构造期只是把
    // 这个函数对象赋给属性, **不执行函数体**; 上一个坑那两行写成语句块 `{ ... }`
    // 才会在构造期被执行。两者长得像, 语义完全不同。
    onPositiveClickListener: function () {
        dialog._handleConfirm();
    }
    onNegativeClickListener: function () {
        dialog._handleCancel();
    }
    onNeutralClickListener: function () {
        dialog._handleCancel();
    }

    // 信号那条路也接住(套件版本不同时"谁生效都能走通"), 但同一次点击**只处理一次**:
    // 万一某个套件版本既调 listener 又发 positiveClicked, 没有这个闸门就会
    // 确认两次(装两遍)。_clickHandled 由 Qt.callLater 在下一轮事件循环里清掉,
    // 所以下一次真实点击不受影响。
    property bool _clickHandled: false

    // 同一次点击只放行一次(见上面的说明)。
    function _beginClick() {
        if (dialog._clickHandled)
            return false;
        dialog._clickHandled = true;
        Qt.callLater(function () {
            dialog._clickHandled = false;
        });
        return true;
    }

    // "确定": 先关掉再派发 accepted()。调用方校验失败时会自己 open() 重开,
    // 这时**没有任何人再关它**(vendor 的 close 已经被 listener 分支绕开了),
    // 所以红字能留在屏幕上。
    function _handleConfirm() {
        if (!dialog.confirmArmed)
            return;
        if (!dialog._beginClick())
            return;
        dialog.close();
        dialog._emitAccepted();
    }

    // "取消" / "中立": 关掉并派发 rejected()。
    function _handleCancel() {
        if (!dialog.confirmArmed)
            return;
        if (!dialog._beginClick())
            return;
        dialog.close();
        dialog.rejected();
    }

    onPositiveClicked: {
        dialog._handleConfirm();
    }
    onNegativeClicked: {
        dialog._handleCancel();
    }
    onNeutralClicked: {
        dialog._handleCancel();
    }

    // 每次**打开之前**跑, 一定早于调用方的 onOpened(默认名是在那里填进去的)。
    onAboutToShow: {
        // 分辨这一次打开是"校验失败后调用方立刻重开"还是"用户重新发起的一次打开":
        // 前者发生在 _emitAccepted() 派发区间里, 且调用方在区间内改写了 inputError。
        var validationReopen = dialog._dispatchingAccept
                               && dialog.inputError !== dialog._errorBeforeAccept;
        // 输入框空着却还挂着上一次的错误 = 死锁状态: 调用方 onOpened 里的
        // `if (inputError === "")` 会让默认名永远填不进来。用户重新发起打开时先把
        // 遗留错误清掉, 默认名就能照常填好(这正是老 bug 缺掉的那一步)。
        // 校验失败的那次立刻重开则**保留**错误与用户输入, 否则用户刚敲进去的名字
        // 会被默认名冲掉(曾经修过一次的回归)。
        if (!validationReopen && dialog.inputError !== "")
            dialog.inputError = "";
        // 打开动画结束前不接受"确认", 见 onOpened。
        dialog.confirmArmed = false;
    }

    onOpened: {
        // 打开完成 → 现在按钮点击才算用户确认。
        // 注意顺序: 本组件的 onOpened 先于调用方的 onOpened 执行, 但两者在同一次信号
        // 派发里同步跑完, 中间不可能插进鼠标事件 —— 所以等到用户能点击时, 默认名
        // 一定已经由调用方填进输入框了。
        dialog.confirmArmed = true;
    }

    // 类型图标 + 输入框 + 校验错误(显示在按钮上方 —— FluContentDialog 的按钮在最下面)
    contentDelegate: Component {
        Column {
            width: parent ? parent.width : 380
            // 必须显式给出高度: FluContentDialog 用 `Layout.preferredHeight: item.height`
            // 计算内容区高度, Column 不写 height 时其 height 为 0 → 内容区高度 0 →
            // 输入框会被按钮压住(表现为"按钮把重命名输入框遮住了")。
            height: implicitHeight
            spacing: 6

            Row {
                spacing: 8
                visible: dialog.kind !== "info" && dialog.kind !== ""

                Image {
                    width: 16
                    height: 16
                    anchors.verticalCenter: parent.verticalCenter
                    source: "image://icon/" + dialog.kindIcon + "?color="
                            + encodeURIComponent(dialog.kindColor) + "&size=16"
                    sourceSize.width: 16
                    sourceSize.height: 16
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: dialog.kind === "error" ? "错误"
                          : (dialog.kind === "warn" ? "注意"
                             : (dialog.kind === "success" ? "完成" : "提示"))
                    font.pixelSize: 12
                    color: dialog.kindColor
                }
            }

            PclTextField {
                id: inputField
                width: parent.width
                visible: dialog.inputVisible
                placeholderText: dialog.inputPlaceholder
                text: dialog.inputText
                // 只做双向同步; **不要**在这里清 inputError —— 校验失败后对话框会重新打开,
                // 调用方靠 "inputError 非空" 判断"这是重开, 别重置输入框",
                // 这里一旦清掉, 用户的输入就会被默认名覆盖(表现为"输入最后又变回原版本号")。
                // 清理由 onAboutToShow 在**打开之前**按"是不是校验失败的那次重开"决定。
                onTextChanged: dialog.inputText = text
                // 输入框里按回车 = 点"确定"(同样要过 confirmArmed: 打开完成前不算确认)
                onAccepted: {
                    if (!dialog.confirmArmed)
                        return;
                    dialog.close();
                    dialog._emitAccepted();
                }
            }

            Text {
                width: parent.width
                visible: dialog.inputVisible && dialog.inputError !== ""
                text: dialog.inputError
                font.pixelSize: 11
                color: theme.danger
                elide: Text.ElideRight
            }
        }
    }
}
