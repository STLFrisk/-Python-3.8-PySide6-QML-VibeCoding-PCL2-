import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 二级页面: 启动日志(原独立窗口, 现在合并进主窗口)
Item {
    id: page

    property var host: null

    Column {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            width: parent.width
            height: 40
            color: theme.card

            Row {
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                PclButton {
                    text: "复制全部"
                    implicitWidth: 92
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: {
                        logText.selectAll();
                        logText.copy();
                        logText.deselect();
                        backend.toastRequested("日志已复制到剪贴板");
                    }
                }
                PclButton {
                    text: "清空"
                    implicitWidth: 72
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: backend.clearLog()
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: backend.launchState === "running" ? "游戏运行中…" : "游戏未运行"
                    font.pixelSize: 11
                    color: theme.textSub
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 1
            color: theme.border
        }

        Flickable {
            id: flick
            width: parent.width
            height: parent.height - 41
            contentWidth: width
            contentHeight: logText.contentHeight + 20
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            TextEdit {
                id: logText
                x: 12
                y: 10
                width: flick.width - 24
                readOnly: true
                selectByMouse: true
                text: backend.logLines.join("\n")
                font.family: "Consolas"
                font.pixelSize: 12
                color: theme.text
                wrapMode: TextEdit.WrapAnywhere
            }
        }
    }

    Connections {
        target: backend

        function onLogAppended(line) {
            logText.text = backend.logLines.join("\n");
        }
    }
}
