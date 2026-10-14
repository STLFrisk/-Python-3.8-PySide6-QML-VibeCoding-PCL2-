import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 四级页面: 选择某个加载器的具体版本
Item {
    id: page

    property var host: null
    property string loaderKey: ""
    property string loaderName: ""
    property string mcVersion: ""
    property var versions: []
    property int currentIndex: 0

    function load() {
        versions = [];
        currentIndex = 0;
        var rows = download.loaderRows;
        for (var i = 0; i < rows.length; i++) {
            if (String(rows[i].key) === String(loaderKey)) {
                versions = rows[i].versions || [];
                currentIndex = Number(rows[i].index || 0);
            }
        }
    }

    Component.onCompleted: load()

    Column {
        anchors.fill: parent
        spacing: 0

        Item {
            width: parent.width
            height: 46

            Text {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                text: loaderName + " 版本（" + versions.length + " 个）"
                font.pixelSize: 12
                color: theme.textSub
            }
        }

        Rectangle { width: parent.width; height: 1; color: theme.border }

        ListView {
            id: list
            width: parent.width
            height: parent.height - 47
            clip: true
            model: page.versions
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                width: list.width
                height: 42
                color: (index === page.currentIndex) ? theme.selected
                     : (itemMouse.containsMouse ? theme.hover : "transparent")

                Text {
                    x: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData
                    font.pixelSize: 12
                    color: theme.text
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    visible: index === page.currentIndex
                    text: "当前"
                    font.pixelSize: 11
                    color: theme.primary
                }
                MouseArea {
                    id: itemMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        download.setLoaderVersion(page.loaderKey, index);
                        if (page.host)
                            page.host.popPage();
                    }
                }
            }
        }
    }
}
