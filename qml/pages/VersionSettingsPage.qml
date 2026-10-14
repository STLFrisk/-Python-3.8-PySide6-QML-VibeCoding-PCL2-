import QtQuick
import QtQuick.Controls.Basic
import "../components"
import "version"

// 二级页面: 版本设置(左侧 概览/设置/Mod管理/导出 为三级菜单, 带切换动画)
Item {
    id: page

    property var host: null
    property int section: 0

    function showSection(index) {
        if (index === page.section)
            return;
        page.section = index;
        innerStack.replace(innerStack.currentItem, sectionComponents[index]);
    }

    readonly property var sectionComponents: [
        overviewComponent, configComponent, modsComponent, exportComponent
    ]

    Component { id: overviewComponent; VersionOverviewPage { host: page.host } }
    Component { id: configComponent; VersionConfigPage { host: page.host } }
    Component { id: modsComponent; VersionModsPage { host: page.host } }
    Component { id: exportComponent; VersionExportPage { host: page.host } }

    Row {
        anchors.fill: parent
        spacing: 0

        RoundedPanel {
            width: 150
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

            Column {
                anchors.top: parent.top
                anchors.topMargin: 6
                width: parent.width

                SideItem {
                    width: parent.width
                    text: "概览"
                    iconName: "cube_grass"
                    checked: page.section === 0
                    onClicked: page.showSection(0)
                }
                SideItem {
                    width: parent.width
                    text: "设置"
                    iconName: "gear"
                    checked: page.section === 1
                    onClicked: page.showSection(1)
                }
                SideItem {
                    width: parent.width
                    text: "Mod 管理"
                    iconName: "package"
                    checked: page.section === 2
                    onClicked: page.showSection(2)
                }
                SideItem {
                    width: parent.width
                    text: "导出"
                    iconName: "export"
                    checked: page.section === 3
                    onClicked: page.showSection(3)
                }
            }
        }

        PclStack {
            id: innerStack
            width: parent.width - 150
            height: parent.height
            duration: Math.round(200 * Math.max(0.0, host ? host.animationScale : 1.0))
            initialItem: overviewComponent
        }
    }

    Connections {
        target: versionSettings

        function onGlobalSettingsRequested() {
            if (page.host)
                page.host.goRoot(2);
        }
    }
}
