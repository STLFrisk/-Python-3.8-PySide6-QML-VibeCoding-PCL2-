import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 下载页: 左侧分类(原版游戏 / 社区资源: Mod·整合包·数据包·资源包·光影包)
Item {
    id: page

    property var host: null
    property string section: "vanilla"      // vanilla | mod | modpack | datapack | resourcepack | shader
    property bool isVanilla: section === "vanilla"

    function installOrSelect(vid, installed) {
        if (!vid)
            return;
        // 下载页就是用来"安装"的: 即使这个版本已经装过, 也进安装页(可以重复安装/改名),
        // 选择版本请用「版本选择」页。
        if (host)
            host.openInstallVersion(vid);
    }

    function openSection(key) {
        section = key;
        if (key !== "vanilla") {
            community.setKind(key);
            if (community.resultsModel.count === 0)
                community.doSearch();
        }
    }

    Row {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------- 左侧分类
        RoundedPanel {
            width: 168
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

            Flickable {
                anchors.fill: parent
                contentHeight: sideColumn.height + 20
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: sideColumn
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    width: parent.width
                    spacing: 2

                    SideItem {
                        width: parent.width
                        text: "原版游戏"
                        iconName: "cube_grass"
                        checked: page.isVanilla
                        onClicked: page.openSection("vanilla")
                    }

                    // 分组标题: 指标对齐 FluNavigationView 的 header 单元格
                    // (FluNavigationView.qml:158-184: 单元格高 = cellHeight 38, 文字底对齐,
                    //  leftMargin 10, 字体 FluTextStyle.BodyStrong = 13px / weight 600)。
                    Text {
                        x: 10
                        height: 38
                        verticalAlignment: Text.AlignBottom
                        text: "社区资源"
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        color: theme.textSub
                    }

                    SideItem {
                        width: parent.width
                        text: "Mod"
                        iconName: "mod"
                        checked: page.section === "mod"
                        onClicked: page.openSection("mod")
                    }
                    SideItem {
                        width: parent.width
                        text: "整合包"
                        iconName: "modpack"
                        checked: page.section === "modpack"
                        onClicked: page.openSection("modpack")
                    }
                    SideItem {
                        width: parent.width
                        text: "数据包"
                        iconName: "datapack"
                        checked: page.section === "datapack"
                        onClicked: page.openSection("datapack")
                    }
                    SideItem {
                        width: parent.width
                        text: "资源包"
                        iconName: "resourcepack"
                        checked: page.section === "resourcepack"
                        onClicked: page.openSection("resourcepack")
                    }
                    SideItem {
                        width: parent.width
                        text: "光影包"
                        iconName: "shader"
                        checked: page.section === "shader"
                        onClicked: page.openSection("shader")
                    }
                }
            }
        }

        // ---------------------------------------------------- 右侧内容: 原版游戏
        Item {
            width: parent.width - 168
            height: parent.height
            visible: page.isVanilla

            Item {
                id: header
                width: parent.width
                height: 42

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: "版本列表来源: " + download.sourceHint
                          + (download.loading ? "   ·   正在获取版本列表…" : "")
                    font.pixelSize: 11
                    color: theme.textSub
                }

                PclButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: "刷新列表"
                    iconName: "refresh"
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: download.refreshForce(true)
                }
            }

            ScrollView {
                id: scroll
                y: header.height
                width: parent.width
                height: parent.height - header.height
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Column {
                    id: contentColumn
                    x: 14
                    y: 4
                    width: scroll.availableWidth - 28
                    spacing: 10
                    bottomPadding: 16

                    // 正式版/快照/远古/愚人节加起来有几百行, 一次性建出来会让页面
                    // 切换动画掉帧。这里等页面出现后再延迟一点创建列表内容。
                    property bool listsReady: false

                    Timer {
                        interval: 90
                        running: true
                        onTriggered: contentColumn.listsReady = true
                    }


                    Card {
                        title: "最新版本"
                        width: parent.width

                        VersionRow {
                            width: parent.width
                            visible: download.latestRelease.versionId !== undefined
                                     && download.latestRelease.versionId !== ""
                            title: download.latestRelease.versionId ? download.latestRelease.versionId : ""
                            subtitle: download.latestRelease.subtitle ? download.latestRelease.subtitle : ""
                            iconName: "cube_grass"
                            showTag: download.latestRelease.installed === true
                            onClicked: page.installOrSelect(download.latestRelease.versionId,
                                                            download.latestRelease.installed === true)
                        }

                        VersionRow {
                            width: parent.width
                            visible: download.latestSnapshot.versionId !== undefined
                                     && download.latestSnapshot.versionId !== ""
                            title: download.latestSnapshot.versionId ? download.latestSnapshot.versionId : ""
                            subtitle: download.latestSnapshot.subtitle ? download.latestSnapshot.subtitle : ""
                            iconName: "cube_sand"
                            showTag: download.latestSnapshot.installed === true
                            onClicked: page.installOrSelect(download.latestSnapshot.versionId,
                                                            download.latestSnapshot.installed === true)
                        }

                        Text {
                            visible: download.releaseModel.count === 0 && download.snapshotModel.count === 0
                            text: download.loading ? "正在获取版本列表…"
                                                   : "尚未获取到版本列表（可能没有网络，可点击右上角「刷新列表」重试）"
                            font.pixelSize: 11
                            color: theme.textHint
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "正式版"
                        count: download.releaseModel.count
                        expanded: true

                        Repeater {
                            model: contentColumn.listsReady ? download.releaseModel : []

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.versionId
                                subtitle: model.subtitle
                                iconName: model.icon
                                showTag: model.installed
                                onClicked: page.installOrSelect(model.versionId, model.installed)
                            }
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "预览版"
                        count: download.snapshotModel.count
                        expanded: false

                        Repeater {
                            model: contentColumn.listsReady ? download.snapshotModel : []

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.versionId
                                subtitle: model.subtitle
                                iconName: model.icon
                                showTag: model.installed
                                onClicked: page.installOrSelect(model.versionId, model.installed)
                            }
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "远古版"
                        count: download.oldModel.count
                        expanded: false

                        Repeater {
                            model: contentColumn.listsReady ? download.oldModel : []

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.versionId
                                subtitle: model.subtitle
                                iconName: model.icon
                                showTag: model.installed
                                onClicked: page.installOrSelect(model.versionId, model.installed)
                            }
                        }
                    }

                    Accordion {
                        width: parent.width
                        title: "愚人节版"
                        count: download.aprilModel.count
                        expanded: false

                        Repeater {
                            model: contentColumn.listsReady ? download.aprilModel : []

                            VersionRow {
                                width: parent.width - 20
                                x: 10
                                title: model.versionId
                                subtitle: model.subtitle
                                iconName: model.icon
                                showTag: model.installed
                                onClicked: page.installOrSelect(model.versionId, model.installed)
                            }
                        }
                    }
                }
            }
        }

        // ---------------------------------------------------- 右侧内容: 社区资源
        Item {
            width: parent.width - 168
            height: parent.height
            visible: !page.isVanilla

            ScrollView {
                id: resScroll
                anchors.fill: parent
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Column {
                    x: 14
                    y: 10
                    width: resScroll.availableWidth - 28
                    spacing: 10
                    bottomPadding: 16

                    Card {
                        title: "搜索" + community.kindLabel
                        width: parent.width

                        Grid {
                            width: parent.width
                            columns: 2
                            columnSpacing: 12
                            rowSpacing: 8

                            // 名称
                            Row {
                                width: (parent.width - 12) / 2
                                spacing: 8
                                Text {
                                    width: 56
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "名称"
                                    font.pixelSize: 12
                                    color: theme.text
                                }
                                PclTextField {
                                    id: nameField
                                    width: parent.width - 64
                                    placeholderText: "留空则按热度列出"
                                    text: community.query
                                    onAccepted: page.doSearch()
                                }
                            }

                            // 来源
                            Row {
                                width: (parent.width - 12) / 2
                                spacing: 8
                                Text {
                                    width: 56
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "来源"
                                    font.pixelSize: 12
                                    color: theme.text
                                }
                                PclComboBox {
                                    width: parent.width - 64
                                    model: ["全部", "Modrinth", "CurseForge"]
                                    currentIndex: community.source === "modrinth" ? 1
                                                  : (community.source === "curseforge" ? 2 : 0)
                                    onActivated: (index) => community.setSource(
                                                      index === 1 ? "modrinth"
                                                                  : (index === 2 ? "curseforge" : "all"))
                                }
                            }

                            // 版本(游戏版本号, 可自行输入)
                            Row {
                                width: (parent.width - 12) / 2
                                spacing: 8
                                Text {
                                    width: 56
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "版本"
                                    font.pixelSize: 12
                                    color: theme.text
                                }
                                PclTextField {
                                    id: versionField
                                    width: parent.width - 64
                                    placeholderText: "全部（可自行输入，如 1.20.1）"
                                    text: community.mcVersion
                                }
                            }

                            // 加载器
                            Row {
                                width: (parent.width - 12) / 2
                                spacing: 8
                                Text {
                                    width: 56
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "加载器"
                                    font.pixelSize: 12
                                    color: theme.text
                                }
                                PclComboBox {
                                    width: parent.width - 64
                                    model: ["全部", "Fabric", "Forge", "NeoForge", "Quilt"]
                                    onActivated: (index) => community.setLoader(
                                                      index === 0 ? "" :
                                                      ["", "fabric", "forge", "neoforge",
                                                       "quilt"][index])
                                }
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 10

                            PclButton {
                                kind: "primary"
                                text: "搜索"
                                iconName: "search"
                                implicitWidth: 96
                                implicitHeight: 30
                                onClicked: page.doSearch()
                            }
                            PclButton {
                                text: "重置条件"
                                implicitWidth: 110
                                implicitHeight: 30
                                onClicked: {
                                    nameField.text = "";
                                    versionField.text = "";
                                    community.resetFilters();
                                }
                            }
                            PclButton {
                                visible: community.kind === "modpack"
                                text: "安装已有整合包"
                                implicitWidth: 140
                                implicitHeight: 30
                                onClicked: if (page.host) page.host.askModpackFile()
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                // 注意: 这里必须用显式宽度, 不能写 parent.width - N ——
                                // 父级 Row 的宽度由子项决定, 会形成循环绑定把界面卡死
                                width: Math.max(60, community.kind === "modpack"
                                                   ? page.width - 640 : page.width - 460)
                                text: community.statusText
                                font.pixelSize: 11
                                color: theme.textHint
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Repeater {
                        model: community.resultsModel

                        Rectangle {
                            width: parent.width
                            height: 78
                            radius: 4
                            color: resultMouse.containsMouse ? theme.hover : "transparent"

                            Image {
                                id: resultIcon
                                x: 10
                                anchors.verticalCenter: parent.verticalCenter
                                width: 48
                                height: 48
                                source: model.icon
                                sourceSize.width: 48
                                sourceSize.height: 48
                                asynchronous: true
                                visible: model.icon !== ""
                            }

                            Column {
                                x: 68
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 80
                                spacing: 3

                                Row {
                                    spacing: 8
                                    Text {
                                        text: model.title
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: theme.textTitle
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: model.source
                                        font.pixelSize: 11
                                        color: theme.primary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: model.summary
                                    font.pixelSize: 11
                                    color: theme.textSub
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: model.meta + "     " + model.downloads + "     " + model.updated
                                    font.pixelSize: 10
                                    color: theme.textHint
                                    elide: Text.ElideRight
                                }
                            }

                            MouseArea {
                                id: resultMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    // 选中资源 → 进三级页面(文件按加载器/适配版本分组);
                                    // 用项目 id 而不是行号, 避免异步搜索导致行号错位
                                    if (page.host)
                                        page.host.openResourceDetail(model.id, model.title,
                                                                     model.icon);
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        visible: community.resultsModel.count === 0 && !community.loading
                        text: "还没有结果。填好条件后点「搜索」。"
                        font.pixelSize: 11
                        color: theme.textHint
                    }
                }
            }
        }
    }

    function doSearch() {
        community.applyFilters(nameField.text, versionField.text, community.loader);
        community.doSearch();
    }

    // 资源详情: 选择具体文件并下载
    Popup {
        id: filePopup

        width: Math.min(680, page.width - 200)
        height: Math.min(420, page.height - 120)
        padding: 0
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        anchors.centerIn: Overlay.overlay
        visible: false

        background: Rectangle {
            radius: 8
            color: "white"
            border.width: 1
            border.color: theme.border
        }

        contentItem: Column {
            width: filePopup.width
            spacing: 0

            Item {
                width: parent.width
                height: 40
                Text {
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: community.detailTitle
                    font.pixelSize: 13
                    font.bold: true
                    color: theme.textTitle
                }
                PclButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: "关闭"
                    implicitWidth: 72
                    implicitHeight: 26
                    onClicked: {
                        filePopup.close();
                        community.closeDetail();
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: theme.border }

            ListView {
                width: parent.width
                height: filePopup.height - 78
                clip: true
                model: community.filesModel
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    width: ListView.view.width
                    height: 52
                    color: fileMouse.containsMouse ? theme.hover : "transparent"

                    Column {
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 120
                        spacing: 2
                        Text {
                            width: parent.width
                            text: model.name + "   (" + model.file + ")"
                            font.pixelSize: 12
                            color: theme.text
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width
                            text: model.size + "   " + model.date + "   " + model.loaders
                                  + "   " + model.versions
                            font.pixelSize: 10
                            color: theme.textHint
                            elide: Text.ElideRight
                        }
                    }

                    PclButton {
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "primary"
                        text: "下载"
                        implicitWidth: 76
                        implicitHeight: 26
                        onClicked: community.downloadFile(index)
                    }

                    MouseArea {
                        id: fileMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: community.downloadFile(index)
                    }
                }
            }

            Text {
                x: 16
                width: parent.width - 32
                topPadding: 6
                bottomPadding: 8
                text: community.statusText
                font.pixelSize: 11
                color: theme.textHint
                elide: Text.ElideRight
            }
        }
    }

    // 资源详情现在走三级页面(见 ResourceDetailPage.qml), 版本安装走 InstallVersionPage.qml
}
