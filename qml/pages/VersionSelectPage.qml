import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 二级页面: 版本选择(原独立窗口, 现在合并进主窗口)
Item {
    id: page

    property var host: null

    // 选中版本并回到启动界面
    function pickVersion(versionId, name) {
        backend.selectVersion(versionId);
        backend.toastRequested("已选择版本 " + name);
        if (host)
            host.goRoot(0);
    }

    // 跳到这个版本的设置界面
    function openSettingsFor(versionId) {
        backend.selectVersion(versionId);
        if (host)
            host.openVersionSettings();
    }

    Row {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------ 文件夹列表
        RoundedPanel {
            width: 200
            height: parent.height
            color: theme.sideBg
            roundTop: false
            roundBottom: true
            radius: theme.cornerRadius

            Rectangle {
                width: 1
                height: parent.height
                anchors.right: parent.right
                color: theme.border
            }

            ScrollView {
                id: scrollFolder
                anchors.fill: parent
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Column {
                    x: 8
                    y: 10
                    width: scrollFolder.availableWidth - 16
                    spacing: 2

                    Text {
                        text: "文件夹列表"
                        font.pixelSize: 11
                        color: theme.textHint
                        leftPadding: 4
                        bottomPadding: 4
                    }

                    Repeater {
                        model: backend.folderModel

                        FolderItem {
                            width: parent.width
                            folderName: model.name
                            folderPath: model.path
                            active: model.active
                            onClicked: backend.selectFolder(index)
                        }
                    }

                    Text {
                        text: "添加或导入"
                        font.pixelSize: 11
                        color: theme.textHint
                        leftPadding: 4
                        topPadding: 10
                        bottomPadding: 4
                    }

                    ActionRow {
                        width: parent.width
                        iconName: "folder_new"
                        text: "新建 .minecraft 文件夹"
                        onClicked: if (page.host) page.host.askCreateFolder()
                    }
                    ActionRow {
                        width: parent.width
                        iconName: "plus"
                        text: "添加已有文件夹"
                        onClicked: if (page.host) page.host.askAddFolder()
                    }
                    ActionRow {
                        width: parent.width
                        iconName: "import"
                        text: "导入整合包"
                        onClicked: if (page.host) page.host.askImportPack()
                    }
                }
            }
        }

        // ------------------------------------------ 版本列表
        Item {
            width: parent.width - 200
            height: parent.height

            ScrollView {
                id: scroll
                anchors.fill: parent
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Column {
                    x: 14
                    y: 12
                    width: scroll.availableWidth - 28
                    spacing: 10
                    bottomPadding: 18

                    // 正在检索时的提示
                    Text {
                        visible: backend.scanning
                        width: parent.width
                        text: "正在检索 " + backend.folderName + " 里的游戏版本…"
                        font.pixelSize: 11
                        color: theme.textHint
                    }

                    // 一个已安装版本都没有时的提示(不再显示示例数据)
                    Rectangle {
                        visible: !backend.scanning && backend.versionCount === 0
                        width: parent.width
                        height: emptyText.height + 20
                        radius: 4
                        color: theme.primarySoft
                        border.width: 1
                        border.color: theme.border

                        Text {
                            id: emptyText
                            x: 10
                            y: 10
                            width: parent.width - 20
                            text: "在「" + backend.folderName + "」里没有找到已安装的游戏版本。\n"
                                  + "可以到「下载 → 原版游戏」安装一个真实版本，"
                                  + "或用左侧「添加已有文件夹」指向你已有的 .minecraft 文件夹。"
                            font.pixelSize: 11
                            color: theme.textSub
                            wrapMode: Text.WordWrap
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "含 Mod 的版本"
                        count: backend.installableModel.count
                        expanded: true

                        Text {
                            x: 12
                            width: parent.width - 24
                            visible: backend.installableModel.count === 0
                            text: "还没有带 Mod 加载器的版本。可以到「下载」页安装，"
                                  + "或把已有的 .minecraft 文件夹添加进来。"
                            font.pixelSize: 11
                            color: theme.textHint
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: backend.installableModel

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.name
                                subtitle: model.note !== "" ? model.subtitle + "   ·   " + model.note
                                                            : model.subtitle
                                iconName: model.icon
                                selected: model.versionId === backend.selectedVersionId
                                showTag: model.installed
                                deletable: model.installed
                                onDeleteClicked: backend.requestDeleteVersion(model.versionId)
                                onSettingsClicked: page.openSettingsFor(model.versionId)
                                onClicked: page.pickVersion(model.versionId, model.name)
                            }
                        }
                    }

                    // 还没装的加载器单独一栏(折叠), 避免和"真实存在的版本"混在一起
                    Accordion {
                        width: parent.width
                        title: "可安装 Mod 加载器（未安装）"
                        count: backend.catalogModel.count
                        expanded: false

                        Repeater {
                            model: backend.catalogModel

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.name
                                subtitle: model.note !== "" ? model.subtitle + "   ·   " + model.note
                                                            : model.subtitle
                                iconName: model.icon
                                onClicked: installDialog.openFor(model.versionId, model.mcVersion,
                                                                 model.loader, model.loaderVersion)
                            }
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "常规版本"
                        count: backend.normalModel.count
                        expanded: true

                        Repeater {
                            model: backend.normalModel

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.name
                                subtitle: model.subtitle
                                iconName: model.icon
                                selected: model.versionId === backend.selectedVersionId
                                deletable: model.installed
                                onDeleteClicked: backend.requestDeleteVersion(model.versionId)
                                onSettingsClicked: page.openSettingsFor(model.versionId)
                                onClicked: page.pickVersion(model.versionId, model.name)
                                onDoubleClicked: {
                                    backend.selectVersion(model.versionId);
                                    if (page.host)
                                        page.host.goRoot(0);
                                    backend.launchGame();
                                }
                            }
                        }

                        Text {
                            x: 12
                            visible: backend.normalModel.count === 0
                            text: "暂无已安装的常规版本"
                            font.pixelSize: 11
                            color: theme.textHint
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "不常用版本"
                        count: backend.uncommonModel.count
                        expanded: false

                        Repeater {
                            model: backend.uncommonModel

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.name
                                subtitle: model.subtitle
                                iconName: model.icon
                                selected: model.versionId === backend.selectedVersionId
                                deletable: model.installed
                                onDeleteClicked: backend.requestDeleteVersion(model.versionId)
                                onSettingsClicked: page.openSettingsFor(model.versionId)
                                onClicked: page.pickVersion(model.versionId, model.name)
                            }
                        }
                    }
                }
            }
        }
    }

    // 安装(可安装 Mod 列表)确认框
    PclDialog {
        id: installDialog
        property string pendingId: ""
        property string pendingMc: ""
        property string pendingLoader: ""
        property string pendingLoaderVersion: ""
        showCancel: true
        okText: "开始安装"

        function openFor(id, mc, loader, loaderVersion) {
            pendingId = id;
            pendingMc = mc;
            pendingLoader = loader;
            pendingLoaderVersion = loaderVersion;
            title = "安装 " + id;
            text = "游戏版本: " + mc + "\n加载器: " + loader + " " + loaderVersion
                   + "\n\n将下载该版本的依赖库与资源文件到：\n" + backend.selectedFolderPath
                   + "\n\n（Forge / NeoForge / 整合包 的自动安装尚未实现，会给出提示。）";
            open();
        }

        onAccepted: backend.installCatalogVersion(pendingId)
    }
}
