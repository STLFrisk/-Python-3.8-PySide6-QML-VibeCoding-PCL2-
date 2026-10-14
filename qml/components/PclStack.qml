import QtQuick
import QtQuick.Controls.Basic

// 带动画的分页容器(用于二级/三级菜单的标签切换)。
// 切换时: 新页面淡入并从右侧轻微滑入, 旧页面淡出并向左滑走。
StackView {
    id: control

    property int duration: 200
    property int slideDistance: 26

    replaceEnter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"; from: 0.0; to: 1.0
                duration: control.duration; easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "x"; from: control.slideDistance; to: 0
                duration: control.duration; easing.type: Easing.OutCubic
            }
        }
    }

    replaceExit: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"; from: 1.0; to: 0.0
                duration: Math.round(control.duration * 0.8); easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "x"; from: 0; to: -control.slideDistance
                duration: Math.round(control.duration * 0.8); easing.type: Easing.OutCubic
            }
        }
    }

    pushEnter: Transition {
        NumberAnimation {
            property: "x"; from: control.width; to: 0
            duration: control.duration; easing.type: Easing.OutCubic
        }
    }
    pushExit: Transition {
        NumberAnimation {
            property: "x"; from: 0; to: -control.slideDistance
            duration: control.duration; easing.type: Easing.OutCubic
        }
    }
    popEnter: Transition {
        NumberAnimation {
            property: "x"; from: -control.slideDistance; to: 0
            duration: control.duration; easing.type: Easing.OutCubic
        }
    }
    popExit: Transition {
        NumberAnimation {
            property: "x"; from: 0; to: control.width
            duration: control.duration; easing.type: Easing.OutCubic
        }
    }
}
