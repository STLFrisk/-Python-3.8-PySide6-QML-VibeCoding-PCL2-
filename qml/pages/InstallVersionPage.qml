import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 三级页面: 安装 <版本> —— 勾选要装的模组加载器, 再进四级页面挑版本
Item {
    id: page

    property var host: null
    property string mcVersion: ""
    property var pending: []          // 等待确认命名的加载器队列
    property string currentKey: ""
    property string currentLoaderName: ""
    property string defaultName: ""   // 本次要安装的默认版本名

    function refresh() {
        if (mcVersion !== "")
            download.queryLoaders(mcVersion);
    }

    // 开始安装: 把勾选的加载器逐个走一遍「重命名确认」
    function startInstall() {
        var chosen = download.selectedLoaders;
        if (chosen.length === 0) {
            backend.toastRequested("请先勾选要安装的加载器");
            return;
        }
        pending = chosen;
        askNextName();
    }

    function askNextName() {
        if (pending.length === 0) {
            renameDialog.close();
            return;
        }
        var item = pending[0];
        currentKey = item.key;
        currentLoaderName = item.name;
        defaultName = download.defaultVersionName(item.key, mcVersion);
        renameDialog.title = "安装 " + item.name + " " + item.version;
        renameDialog.text = "将安装：" + mcVersion + " + " + item.name + " " + item.version
                            + (pending.length > 1 ? "（还有 " + (pending.length - 1)
                                                    + " 个加载器排队）" : "")
                            + "\n可以修改版本名称，安装后会以此名字出现在版本列表里。";
        renameDialog.open();
    }

    function confirmName() {
        var name = String(renameDialog.inputText || "").trim();
        var error = download.validateVersionName(name);
        if (error !== "") {
            renameDialog.inputError = error;
            // 注意: FluContentDialog 的"确定"按钮自己会 close(), 所以这里必须把对话框
            // 重新打开一次, 否则错误提示会在框已关闭后才设置 —— 用户根本看不到
            // (表现就是"重名/非法符号检测消失了")。
            renameDialog.open();
            return;
        }
        download.installWithLoader(currentKey, mcVersion, name);
        pending = pending.slice(1);
        askNextName();
    }

    Component.onCompleted: refresh()

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Column {
            x: 16
            y: 12
            width: scroll.availableWidth - 32
            spacing: 10
            bottomPadding: 18

            Card {
                title: "安装 Minecraft " + page.mcVersion
                width: parent.width

                Text {
                    width: parent.width
                    text: "选择一个要安装的模组加载器（Forge / Fabric / NeoForge / Quilt /"
                          + " OptiFine 同一时间只能选一个，选新的会自动取消旧的），"
                          + "再点「选择版本」进四级页面挑具体加载器版本，最后点「开始安装」。"
                          + "原版会自动装好，进度可在右下角圆标里查看。"
                    font.pixelSize: 11
                    color: theme.textSub
                    wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        kind: "primary"
                        text: "开始安装"
                        iconName: "download"
                        implicitWidth: 124
                        implicitHeight: 32
                        enabled: download.selectedLoaders.length > 0
                        onClicked: page.startInstall()
                    }
                    PclButton {
                        text: "只安装原版"
                        implicitWidth: 120
                        implicitHeight: 32
                        onClicked: {
                            page.currentKey = "vanilla";
                            page.currentLoaderName = "原版";
                            page.defaultName = page.mcVersion;
                            renameDialog.title = "安装原版 " + page.mcVersion;
                            renameDialog.text = "将只安装原版 " + page.mcVersion
                                                + "。\n可以修改版本名称。";
                            renameDialog.open();
                        }
                    }
                    PclButton {
                        text: "重新获取列表"
                        iconName: "refresh"
                        implicitWidth: 140
                        implicitHeight: 32
                        onClicked: {
                            download.queryLoaders(page.mcVersion + " ");
                            download.queryLoaders(page.mcVersion);
                        }
                    }
                }
            }

            Card {
                title: "模组加载器"
                width: parent.width

                Text {
                    width: parent.width
                    visible: download.loaderVersion !== ""
                    text: "以下为 " + download.loaderVersion + " 可用的加载器（勾选后可点「选择版本」）："
                    font.pixelSize: 11
                    color: theme.textHint
                }

                Repeater {
                    model: download.loaderRows

                    Rectangle {
                        width: parent.width
                        height: 44
                        radius: 4
                        color: loaderMouse.containsMouse ? theme.hover : "transparent"

                        // 单选(radio): Forge / Fabric / NeoForge / Quilt / OptiFine 同一时间
                        // 只能选中一个, 互斥由后端 download.toggleLoader 保证(选新的自动取消旧的)。
                        PclRadioButton {
                            id: loaderCheck
                            x: 4
                            anchors.verticalCenter: parent.verticalCenter
                            visible: (modelData.versions || []).length > 0
                            // 用 Binding 而不是 checked: xxx —— 用户点击会把普通绑定打断,
                            // 之后互斥逻辑取消勾选时界面就不会跟着变了(表现为两个都选着)
                            Binding on checked {
                                value: modelData.selected === true
                            }
                            onClicked: download.toggleLoader(modelData.key)
                        }

                        Text {
                            x: 34
                            width: 100
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.name
                            font.pixelSize: 12
                            font.bold: true
                            color: theme.textTitle
                        }

                        Text {
                            x: 140
                            width: parent.width - 140 - 180
                            anchors.verticalCenter: parent.verticalCenter
                            text: (modelData.versions || []).length > 0
                                  ? "已选版本：" + (modelData.current || "")
                                  : modelData.state
                            font.pixelSize: 11
                            color: (modelData.versions || []).length > 0 ? theme.text : theme.textHint
                            elide: Text.ElideRight
                        }

                        PclButton {
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: 132
                            implicitHeight: 28
                            text: (modelData.versions || []).length > 0 ? "选择版本 ›" : "—"
                            enabled: (modelData.versions || []).length > 0
                            onClicked: if (page.host)
                                           page.host.openLoaderVersions(modelData.key,
                                                                        modelData.name)
                        }

                        MouseArea {
                            id: loaderMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            z: -1
                            onClicked: {
                                if ((modelData.versions || []).length > 0)
                                    download.toggleLoader(modelData.key);
                            }
                        }
                    }
                }
            }

            Text {
                width: parent.width
                text: "提示：OptiFine 官方没有自动安装接口，需要手动运行它的安装器；"
                      + "装好后本启动器会自动识别（也可以把它当成 Mod 放进 mods 目录）。"
                font.pixelSize: 11
                color: theme.textHint
                wrapMode: Text.WordWrap
            }
        }
    }

    // 安装前确认名称(重命名 + 重名/非法字符校验); 输入框用对话框自带的那一套,
    // 它就在按钮【上面】。
    PclDialog {
        id: renameDialog
        showCancel: true
        okText: "开始安装"
        inputVisible: true
        inputPlaceholder: "新的版本名"

        onOpened: {
            // 校验失败时对话框会被重新打开以显示错误, 这时不要重置名称(否则用户输入被冲掉);
            // 只有首次打开(inputError 为空)才填默认名。
            if (inputError === "") {
                inputText = page.defaultName;
            }
        }
        onAccepted: page.confirmName()
    }
}
