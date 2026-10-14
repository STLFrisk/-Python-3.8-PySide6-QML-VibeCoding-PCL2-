import QtQuick
import QtQuick.Controls.Basic
import "../components"
import "settings"

// 一级页面: 设置(左侧 启动/个性化/其他 为二级菜单, 带切换动画)
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

    readonly property var sectionComponents: [launchComponent, personalComponent, otherComponent]

    Component { id: launchComponent; LaunchSettings { host: page.host } }
    Component { id: personalComponent; PersonalizationSettings { host: page.host } }
    Component { id: otherComponent; OtherSettings { host: page.host } }

    Row {
        anchors.fill: parent
        spacing: 0

        RoundedPanel {
            width: 160
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
                    text: "启动"
                    iconName: "play"
                    checked: page.section === 0
                    onClicked: page.showSection(0)
                }
                SideItem {
                    width: parent.width
                    text: "个性化"
                    iconName: "palette"
                    checked: page.section === 1
                    onClicked: page.showSection(1)
                }
                SideItem {
                    width: parent.width
                    text: "其他"
                    iconName: "grid"
                    checked: page.section === 2
                    onClicked: page.showSection(2)
                }
            }
        }

        PclStack {
            id: innerStack
            width: parent.width - 160
            height: parent.height
            duration: Math.round(200 * Math.max(0.0, host ? host.animationScale : 1.0))
            initialItem: launchComponent
        }
    }
}
