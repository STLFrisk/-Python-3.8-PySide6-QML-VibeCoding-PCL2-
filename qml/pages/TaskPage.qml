import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 二级页面: 任务管理(下载 / 安装 / 导出整合包的进度)
// 由窗口右下角的圆形悬浮按钮打开, 不再用模态进度对话框挡住界面。
Item {
    id: page

    property var host: null

    component StatBlock: Column {
        id: block
        width: parent.width
        spacing: 6
        property string label: ""
        property string value: ""

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: block.label
            color: theme.primary
            font.pixelSize: 13
        }
        Rectangle {
            width: parent.width * 0.62
            height: 2
            radius: 1
            color: theme.primary
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: block.value
            color: theme.textTitle
            font.pixelSize: 22
        }
    }

    Row {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------- 左侧统计
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

            Column {
                x: 20
                y: 24
                width: parent.width - 40
                spacing: 30

                StatBlock {
                    label: "总进度"
                    value: backend.overallPercent.toFixed(2) + " %"
                }
                StatBlock {
                    label: "下载速度"
                    value: backend.speedText
                }
                StatBlock {
                    label: "剩余文件"
                    value: backend.remainingText
                }
            }
        }

        // ---------------------------------------------------- 右侧任务列表
        Item {
            width: parent.width - 200
            height: parent.height

            Item {
                id: header
                width: parent.width
                height: 44

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: backend.taskCount > 0 ? "共 " + backend.taskCount + " 个任务" : "暂无任务"
                    font.pixelSize: 12
                    color: theme.textSub
                }

                PclButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    visible: backend.hasRunningTask === false && backend.taskCount > 0
                    text: "清空已完成"
                    implicitHeight: 26
                    fontSize: 12
                    onClicked: backend.clearFinishedTasks()
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
                    x: 14
                    y: 4
                    width: scroll.availableWidth - 28
                    spacing: 10
                    bottomPadding: 16

                    Repeater {
                        model: backend.taskModel

                        Rectangle {
                            id: card
                            width: parent.width
                            height: cardBody.height + 26
                            radius: 8
                            color: theme.card
                            border.width: 1
                            border.color: model.state === "failed" ? theme.danger : theme.border

                            property var stepList: model.steps
                            property string stateText: model.stateText
                            property bool running: model.state === "running"
                            property bool finished: model.state !== "running"

                            Column {
                                id: cardBody
                                x: 14
                                y: 13
                                width: parent.width - 28
                                spacing: 7

                                Row {
                                    width: parent.width
                                    spacing: 8

                                    Text {
                                        id: cardTitle
                                        text: model.title
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: theme.textTitle
                                    }

                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: model.stateText + "   " + model.percent + "%"
                                        font.pixelSize: 11
                                        color: model.state === "failed" ? theme.danger
                                             : (model.state === "done" ? theme.success : theme.primary)
                                    }

                                    Item {
                                        width: Math.max(0, parent.width - cardTitle.width - 190)
                                        height: 1
                                    }

                                    PclButton {
                                        visible: card.running
                                        kind: "link"
                                        text: "取消"
                                        fontSize: 11
                                        implicitHeight: 20
                                        onClicked: backend.cancelTaskAt(index)
                                    }

                                    Image {
                                        visible: card.finished
                                        width: 13
                                        height: 13
                                        anchors.verticalCenter: parent.verticalCenter
                                        source: "image://icon/close?color="
                                                + encodeURIComponent(theme.textSub) + "&size=13"
                                        sourceSize.width: 13
                                        sourceSize.height: 13
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: backend.removeTaskAt(index)
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 4
                                    radius: 2
                                    color: "#E4EBF6"

                                    Rectangle {
                                        width: parent.width * Math.max(0, Math.min(1, model.percent / 100.0))
                                        height: parent.height
                                        radius: 2
                                        color: model.state === "failed" ? theme.danger : theme.primary
                                    }
                                }

                                Repeater {
                                    model: card.stepList

                                    Row {
                                        spacing: 8

                                        Image {
                                            width: 13
                                            height: 13
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: modelData.state === "done"
                                            source: "image://icon/check?color="
                                                    + encodeURIComponent(theme.primary) + "&size=13"
                                            sourceSize.width: 13
                                            sourceSize.height: 13
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: modelData.state !== "done"
                                            text: modelData.state === "running"
                                                  ? modelData.percent + "%" : "…"
                                            color: modelData.state === "running" ? theme.primary : theme.textHint
                                            font.pixelSize: 11
                                            width: 30
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.name
                                            font.pixelSize: 12
                                            color: modelData.state === "wait" ? theme.textHint : theme.text
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        visible: backend.taskCount === 0
                        width: parent.width
                        topPadding: 40
                        horizontalAlignment: Text.AlignHCenter
                        text: "暂无任务\n安装游戏版本或导出整合包时，会在这里显示进度"
                        color: theme.textHint
                        font.pixelSize: 12
                        lineHeight: 1.5
                    }
                }
            }
        }
    }
}
