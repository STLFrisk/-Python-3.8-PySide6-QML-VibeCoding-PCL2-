import QtQuick
import QtQuick.Controls.Basic
import "../components"

// 资源详情页: 层级完全由后端 community.detailGroups 决定
//   客户端大类 → 加载器种类 → 适配游戏版本 → 资源版本(文件)
//   服务端大类 → 适配游戏版本 → 核心分区(sectionLabel) → 资源版本
//   数据包: 客户端大类(顶部一条"查看其 Mod 版本"的跳转条) → 适配游戏版本 → 资源版本
//   整合包 / 资源包 / 光影包: 只有一个"没有加载器名"的组 → 适配游戏版本(不再多一层)
//
// 每一层都能点标题收起/展开(带动画); 折叠的**初始值**听后端给的 collapsed
// (两个大类并列时默认收起; 带跳转条的那一层必须默认展开, 否则入口就被藏起来了)。
// 跳转条只由最外面的大类携带(全页最多一条), 子组不再渲染它。
Item {
    id: page

    property var host: null
    // 动画时长跟随设置里的"动画速度"(原来这里直接写 mainWindow, 但本页被
    // Component.createObject 实例化时那个 id 取不到 → 统一走 host)
    readonly property real animScale: host ? Math.max(0.0, host.animationScale) : 1.0

    // 「转到 Modrinth」的目标地址: 详情项目 id + 分类(mod/datapack/modpack/resourcepack/shader)
    // —— Modrinth 的页面路径与分类名一一对应。取不到 id 时留空。
    readonly property string modrinthUrl: community.detailProjectId === ""
                                          ? "" : "https://modrinth.com/"
                                          + (community.detailKind !== "" ? community.detailKind
                                                                         : "mod")
                                          + "/" + community.detailProjectId

    // ================================================================ 筛选胶囊(C3)
    // 只过滤**已经拿到的** community.detailGroups: 不发任何新请求, 也不改后端数据,
    // 只是在前端按 加载器 / 适配版本 重建一份列表给 ListView。
    property string loaderFilter: "全部"
    property string versionFilter: "全部"
    property var loaderOptions: ["全部"]
    property var versionOptions: ["全部"]
    property var viewGroups: []
    property string lastDetailId: ""
    readonly property int maxVersionCapsules: 10

    // 组节点的浅拷贝: 只替换 children / versions / 计数, 原始数据一个字节都不动
    function copyGroup(src) {
        var out = {};
        for (var key in src)
            out[key] = src[key];
        return out;
    }

    // 组名 → 胶囊上的加载器名。后端把这一层写成 "客户端 · fabric · 正式版" /
    // "客户端 · fabric/quilt" / "通用 / 其它", 胶囊只显示中间那段加载器名(与 PCL2 一致)。
    function loaderLabelOf(name) {
        var text = String(name === undefined || name === null ? "" : name).trim();
        var parts = text.split(" · ");
        if (parts.length >= 3)
            return parts[1].trim();
        if (parts.length === 2)
            return parts[1].trim();
        return text;
    }

    function loaderMatches(name, label) {
        if (label === "全部")
            return true;
        return loaderLabelOf(name) === label;
    }

    function countIn(versions) {
        var total = 0;
        for (var i = 0; i < (versions ? versions.length : 0); i++)
            total += Number(versions[i].count) || 0;
        return total;
    }

    // 收集可选的加载器 / 适配版本(用**未过滤**的数据收集, 胶囊不会因为筛选而消失)
    function collectOptions() {
        var loaders = ["全部"];
        var versions = ["全部"];

        function add(list, value) {
            var text = String(value === undefined || value === null ? "" : value).trim();
            if (text !== "" && list.indexOf(text) < 0)
                list.push(text);
        }

        // depth: 0 = 最外面那一层(客户端 / 服务端 大类, 或整合包那种直接被交出来的扁平组)。
        // 加载器胶囊只从**大类里面的子组**收集: 数据包那一页的大类节点会被后端合并成
        // "loader = 客户端 + versions"(见 resources._as_category 的 force 分支), 它并不是
        // 加载器层; 若把它也收进胶囊, 选中它会把整页过滤空。
        function walk(nodes, depth) {
            for (var i = 0; i < (nodes ? nodes.length : 0); i++) {
                var node = nodes[i];
                if (!node)
                    continue;
                // 加载器层: 大类里面的子组, 有 versions 且 loader 非空
                if (depth > 0 && node.versions && node.loader !== undefined
                        && String(node.loader) !== "")
                    add(loaders, loaderLabelOf(node.loader));
                for (var j = 0; j < (node.versions ? node.versions.length : 0); j++) {
                    if (node.versions[j])
                        add(versions, node.versions[j].version);
                }
                // 服务端那一层本身就是"游戏版本"(只有 version, 没有 versions)
                if (node.version !== undefined && !node.versions)
                    add(versions, node.version);
                if (node.children)
                    walk(node.children, depth + 1);
            }
        }

        walk(community.detailGroups, 0);
        // 适配版本最多列前 10 个(后端已按版本号倒序), 与 PCL2 的 "…" 一致
        if (versions.length > page.maxVersionCapsules + 1)
            versions = versions.slice(0, page.maxVersionCapsules + 1);
        page.loaderOptions = loaders;
        page.versionOptions = versions;
    }

    function filterVersionNodes(list) {
        var out = [];
        for (var i = 0; i < (list ? list.length : 0); i++) {
            var node = list[i];
            if (!node)
                continue;
            if (page.versionFilter === "全部" || String(node.version) === page.versionFilter)
                out.push(node);
        }
        return out;
    }

    function buildGroups() {
        var wantLoader = page.loaderFilter;
        var wantVersion = page.versionFilter;
        var groups = community.detailGroups;
        var out = [];
        for (var i = 0; i < (groups ? groups.length : 0); i++) {
            var node = copyGroup(groups[i]);
            var kids = [];
            if (node.children && node.children.length > 0) {
                for (var j = 0; j < node.children.length; j++) {
                    var child = copyGroup(node.children[j]);
                    if (child.versions && child.versions.length > 0) {
                        // 加载器层 → 加载器与适配版本两个条件都要过
                        if (!loaderMatches(child.loader, wantLoader))
                            continue;
                        child.versions = filterVersionNodes(child.versions);
                        if (child.versions.length === 0)
                            continue;
                        child.count = countIn(child.versions);
                        child.versionCount = child.versions.length;
                    } else if (child.children && child.children.length > 0) {
                        // 服务端: 这一层是游戏版本 → 只按适配版本过滤
                        if (wantVersion !== "全部" && String(child.version) !== wantVersion)
                            continue;
                    } else if (wantLoader !== "全部" || wantVersion !== "全部") {
                        continue;
                    }
                    kids.push(child);
                }
                if (kids.length === 0)
                    continue;
                node.children = kids;
                node.count = 0;
                node.versionCount = 0;
                for (var k = 0; k < kids.length; k++) {
                    node.count += Number(kids[k].count) || 0;
                    node.versionCount += Number(kids[k].versionCount) || 0;
                }
            } else if (node.versions && node.versions.length > 0) {
                // 扁平组(整合包 / 资源包 / 数据包): loader 为空 → 只有"全部"能留住它
                if (wantLoader !== "全部")
                    continue;
                node.versions = filterVersionNodes(node.versions);
                if (node.versions.length === 0)
                    continue;
                node.count = countIn(node.versions);
                node.versionCount = node.versions.length;
            } else if (wantLoader !== "全部" || wantVersion !== "全部") {
                continue;
            }
            out.push(node);
        }
        return out;
    }

    function refreshGroups() {
        collectOptions();
        viewGroups = buildGroups();
    }

    function resetFilters() {
        loaderFilter = "全部";
        versionFilter = "全部";
    }

    // 后端详情数据变化(换项目 / 异步文件列表回来) → 胶囊与列表重建。
    // 换了项目就把筛选恢复成"全部", 免得新项目一进来就是空列表。
    Connections {
        target: community

        function onDetailChanged() {
            var pid = String(community.detailProjectId || "");
            if (pid !== page.lastDetailId) {
                page.lastDetailId = pid;
                page.resetFilters();
            }
            page.refreshGroups();
        }
    }

    onLoaderFilterChanged: viewGroups = buildGroups()
    onVersionFilterChanged: viewGroups = buildGroups()
    Component.onCompleted: refreshGroups()

    Column {
        anchors.fill: parent
        spacing: 0

        // 顶部: 资源名 + 下载目录 + 操作
        Rectangle {
            id: header
            width: parent.width
            height: 74
            color: theme.card

            Column {
                x: 16
                y: 10
                // 右侧一排三个按钮(转到 Modrinth / 复制名称 / 打开下载文件夹)要留够位置
                width: parent.width - 412
                spacing: 4

                Text {
                    width: parent.width
                    text: community.detailTitle
                    font.pixelSize: 14
                    font.bold: true
                    color: theme.textTitle
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: "下载会保存到：" + community.downloadFolder
                    font.pixelSize: 11
                    color: theme.textSub
                    elide: Text.ElideMiddle
                }
                Text {
                    width: parent.width
                    text: community.statusText
                    font.pixelSize: 11
                    color: theme.textHint
                    elide: Text.ElideRight
                }
            }

            // PCL2 详情页右上角那两个按钮: 转到 Modrinth / 复制名称(+ 原有的打开下载文件夹)
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                PclButton {
                    text: "转到 Modrinth"
                    iconName: "next"
                    implicitWidth: 132
                    implicitHeight: 30
                    // 没有 id 时(理论上不会发生)不做任何事, 免得打开一个坏地址
                    enabled: page.modrinthUrl !== ""
                    onClicked: Qt.openUrlExternally(page.modrinthUrl)
                }

                PclButton {
                    text: "复制名称"
                    implicitWidth: 96
                    implicitHeight: 30
                    // 复用后端已有的剪贴板接口(launcher.copyToClipboard, 复制成功会弹提示)
                    onClicked: backend.copyToClipboard(community.detailTitle)
                }

                PclButton {
                    text: "打开下载文件夹"
                    iconName: "folder"
                    implicitWidth: 148
                    implicitHeight: 30
                    onClicked: backend.openPath(community.downloadFolder)
                }
            }
        }

        Rectangle { width: parent.width; height: 1; color: theme.border }

        // ---------------------------------------------------------------- 筛选胶囊
        // PCL2 那排 "加载器: 全部 / fabric …" 与 "适配版本: 全部 / 26.3 / 26.2 …",
        // 点击即过滤当前详情列表(纯前端过滤, 见上面的 buildGroups)。
        Rectangle {
            id: capsuleBand
            width: parent.width
            height: capsuleColumn.implicitHeight + 14
            color: theme.sideBg

            Column {
                id: capsuleColumn
                x: 16
                y: 7
                width: parent.width - 32
                spacing: 6

                Row {
                    width: parent.width
                    spacing: 8

                    CapsuleLabel { text: "加载器" }

                    Flow {
                        width: parent.width - 66
                        spacing: 6

                        Repeater {
                            model: page.loaderOptions

                            Capsule {
                                label: modelData
                                selected: page.loaderFilter === modelData
                                onClicked: page.loaderFilter = modelData
                            }
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: 8

                    CapsuleLabel { text: "适配版本" }

                    Flow {
                        width: parent.width - 66
                        spacing: 6

                        Repeater {
                            model: page.versionOptions

                            Capsule {
                                label: modelData
                                selected: page.versionFilter === modelData
                                onClicked: page.versionFilter = modelData
                            }
                        }
                    }
                }
            }
        }

        Rectangle { width: parent.width; height: 1; color: theme.border }

        ListView {
            id: list
            width: parent.width
            height: parent.height - header.height - capsuleBand.height - 2
            clip: true
            model: page.viewGroups
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            spacing: 2

            delegate: Column {
                id: groupColumn
                width: list.width
                spacing: 0

                // 最外面这一层是"大类"(客户端 / 服务端)。
                // loader 字段存在但为空 = "扁平组"(整合包 / 资源包 / 光影包):
                //   它的标题栏不画, 内容恒展开 —— 否则用户没有任何展开入口, 整组不可达。
                // (数据包页不再是扁平组: 后端会强制包一层"客户端"大类, 跳转条挂在那上面。)
                property bool collapsed: modelData.collapsed !== undefined
                                         ? !!modelData.collapsed : true
                // "适配版本"(客户端)还是"核心"(服务端)
                property string groupLabel: modelData.label || "适配版本"
                // 没写 loader 字段的组(服务端子组)不是扁平组, 标题栏照画
                property bool flatGroup: modelData.loader !== undefined && modelData.loader === ""
                // 大类下面还有一层吗(客户端/服务端大类为 true)
                property bool hasChildren: !!(modelData.children && modelData.children.length > 0)

                // ============ 大类 / 加载器标题栏 ============
                Rectangle {
                    width: parent.width
                    height: groupColumn.flatGroup ? 0 : 38
                    visible: height > 0
                    color: theme.primarySoft

                    Row {
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8

                        Image {
                            width: 13
                            height: 13
                            anchors.verticalCenter: parent.verticalCenter
                            source: "image://icon/chevron_right?color="
                                    + encodeURIComponent(theme.primary) + "&size=13"
                            sourceSize.width: 13
                            sourceSize.height: 13
                            rotation: groupColumn.collapsed ? 0 : 90
                            Behavior on rotation {
                                NumberAnimation {
                                    duration: Math.round(160 * page.animScale)
                                    easing.type: Easing.OutCubic
                                }
                            }
                        }
                        Image {
                            width: 15
                            height: 15
                            anchors.verticalCenter: parent.verticalCenter
                            source: "image://icon/mod?color=" + encodeURIComponent(theme.primary)
                                    + "&size=15"
                            sourceSize.width: 15
                            sourceSize.height: 15
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.loader
                            font.pixelSize: 13
                            font.bold: true
                            color: theme.primary
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.versionCount + " 个" + (modelData.unit || "适配版本")
                                  + " · " + modelData.count + " 个文件"
                            font.pixelSize: 11
                            color: theme.textSub
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: groupColumn.collapsed = !groupColumn.collapsed
                    }
                }

                // ============ 大类内容(可折叠) ============
                Item {
                    id: groupBody
                    width: parent.width
                    clip: true
                    height: (groupColumn.collapsed && !groupColumn.flatGroup)
                            ? 0 : groupInner.implicitHeight
                    Behavior on height {
                        NumberAnimation {
                            duration: Math.round(190 * page.animScale)
                            easing.type: Easing.OutCubic
                        }
                    }

                    Column {
                        id: groupInner
                        width: parent.width

                        // ============ 跳转条(大类内容最上面, 展开第一眼就看到) ============
                        // 后端只会把 switchTo 挂在**最外面的大类**上(数据包页的"客户端"大类、
                        // Mods 页的"客户端"大类), 这里因此只会出现一条。
                        // 曾经后端还往第一个加载器子组上多挂了一份, 界面上就出现两条一模一样的
                        // "以下是该项目的「Mod」版本…" —— 子组那一份已经删掉了, 别再挂回去。
                        //
                        // 文案(B3'): 优先用后端随 switchTo 一起给的 switchText —— 整句话由后端
                        // 按"跳转条挂在哪个大类上"生成, 所以第一大类是「服务端」时(项目只有
                        // paper/spigot 这类服务端核心版本)也能说对。老数据没有 switchText 字段,
                        // 回退到下面那两句写死的文案(向后兼容, 逐字不变)。
                        Rectangle {
                            width: parent.width
                            height: modelData.switchTo ? 34 : 0
                            visible: height > 0
                            color: switchMouse.containsMouse ? theme.hover : theme.primarySoft

                            Text {
                                x: 30
                                anchors.verticalCenter: parent.verticalCenter
                                text: (modelData.switchText !== undefined
                                       && modelData.switchText !== null
                                       && String(modelData.switchText) !== "")
                                      ? String(modelData.switchText)
                                      : (modelData.switchTo === "mod"
                                         ? "以下是该项目的「数据包」版本，点击这里查看其「Mod」版本。"
                                         : "以下是该项目的「Mod」版本，点击这里查看其「数据包」版本。")
                                font.pixelSize: 11
                                color: theme.primary
                            }

                            MouseArea {
                                id: switchMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: community.jumpToKind(modelData.switchTo)
                            }
                        }

                        // ---------- 第三层: 加载器种类(大类 → 加载器 → 游戏版本 → 文件) ----------
                        Repeater {
                            model: groupColumn.hasChildren ? modelData.children : []

                            Column {
                                id: loaderRow
                                width: groupInner.width
                                spacing: 0

                                // 加载器这一层也默认收起(后端给了 collapsed 就听后端的)
                                property bool collapsed: modelData.collapsed !== undefined
                                                         ? !!modelData.collapsed : true
                                // 整合包那种"没有加载器名"的子组 → 不画标题栏, 恒展开
                                property bool flatGroup: modelData.loader !== undefined
                                                         && modelData.loader === ""
                                // 子组标题:
                                //   * 客户端大类的子组 = 加载器种类, loader 就是"客户端 · fabric",
                                //     直接显示;
                                //   * 服务端大类的子组 = **一个游戏版本**(后端给的结构是
                                //     "服务端 → 游戏版本 → 核心分区(sectionLabel) → 资源版本"),
                                //     它的 loader 只是大类名("服务端"), 版本号在 version 字段里。
                                // 以前这里只显示 loader, 于是服务端大类下面每个子组都长成
                                // 一模一样的"服务端 N 个文件", 完全看不出是哪个游戏版本
                                // (用户报的正是这个)。所以: 有 version 就拼上, 没有就保持原样。
                                readonly property string groupTitle: {
                                    var name = (modelData.loader !== undefined
                                                && modelData.loader !== null)
                                               ? String(modelData.loader) : "";
                                    var mc = (modelData.version !== undefined
                                              && modelData.version !== null)
                                             ? String(modelData.version) : "";
                                    return mc !== "" ? (name + " " + mc) : name;
                                }

                                Rectangle {
                                    width: parent.width
                                    height: loaderRow.flatGroup ? 0 : 34
                                    visible: height > 0
                                    color: theme.primarySoft

                                    Row {
                                        x: 30
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 8

                                        Image {
                                            width: 12
                                            height: 12
                                            anchors.verticalCenter: parent.verticalCenter
                                            source: "image://icon/chevron_right?color="
                                                    + encodeURIComponent(theme.primary)
                                                    + "&size=12"
                                            sourceSize.width: 12
                                            sourceSize.height: 12
                                            rotation: loaderRow.collapsed ? 0 : 90
                                            Behavior on rotation {
                                                NumberAnimation {
                                                    duration: Math.round(160 * page.animScale)
                                                    easing.type: Easing.OutCubic
                                                }
                                            }
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: loaderRow.groupTitle
                                            font.pixelSize: 12
                                            font.bold: true
                                            color: theme.primary
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            // 服务端这一层是"游戏版本"(没有"适配版本"这个数),
                                            // 那种情况下只报文件数, 免得写出一句"0 个适配版本"
                                            text: (modelData.versionCount || 0) > 0
                                                  ? ((modelData.versionCount || 0) + " 个"
                                                     + (modelData.unit || "适配版本") + " · "
                                                     + (modelData.count || 0) + " 个文件")
                                                  : ((modelData.count || 0) + " 个文件")
                                            font.pixelSize: 11
                                            color: theme.textSub
                                        }
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: loaderRow.collapsed = !loaderRow.collapsed
                                    }
                                }

                                Item {
                                    id: loaderBody
                                    width: parent.width
                                    clip: true
                                    height: (loaderRow.collapsed && !loaderRow.flatGroup)
                                            ? 0 : loaderInner.implicitHeight
                                    Behavior on height {
                                        NumberAnimation {
                                            duration: Math.round(190 * page.animScale)
                                            easing.type: Easing.OutCubic
                                        }
                                    }

                                    Column {
                                        id: loaderInner
                                        width: parent.width

                                        // 注意: 跳转条**不在这里**渲染。它只属于最外面的"客户端/服务端"
                                        // 大类, 由后端挂在那个大类上(挂在加载器子组上会让同一条提示
                                        // 出现两次, 用户明确否决过)。
                                        // ---------- 第四层: 适配游戏版本 ----------
                                        Repeater {
                                            model: modelData.versions || []

                                            VersionRow {
                                                width: loaderInner.width
                                                version: modelData
                                                group: groupColumn.modelData
                                            }
                                        }

                                        // 兜底: 万一这一层既没有 versions 也没有 files, 也不能白屏
                                        Repeater {
                                            model: (modelData.versions
                                                    && modelData.versions.length > 0)
                                                   ? [] : (modelData.files || [])

                                            FileRow {
                                                width: loaderInner.width
                                                row: modelData
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // ---------- 扁平组(整合包 / 资源包 / 数据包): 直接是游戏版本 ----------
                        Repeater {
                            model: groupColumn.hasChildren ? [] : (modelData.versions || [])

                            VersionRow {
                                width: groupInner.width
                                version: modelData
                                group: groupColumn.modelData
                            }
                        }

                        // 扁平组的兜底: 后端直接给了 files(没有 versions 层)
                        Repeater {
                            model: groupColumn.hasChildren ? [] : (modelData.files || [])

                            FileRow {
                                width: groupInner.width
                                row: modelData
                            }
                        }
                    }
                }
            }
        }
    }

    // ================================================================ 筛选胶囊的两个小件
    // 胶囊左边的固定宽度标签("加载器" / "适配版本")
    component CapsuleLabel: Text {
        width: 58
        anchors.verticalCenter: parent.verticalCenter
        font.pixelSize: 12
        color: theme.textSub
    }

    // 一个筛选胶囊: 选中时用主题主色高亮(与 PCL2 一致)
    component Capsule: Rectangle {
        id: capsule

        property string label: ""
        property bool selected: false
        signal clicked()

        width: capsuleText.implicitWidth + 22
        height: 22
        radius: 11
        color: capsule.selected ? theme.primary : theme.card
        border.width: 1
        border.color: capsule.selected ? theme.primary : theme.borderInput

        Text {
            id: capsuleText
            anchors.centerIn: parent
            text: capsule.label
            font.pixelSize: 11
            color: capsule.selected ? "white" : theme.text
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: capsule.clicked()
        }
    }

    // ================================================================ 一个"适配游戏版本"行
    // 展开后是该游戏版本下的资源版本(sectionLabel 分区标题 + 文件行)。
    component VersionRow: Column {
        id: versionRow

        // 这个游戏版本的数据(versions 数组里的那一项)
        property var version: null
        // 它所属的分组(取标题里的"适配版本 / 核心"用)
        property var group: null

        width: parent ? parent.width : 0
        spacing: 0

        // 第二级(适配版本 / 核心)也默认收起; 后端给了 collapsed 就听后端的
        property bool collapsed: version && version.collapsed !== undefined
                                 ? !!version.collapsed : true

        Rectangle {
            width: parent.width
            height: 30
            color: theme.sideBg

            Row {
                x: 30
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Image {
                    width: 11
                    height: 11
                    anchors.verticalCenter: parent.verticalCenter
                    source: "image://icon/chevron_right?color="
                            + encodeURIComponent(theme.textSub) + "&size=11"
                    sourceSize.width: 11
                    sourceSize.height: 11
                    rotation: versionRow.collapsed ? 0 : 90
                    Behavior on rotation {
                        NumberAnimation {
                            duration: Math.round(160 * page.animScale)
                            easing.type: Easing.OutCubic
                        }
                    }
                }
                Image {
                    width: 13
                    height: 13
                    anchors.verticalCenter: parent.verticalCenter
                    source: "image://icon/cube_grass?size=13"
                    sourceSize.width: 13
                    sourceSize.height: 13
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ((versionRow.group && versionRow.group.label) || "适配版本")
                          + " " + (versionRow.version ? versionRow.version.version : "")
                    font.pixelSize: 12
                    font.bold: true
                    color: theme.textTitle
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "(" + (versionRow.version ? versionRow.version.count : 0) + " 个文件)"
                    font.pixelSize: 11
                    color: theme.textHint
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: versionRow.collapsed = !versionRow.collapsed
            }
        }

        Item {
            width: parent.width
            clip: true
            height: versionRow.collapsed ? 0 : versionFiles.implicitHeight
            Behavior on height {
                NumberAnimation {
                    duration: Math.round(190 * page.animScale)
                    easing.type: Easing.OutCubic
                }
            }

            Column {
                id: versionFiles
                width: parent.width

                Repeater {
                    model: versionRow.version ? (versionRow.version.files || []) : []

                    FileRow {
                        width: versionFiles.width
                        row: modelData
                    }
                }
            }
        }
    }

    // ================================================================ 一个文件行
    // 分区标题行(sectionLabel)由后端插进来, 用来把"资源自身的快照版本"和正式版分开
    // —— 与游戏版本是不是快照无关。整行点一下就是开始下载(PCL2 也是这样, 没有单独按钮)。
    component FileRow: Rectangle {
        id: fileRow

        property var row: null

        height: (row && row.sectionLabel) ? 26 : 46
        color: (row && row.sectionLabel) ? theme.sideBg
             : (fileMouse.containsMouse ? theme.hover : "transparent")

        Text {
            visible: !!(row && row.sectionLabel)
            x: 44
            anchors.verticalCenter: parent.verticalCenter
            text: (row && row.sectionLabel) || ""
            font.pixelSize: 11
            font.bold: true
            color: theme.textSub
        }

        Column {
            x: 44
            anchors.verticalCenter: parent.verticalCenter
            visible: !(row && row.sectionLabel)
            // PCL2 的文件行没有右侧按钮: 整行就是"点一下开始下载", 文字铺满整行宽度。
            width: parent.width - 60
            spacing: 2

            Text {
                width: parent.width
                text: row ? (row.name + "   " + row.file) : ""
                font.pixelSize: 12
                color: fileMouse.containsMouse ? theme.primary : theme.text
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: row ? (row.size + "   " + row.date + "   " + row.loaders
                            + "   ↓ " + row.downloads) : ""
                font.pixelSize: 10
                color: theme.textHint
                elide: Text.ElideRight
            }
        }

        // 悬停时右侧出现一个轻轻的"下载"提示
        Text {
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            visible: !(row && row.sectionLabel) && fileMouse.containsMouse
            text: "下载"
            font.pixelSize: 11
            color: theme.primary
        }

        MouseArea {
            id: fileMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (row && !row.sectionLabel) community.downloadFile(row.index)
        }
    }
}
