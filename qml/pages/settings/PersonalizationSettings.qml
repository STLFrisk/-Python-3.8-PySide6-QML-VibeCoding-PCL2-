import QtQuick
import QtQuick.Controls.Basic
import "../../components"

// 设置 - 个性化: 自定义启动器标题与主题色(实时应用到所有组件)
Item {
    id: page

    property var host: null

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
                title: "启动器标题"
                width: parent.width

                Text {
                    width: parent.width
                    text: "显示在窗口标题栏与任务栏上的名称，留空则恢复默认。"
                    font.pixelSize: 11
                    color: theme.textSub
                    wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    spacing: 10

                    PclTextField {
                        id: titleField
                        width: 240
                        placeholderText: theme.defaultAppTitle
                        text: settings.value("ui.app_title")
                        onEditingFinished: {
                            theme.setAppTitle(text);
                            settings.setValue("ui.app_title", theme.appTitle === theme.defaultAppTitle
                                              ? "" : theme.appTitle);
                        }
                    }
                    PclButton {
                        text: "应用"
                        implicitWidth: 84
                        implicitHeight: 28
                        onClicked: {
                            theme.setAppTitle(titleField.text);
                            settings.setValue("ui.app_title", theme.appTitle === theme.defaultAppTitle
                                              ? "" : theme.appTitle);
                        }
                    }
                    PclButton {
                        text: "恢复默认"
                        implicitWidth: 100
                        implicitHeight: 28
                        onClicked: {
                            titleField.text = "";
                            theme.setAppTitle("");
                            settings.setValue("ui.app_title", "");
                        }
                    }
                }
            }

            Card {
                title: "主题颜色"
                width: parent.width

                Text {
                    width: parent.width
                    text: "选择一个预设颜色，或自定义任意颜色。修改后立即应用到标题栏、按钮、选中状态等所有组件。"
                    font.pixelSize: 11
                    color: theme.textSub
                    wrapMode: Text.WordWrap
                }

                Flow {
                    width: parent.width
                    spacing: 10

                    Repeater {
                        model: theme.presets

                        Rectangle {
                            width: 42
                            height: 42
                            radius: 21
                            color: modelData.color
                            border.width: theme.primary.toLowerCase() === modelData.color.toLowerCase() ? 3 : 1
                            border.color: theme.primary.toLowerCase() === modelData.color.toLowerCase()
                                          ? theme.textTitle : theme.borderInput

                            ToolTip.visible: mouse.containsMouse
                            ToolTip.text: modelData.name
                            ToolTip.delay: 400

                            Image {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                visible: theme.primary.toLowerCase() === modelData.color.toLowerCase()
                                source: "image://icon/check?color=%23FFFFFF&size=18"
                                sourceSize.width: 18
                                sourceSize.height: 18
                            }

                            MouseArea {
                                id: mouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: theme.setPrimary(modelData.color)
                            }
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: 10

                    PclButton {
                        text: "自定义颜色…"
                        iconName: "palette"
                        implicitWidth: 140
                        implicitHeight: 30
                        onClicked: {
                            picker.currentColor = theme.primary;
                            picker.open();
                        }
                    }
                    PclButton {
                        text: "恢复默认"
                        implicitWidth: 110
                        implicitHeight: 30
                        onClicked: theme.resetPrimary()
                    }
                    Rectangle {
                        width: 30
                        height: 30
                        radius: 6
                        color: theme.primary
                        border.width: 1
                        border.color: theme.borderInput
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: theme.primary.toUpperCase()
                        font.pixelSize: 12
                        color: theme.textSub
                    }
                }
            }

            Card {
                title: "预览"
                width: parent.width

                Row {
                    width: parent.width
                    spacing: 12

                    Rectangle {
                        width: 150
                        height: 34
                        radius: 4
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: theme.titleTop }
                            GradientStop { position: 1.0; color: theme.titleBottom }
                        }
                        Text {
                            anchors.centerIn: parent
                            text: theme.appTitle
                            color: "white"
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            width: parent.width - 16
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }

                    PclButton {
                        kind: "primary"
                        text: "主要按钮"
                        implicitWidth: 110
                        implicitHeight: 34
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    PclButton {
                        text: "次要按钮"
                        implicitWidth: 110
                        implicitHeight: 34
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Rectangle {
                        width: 110
                        height: 34
                        radius: 3
                        color: theme.selected
                        border.width: 1
                        border.color: theme.primary
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            anchors.centerIn: parent
                            text: "选中状态"
                            color: theme.primary
                            font.pixelSize: 12
                        }
                    }
                }
            }

            Card {
                title: "任务悬浮按钮"
                width: parent.width

                PclCheckBox {
                    text: "在窗口右下角显示圆形任务按钮"
                    checked: settings.flag("ui.show_task_button")
                    onClicked: settings.setValue("ui.show_task_button", checked)
                }

                Text {
                    width: parent.width
                    text: "下载 / 安装 / 导出整合包时会自动显示，点一下即可打开「任务管理」页面。"
                    font.pixelSize: 11
                    color: theme.textHint
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    ColorPickerDialog {
        id: picker
        currentColor: theme.primary
        onColorAccepted: (value) => theme.setPrimary(value.toString())
    }
}
