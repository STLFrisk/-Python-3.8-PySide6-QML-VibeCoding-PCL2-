import QtQuick
import FluentUI

// 可折叠卡片(手风琴) —— 兼容层。
//
// 对外接口与旧的自绘版**逐字一致**: title / count / expanded / bodySpacing /
// showCount / 默认内容别名, 所以 8 处调用页面(下载页 4、版本选择页 4、设置页 3、
// 版本设置页 2)一行都不用改。内部换成 FluentUI 的 FluExpander:
// 45px 标题栏 + 悬停变色的 chevron 按钮 + 167ms 滑动展开, 与内容区其它组件同一套语言。
//
// 默认收起/展开语义不变:
//   * 调用页写的 `expanded: true/false` 就是初值 —— expand: root.expanded 是绑定,
//     不会被 FluExpander 自己的 expand 默认值(false)覆盖, 也不会先展开再收起;
//   * 用户点击标题栏/chevron 之后 FluExpander 会自己写 expand, 这里回写到 root.expanded;
//   * 外部改 root.expanded 时再同步回 FluExpander(赋值会顶掉绑定, 所以两个方向都要接)。
Item {
    id: root

    property string title: ""
    property int count: -1
    property bool expanded: true
    // 旧自绘实现的属性, 页面里没有地方读它; 保留以维持对外接口
    property int bodySpacing: 0
    property bool showCount: count >= 0
    default property alias content: bodyColumn.data

    implicitWidth: 200
    implicitHeight: expander.implicitHeight

    FluExpander {
        id: expander

        width: parent.width
        // FluExpander 的标题只有一个字符串入口 → 标题与 "(N)" 拼在同一行同一位置
        headerText: root.showCount ? (root.title + "  (" + root.count + ")") : root.title
        // 内容高度必须显式给: FluExpander 默认 300 会把长列表裁掉。
        // 末尾留 10px, 与旧自绘版(holder 高度 = 内容 + 10)一致。
        contentHeight: bodyColumn.implicitHeight + 10
        expand: root.expanded

        onExpandChanged: {
            if (root.expanded !== expand)
                root.expanded = expand;
        }

        Column {
            id: bodyColumn
            width: parent.width
            spacing: 0
        }
    }

    onExpandedChanged: {
        if (expander.expand !== expanded)
            expander.expand = expanded;
    }
}
