import QtQuick

// 版本列表行(图标 + 标题 + 副标题)
Item {
    id: row

    property string title: ""
    property string subtitle: ""
    property string iconName: "cube_grass"
    property int iconSize: 32
    property bool installed: false
    property bool selected: false
    property bool showTag: false
    property string tagText: "已安装"
    property bool deletable: false

    signal clicked()
    signal doubleClicked()
    signal deleteClicked()
    signal settingsClicked()

    // 行悬停状态: 统一用 HoverHandler 追踪(不用 MouseArea 的 containsMouse ——
    // 子项的 hoverEnabled 会把它抢走)。hoverActive 立即变 true、延迟变 false,
    // 这样"平时隐藏、悬停才出现"也不会因为任何瞬时抖动而闪烁。
    property bool hoverActive: false

    HoverHandler {
        id: rowHover

        onHoveredChanged: {
            if (hovered) {
                row.hoverActive = true;
                hideTimer.stop();
            } else {
                hideTimer.restart();
            }
        }
    }

    Timer {
        id: hideTimer
        interval: 140
        onTriggered: row.hoverActive = false
    }

    implicitHeight: 46
    implicitWidth: 200

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: row.selected ? theme.selected
             : (row.hoverActive ? theme.hover : "transparent")
    }

    Image {
        id: icon
        x: 10
        anchors.verticalCenter: parent.verticalCenter
        width: row.iconSize
        height: row.iconSize
        source: "image://icon/" + row.iconName + "?size=" + row.iconSize
        sourceSize.width: row.iconSize
        sourceSize.height: row.iconSize
        smooth: true
    }

    Column {
        anchors.left: icon.right
        anchors.leftMargin: 12
        anchors.right: tag.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Text {
            text: row.title
            font.pixelSize: 13
            color: theme.textTitle
            elide: Text.ElideRight
            width: parent.width
        }
        Text {
            text: row.subtitle
            font.pixelSize: 11
            color: theme.textSub
            elide: Text.ElideRight
            width: parent.width
            visible: row.subtitle !== ""
        }
    }

    Rectangle {
        id: tag
        anchors.right: settingsButton.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        visible: row.showTag
        width: tagLabel.implicitWidth + 12
        height: 18
        radius: 9
        color: theme.primarySoft
        Text {
            id: tagLabel
            anchors.centerIn: parent
            text: row.tagText
            font.pixelSize: 11
            color: theme.primary
        }
    }

    // 版本设置按钮(已安装版本才会出现, 和删除按钮一样平时隐藏、悬停出现)
    Item {
        id: settingsButton
        objectName: "settingsButton"
        visible: row.deletable && (row.hoverActive || row.selected)
        z: 10
        width: 26
        height: 26
        anchors.right: parent.right
        anchors.rightMargin: 40
        anchors.verticalCenter: parent.verticalCenter
        opacity: visible ? 1.0 : 0.0

        Rectangle {
            anchors.fill: parent
            radius: 4
            color: settingsMouse.containsMouse ? theme.primarySoft : "transparent"
        }
        Image {
            anchors.centerIn: parent
            width: 15
            height: 15
            source: "image://icon/gear?color="
                    + encodeURIComponent(settingsMouse.containsMouse ? theme.primary : theme.textSub)
                    + "&size=15"
            sourceSize.width: 15
            sourceSize.height: 15
        }
        MouseArea {
            id: settingsMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.settingsClicked()
        }
    }

    // 删除按钮(仅已安装的版本显示): 平时隐藏, 悬停或选中时出现。
    // 可见性只看 hoverActive / selected —— 绝不能用会被按钮自己抢走的 hover。
    Item {
        id: deleteButton
        objectName: "deleteButton"
        visible: row.deletable && (row.hoverActive || row.selected)
        z: 10   // 必须盖在上面那个 MouseArea 之上, 否则点不到
        width: 26
        height: 26
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        opacity: visible ? 1.0 : 0.0
        Behavior on opacity {
            NumberAnimation { duration: 110 }
        }

        Rectangle {
            anchors.fill: parent
            radius: 4
            color: deleteMouse.containsMouse ? "#FCEFEF" : "transparent"
        }
        Image {
            anchors.centerIn: parent
            width: 15
            height: 15
            source: "image://icon/trash?color="
                    + encodeURIComponent(deleteMouse.containsMouse ? theme.danger : theme.textSub)
                    + "&size=15"
            sourceSize.width: 15
            sourceSize.height: 15
        }
        MouseArea {
            id: deleteMouse
            anchors.fill: parent
            // 这个 MouseArea 可以开 hover(用于图标变红): 行的 hover 走 HoverHandler,
            // 和 MouseArea 的 hover 互不干扰, 不会出现"按钮把行的 hover 抢走"。
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.deleteClicked()
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        // 行 hover 由上面的 HoverHandler 负责, 这里只处理点击
        hoverEnabled: false
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: (mouseEvent) => {
            if (mouseEvent.button === Qt.RightButton)
                row.settingsClicked();
            else
                row.clicked();
        }
        onDoubleClicked: row.doubleClicked()
    }
}
