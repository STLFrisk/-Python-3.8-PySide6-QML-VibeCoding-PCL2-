import QtQuick
import QtQuick.Window

// 无边框窗口的边缘拖拽缩放
Item {
    id: resizer

    property Window target: null
    property int edge: 4

    anchors.fill: parent
    z: 5000

    MouseArea {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: resizer.edge
        cursorShape: Qt.SizeHorCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.LeftEdge)
    }
    MouseArea {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: resizer.edge
        cursorShape: Qt.SizeHorCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.RightEdge)
    }
    MouseArea {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: resizer.edge
        cursorShape: Qt.SizeVerCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.TopEdge)
    }
    MouseArea {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: resizer.edge
        cursorShape: Qt.SizeVerCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.BottomEdge)
    }

    MouseArea {
        anchors.left: parent.left
        anchors.top: parent.top
        width: resizer.edge + 2
        height: resizer.edge + 2
        cursorShape: Qt.SizeFDiagCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.LeftEdge | Qt.TopEdge)
    }
    MouseArea {
        anchors.right: parent.right
        anchors.top: parent.top
        width: resizer.edge + 2
        height: resizer.edge + 2
        cursorShape: Qt.SizeBDiagCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.RightEdge | Qt.TopEdge)
    }
    MouseArea {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: resizer.edge + 2
        height: resizer.edge + 2
        cursorShape: Qt.SizeBDiagCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.LeftEdge | Qt.BottomEdge)
    }
    MouseArea {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: resizer.edge + 2
        height: resizer.edge + 2
        cursorShape: Qt.SizeFDiagCursor
        onPressed: if (resizer.target) resizer.target.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
    }
}
