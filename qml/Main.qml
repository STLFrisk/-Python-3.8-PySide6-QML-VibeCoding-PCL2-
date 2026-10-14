import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import FluentUI
import "components"
import "pages"

// 所有菜单(一级 / 二级 / 三级)都在这一个窗口内切换, 带过渡动画。
Window {
    id: mainWindow

    visible: true
    width: 960
    height: 640
    minimumWidth: 860
    minimumHeight: 540
    title: theme.appTitle
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    property int rootIndex: 0                 // 当前一级页面
    property string pageTitle: theme.appTitle // 二级页面标题
    property string lastDownloadPath: ""      // 最近一次资源下载的落盘路径
    property bool subPage: false              // 是否处于二级页面
    property real animationScale: 1.0
    readonly property int animDuration: Math.max(0, Math.round(240 * animationScale))
    readonly property bool maximized: visibility === Window.Maximized

    property int pendingRoot: -1
    property int pendingSection: -1

    // ---------------------------------------------------------------- 启动 / 关闭动画
    // 启动: 窗口从全透明淡入(在"常规运行"之前先播完这段)。
    // 关闭: 先淡出, 播完再真正退出 —— 所以关闭信号要先拦下来。
    property bool closing: false
    opacity: 0
    NumberAnimation on opacity {
        from: 0
        to: 1
        duration: Math.max(1, Math.round(260 * mainWindow.animationScale))
        easing.type: Easing.OutCubic
    }
    NumberAnimation {
        id: closeAnimation
        target: mainWindow
        property: "opacity"
        to: 0
        duration: Math.max(1, Math.round(180 * mainWindow.animationScale))
        easing.type: Easing.InCubic
        onFinished: Qt.quit()
    }
    onClosing: function (close) {
        if (mainWindow.closing) {
            return;                 // 动画已经在播了, 别重复触发
        }
        close.accepted = false;     // 先别退, 等淡出播完
        mainWindow.closing = true;
        closeAnimation.start();
    }
    property string filePurpose: ""
    property var filePayload: null
    // 本地整合包导入(.mrpack): 选完文件后要先问版本名, 确认之前不开始安装(B1')
    property string pendingModpackPath: ""
    property string pendingModpackName: ""   // 对话框的默认版本名(已按后端规则避让重名)

    // ================================================================ 页面组件
    Component { id: homeComponent; HomePage { host: mainWindow } }
    Component { id: downloadComponent; DownloadPage { host: mainWindow } }
    Component { id: settingsComponent; SettingsPage { host: mainWindow } }
    Component { id: versionSelectComponent; VersionSelectPage { host: mainWindow } }
    Component { id: versionSettingsComponent; VersionSettingsPage { host: mainWindow } }
    Component { id: logComponent; LogPage { host: mainWindow } }
    Component { id: taskComponent; TaskPage { host: mainWindow } }
    Component { id: installVersionComponent; InstallVersionPage { host: mainWindow } }
    Component { id: loaderVersionComponent; LoaderVersionPage { host: mainWindow } }
    Component { id: resourceDetailComponent; ResourceDetailPage { host: mainWindow } }

    readonly property var rootComponents: [homeComponent, downloadComponent, settingsComponent]

    // ================================================================ 导航
    function applyRoot(index) {
        if (index < 0 || index >= rootComponents.length)
            return;
        rootIndex = index;
        rootStack.replace(rootStack.get(0), rootComponents[index]);
    }

    function goRoot(index) {
        if (rootStack.depth > 1) {
            pendingRoot = index;
            rootStack.pop(rootStack.get(0));
            return;
        }
        if (rootIndex === index)
            return;
        applyRoot(index);
    }

    function pushPage(component, pageName) {
        pageTitle = pageName;
        rootStack.push(component);
    }

    function popPage() {
        if (rootStack.depth > 1)
            rootStack.pop();
    }

    function openVersionSelect() {
        if (subPage && pageTitle === "版本选择")
            return;
        // 每次进入都重新检索一遍当前文件夹里的版本(强制, 不做节流)
        backend.refreshVersions();
        pushPage(versionSelectComponent, "版本选择");
    }

    // 三级页面: 安装某个版本时选择模组加载器
    function openInstallVersion(mcVersion) {
        var vid = String(mcVersion || "").trim();
        if (vid === "") {
            backend.toastRequested("请先选择要安装的版本");
            return;
        }
        var item = installVersionComponent.createObject(mainWindow,
                                                       {"host": mainWindow, "mcVersion": vid});
        if (item)
            pushPage(item, "安装 " + vid);
    }

    // 三级页面: 社区资源详情(文件按 加载器 → 适配版本 分组)
    function openResourceDetail(projectId, title, icon) {
        community.openProjectById(String(projectId || ""), String(title || ""), String(icon || ""));
        var item = resourceDetailComponent.createObject(mainWindow, {"host": mainWindow});
        if (item)
            pushPage(item, String(title || community.detailTitle || "资源详情"));
    }

    // 四级页面: 选某个加载器的具体版本
    function openLoaderVersions(loaderKey, loaderName) {
        var item = loaderVersionComponent.createObject(mainWindow, {
            "host": mainWindow,
            "loaderKey": String(loaderKey || ""),
            "loaderName": String(loaderName || ""),
            "mcVersion": download.loaderVersion
        });
        if (item)
            pushPage(item, String(loaderName || "加载器") + " 版本");
    }

    function openVersionSettings() {
        var vid = backend.selectedVersionId;
        if (!vid) {
            backend.messageRequested("无法打开版本设置", "请先在「版本选择」里选择一个游戏版本。", "warn");
            return;
        }        backend.selectVersion(vid);
        versionSettings.load(vid);
        pushPage(versionSettingsComponent, "版本设置");
    }

    function openLog() {
        pushPage(logComponent, "启动日志");
    }

    function openTasks() {
        if (subPage && pageTitle === "任务管理") {
            popPage();
            return;
        }
        pushPage(taskComponent, "任务管理");
    }

    function showVersionSettingsSection(index) {
        if (!subPage || pageTitle !== "版本设置")
            openVersionSettings();
        if (rootStack.currentItem && rootStack.currentItem.showSection)
            rootStack.currentItem.showSection(index);
    }

    function showSettingsSection(index) {
        if (rootStack.depth > 1) {
            pendingRoot = 2;
            pendingSection = index;
            rootStack.pop(rootStack.get(0));
            return;
        }
        if (rootIndex !== 2)
            applyRoot(2);
        if (rootStack.currentItem && rootStack.currentItem.showSection)
            rootStack.currentItem.showSection(index);
    }

    function syncAnimationScale() {
        // settings 是运行时注入的 context property: 求值早于注入、以及关窗销毁
        // 阶段(QML 仍会对存活的绑定再求值一次)时它是 null, 直接取 .value 会抛
        // "Cannot call method 'value' of null"。这里做空安全, 取不到就用默认 1.0。
        if (typeof settings === "undefined" || settings === null
                || typeof settings.value !== "function") {
            mainWindow.animationScale = 1.0;
            return;
        }
        var value = Number(settings.value("ui.animation_speed"));
        if (isNaN(value))
            value = 1.0;
        mainWindow.animationScale = Math.max(0.0, value);
    }

    Component.onCompleted: {
        syncAnimationScale()
        // 内容区统一用 FluentUI 的设计语言(与 PCL2 观感最接近), 主色跟随本启动器主题。
        // 外壳(窗口/标题栏/圆角)仍是自绘的 PCL2 风格, 不参与 FluentUI。
        FluTheme.primaryColor = theme.primary
    }

    // ================================================================ 界面
    WindowFrame {
        id: frame
        targetWindow: mainWindow
        onMaximizedChanged: theme.setMaximized(maximized)

        Column {
            anchors.fill: parent
            spacing: 0

            TitleBar {
                id: titleBar
                width: parent.width
                targetWindow: mainWindow
                title: mainWindow.subPage ? mainWindow.pageTitle : theme.appTitle
                showBack: mainWindow.subPage
                // 二级页面(版本选择/版本设置/日志/任务管理)隐藏顶部主菜单
                showNav: !mainWindow.subPage
                animationScale: mainWindow.animationScale
                navIndex: mainWindow.rootIndex
                navLabels: ["启动", "下载", "设置"]
                navIcons: ["play", "download", "gear"]
                onNavClicked: (index) => mainWindow.goRoot(index)
                onBackClicked: mainWindow.popPage()
                onMinimizeClicked: mainWindow.showMinimized()
                onMaximizeClicked: {
                    if (mainWindow.maximized)
                        mainWindow.showNormal();
                    else
                        mainWindow.showMaximized();
                }
                onCloseClicked: mainWindow.close()
            }

            // 一级 / 二级页面容器(带动画)
            StackView {
                id: rootStack
                width: parent.width
                height: parent.height - titleBar.height
                initialItem: homeComponent
                onDepthChanged: mainWindow.subPage = depth > 1

                pushEnter: Transition {
                    NumberAnimation {
                        property: "x"; from: rootStack.width; to: 0
                        duration: mainWindow.animDuration; easing.type: Easing.OutCubic
                    }
                    // 进入的页面必须显式恢复不透明度: 它上次可能是"退出页"被淡出成 0 了,
                    // 不恢复就会出现"页面看不见但还能点到"的怪现象
                    NumberAnimation { property: "opacity"; from: 1.0; to: 1.0; duration: 1 }
                }
                pushExit: Transition {
                    NumberAnimation {
                        property: "x"; from: 0; to: -rootStack.width * 0.18
                        duration: mainWindow.animDuration; easing.type: Easing.OutCubic
                    }
                    // 让退出的页面尽快淡出, 否则动画期间会看到前后两页内容重叠
                    NumberAnimation {
                        property: "opacity"; from: 1.0; to: 0.0
                        duration: 1        // 立刻隐藏退出页, 避免过渡期间新旧两页重叠
                    }
                }
                popEnter: Transition {
                    NumberAnimation {
                        property: "x"; from: -rootStack.width * 0.18; to: 0
                        duration: mainWindow.animDuration; easing.type: Easing.OutCubic
                    }
                    NumberAnimation { property: "opacity"; from: 1.0; to: 1.0; duration: 1 }
                }
                popExit: Transition {
                    NumberAnimation {
                        property: "x"; from: 0; to: rootStack.width
                        duration: mainWindow.animDuration; easing.type: Easing.OutCubic
                    }
                    NumberAnimation {
                        property: "opacity"; from: 1.0; to: 0.0
                        duration: 1        // 立刻隐藏退出页, 避免过渡期间新旧两页重叠
                    }
                }
                replaceEnter: Transition {
                    // 只做纵向滑入: 不再让两页同时半透明(那会造成内容重叠)
                    NumberAnimation {
                        property: "y"; from: 16; to: 0
                        duration: mainWindow.animDuration; easing.type: Easing.OutCubic
                    }
                }
                replaceExit: Transition {
                    NumberAnimation {
                        property: "opacity"; from: 1.0; to: 0.0
                        duration: 1        // 立刻隐藏退出页, 避免过渡期间新旧两页重叠
                    }
                }
            }
        }
    }

    WindowResizer {
        target: mainWindow
    }

    // ================================================================ 右下角圆形任务按钮(置顶)
    Item {
        id: taskFab

        // visible: 有任务时显示; 任务全部结束后等 5 秒再淡出(淡出 400ms)
        property bool running: backend.hasRunningTask
        property bool fading: false
        // settings 是运行时注入的 context property: 求值早于注入时会抛
        // "Cannot call method 'flag' of null" 并把按钮**永久卡成隐藏**, 所以这里做空安全。
        // (关窗销毁阶段同样会变 null, 此时按"显示"处理即可 —— 窗口已经在退出。)
        readonly property bool showButton: (typeof settings === "undefined" || settings === null
                                           || typeof settings.flag !== "function")
                                           ? true : settings.flag("ui.show_task_button")

        width: 56
        height: 56
        z: 900
        visible: opacity > 0.01 && showButton
        opacity: (backend.taskCount > 0 || fading) ? 1 : 0
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 22
        anchors.bottomMargin: 22

        onRunningChanged: {
            if (running) {
                taskFab.fading = false;
                taskFab.opacity = 1;
                taskHideTimer.stop();
            } else if (backend.taskCount > 0) {
                taskHideTimer.restart();
            }
        }

        Timer {
            id: taskHideTimer
            interval: 5000
            onTriggered: {
                taskFab.fading = true;
                fadeOut.start();
            }
        }

        NumberAnimation {
            id: fadeOut
            target: taskFab
            property: "opacity"
            to: 0
            duration: 400        // 消失动画不超过 500ms
            easing.type: Easing.OutCubic
            onFinished: {
                taskFab.fading = false;
                backend.clearFinishedTasks();
            }
        }

        Behavior on opacity {
            enabled: !fadeOut.running
            NumberAnimation { duration: 150 }
        }

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: backend.hasRunningTask ? theme.primary : theme.success
            border.width: 2
            border.color: "#FFFFFF"

            Behavior on color {
                ColorAnimation { duration: 200 }
            }
        }

        // 进度环: FluentUI 的 FluProgressRing(不再自绘 Canvas)
        // 49x49 居中 → 弧线中心半径 = 49/2 - 3/2 = 23, 与原自绘环(r = 56/2 - 5 = 23,
        // lineWidth 3)逐像素对齐; 两层白色沿用原来的 35% / 95%。
        // 百分比文字仍由下面的 Text 自己画(任务结束后要显示 ✓, 不是数字)。
        FluProgressRing {
            id: ring
            anchors.centerIn: parent
            width: 49
            height: 49
            indeterminate: false
            strokeWidth: 3
            value: Math.max(0, Math.min(1, backend.overallPercent / 100.0))
            color: Qt.rgba(1, 1, 1, 0.95)
            backgroundColor: Qt.rgba(1, 1, 1, 0.35)
            progressVisible: false
        }

        Text {
            anchors.centerIn: parent
            text: backend.hasRunningTask ? backend.overallPercent + "%" : "✓"
            color: "white"
            font.pixelSize: backend.hasRunningTask ? 12 : 20
            font.bold: true
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: mainWindow.openTasks()
        }

        Connections {
            target: backend

            // 注意: FluProgressRing 是 ProgressBar, 没有 Canvas.requestPaint()。
            // 进度由上面的 value 绑定自动跟随 backend.overallPercent, 这里不用再管。

            // 版本被删除(可能在「版本设置」里删的): 退回主页面, 别停在已删除版本的页面上
            function onVersionDeleted(versionId) {
                mainWindow.goRoot(0);
            }

            // 资源下载完成: 告诉用户存到哪了, 并提供"打开文件夹 / 复制路径"
            function onResourceDownloaded(message, path) {
                mainWindow.lastDownloadPath = path;
                messageDialog.title = "下载完成";
                messageDialog.kind = "success";
                messageDialog.cancelText = "打开文件夹";
                messageDialog.showCancel = path !== "";
                messageDialog.text = message
                        + "\n\n文件路径已经自动复制到剪贴板，可以直接粘贴使用。"
                        + (path !== "" ? "\n也可以点「打开文件夹」直接定位到它。" : "");
                messageDialog.open();
            }
        }
    }

    // ================================================================ 提示 / 确认
    PclDialog {
        id: messageDialog

        // 下载完成后「打开文件夹」用(取消按钮被复用成这个动作)
        onRejected: if (mainWindow.lastDownloadPath !== "")
                        backend.openPath(mainWindow.lastDownloadPath)
    }

    PclDialog {
        id: confirmDialog
        showCancel: true
        onAccepted: backend.confirmPendingYes()
        onRejected: backend.confirmPendingNo()
    }

    // 整合包的命名确认: 两条来源共用这一个对话框 ——
    //   ① 本地文件导入(.mrpack, B1')
    //   ② 社区资源页点「下载」整合包(后端 modpackNameRequested 信号)
    // 与 InstallVersionPage 的 renameDialog 同款 —— 默认名只在 onOpened(打开完成)
    // 时填, 校验失败重开时保留用户输入与红字。两条来源的差别只在"确认之后走哪条安装路径"。
    PclDialog {
        id: modpackDialog
        showCancel: true
        okText: "开始安装"
        inputVisible: true
        inputPlaceholder: "整合包版本名"

        onOpened: {
            if (inputError === "")
                inputText = mainWindow.pendingModpackName;
        }
        // 取消: 两条来源都**不安装**(本地导入清路径; 资源页丢掉后端那份待装快照)
        onRejected: {
            mainWindow.pendingModpackPath = "";
            modpackRequest.fromResource = false;
            community.cancelPendingModpack();
        }
        onAccepted: mainWindow.confirmModpackName()
    }

    // 这次命名请求是"资源页点下载整合包"发起的(不是本地文件导入)。非可视对象,
    // 就放在对话框旁边: 窗口外壳(标题栏/圆角/拖拽/按钮)一行都不动。
    QtObject {
        id: modpackRequest
        property bool fromResource: false
    }

    // 资源页点「下载」整合包 → 后端**先不开任务**, 只把默认版本名报上来
    // (已经按安装时同一套规则避让过重名, 所以可能是 xxx-2, 用户看得见也改得动);
    // 用户确认之后才 community.installPendingModpack(名字)。
    Connections {
        target: community
        function onModpackNameRequested(defaultName) {
            mainWindow.askResourceModpackName(defaultName);
        }
    }


    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: toastText.implicitWidth + 32
        height: 34
        radius: 17
        color: "#2B3A4D"
        opacity: 0
        visible: opacity > 0
        z: 100

        Text {
            id: toastText
            anchors.centerIn: parent
            color: "white"
            font.pixelSize: 12
        }

        Behavior on opacity {
            NumberAnimation { duration: 160 }
        }

        Timer {
            id: toastTimer
            interval: 2200
            onTriggered: toast.opacity = 0
        }

        function show(text) {
            toastText.text = text;
            toast.opacity = 1;
            toastTimer.restart();
        }
    }

    // ================================================================ 文件 / 文件夹选择
    FolderDialog {
        id: folderDialog
        onAccepted: {
            var path = mainWindow.toLocalPath(selectedFolder);
            if (mainWindow.filePurpose === "add_folder")
                backend.addFolderPath(path);
            else if (mainWindow.filePurpose === "create_mc")
                backend.createMinecraftFolderAt(path);
            mainWindow.filePurpose = "";
        }
    }

    FileDialog {
        id: fileDialog
        onAccepted: {
            var path = mainWindow.toLocalPath(selectedFile);
            var purpose = mainWindow.filePurpose;
            mainWindow.filePurpose = "";
            if (purpose === "import_pack")
                backend.importPackPath(path);
            else if (purpose === "install_mod")
                backend.installModFromPath(path);
            else if (purpose === "export_pack")
                backend.startExport(mainWindow.filePayload, path);
            else if (purpose === "settings_import")
                settings.importSettings(path);
            else if (purpose === "settings_export")
                settings.exportSettings(path);
            else if (purpose === "skin_file")
                settings.setValue("skin.path", path);
            else if (purpose === "java_file")
                settings.setValue("launch.java_path", path);
            else if (purpose === "modpack_file") {
                // 开框**之前**先问后端"这到底是不是整合包"(core.resources.is_modpack_file):
                // 只有真整合包才弹命名框; 普通 .zip/.jar(对话框里有"所有文件", 很容易选到)
                // 不弹框, 直接走后端既有逻辑 —— installLocalModpack 会把它按普通资源
                // 放进 Download/<类型>, 并给一条明确的提示。
                if (community.isModpackFile(path))
                    mainWindow.askModpackName(path);
                else
                    community.installLocalModpack(path, "");
            }
        }
    }

    // ================================================================ 对外接口(供页面/脚本调用)
    function setPage(index) {
        mainWindow.goRoot(index);
    }

    // 打开下载页并切到某个分类原版游戏 / Mod / 整合包 / 数据包 / 资源包 / 光影包
    function openDownloadSection(key) {
        goRoot(1);
        var item = rootStack.currentItem;
        if (item && item.openSection)
            item.openSection(key);
    }

    function askAddFolder() {
        mainWindow.filePurpose = "add_folder";
        folderDialog.title = "添加已有的 .minecraft 文件夹";
        folderDialog.open();
    }

    function askCreateFolder() {
        mainWindow.filePurpose = "create_mc";
        folderDialog.title = "选择要新建 .minecraft 的父文件夹";
        folderDialog.open();
    }

    function askImportPack() {
        mainWindow.filePurpose = "import_pack";
        fileDialog.title = "选择整合包 (.zip)";
        fileDialog.nameFilters = ["整合包 (*.zip)", "所有文件 (*)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    function askModpackFile() {
        mainWindow.filePurpose = "modpack_file";
        fileDialog.title = "选择要安装的整合包 (.mrpack / .zip)";
        fileDialog.nameFilters = ["Modrinth 整合包 (*.mrpack)", "整合包 (*.zip)", "所有文件 (*)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    // ---------------------------------------------------------------- 本地整合包导入(B1')
    // 选完 .mrpack 文件后先弹命名对话框(与 InstallVersionPage 的 renameDialog 完全同一套
    // PclDialog 机制): 默认名先就位, 用户点「确定」之后才真正开始安装。
    function modpackDefaultName(path) {
        // 后端 install_modpack 在没有给出名字时的兜底就是"文件主名", 这里取同一个值。
        var text = String(path || "");
        var cut = Math.max(text.lastIndexOf("/"), text.lastIndexOf("\\"));
        if (cut >= 0)
            text = text.substring(cut + 1);
        var dot = text.lastIndexOf(".");
        if (dot > 0)
            text = text.substring(0, dot);
        return String(text).trim();
    }

    // 合法且未被占用的默认名: 校验规则只有一个定义处(后端的 validateVersionName),
    // 这里不复制字符表; 重名时的 -2/-3 避让与 download.defaultVersionName 的写法一致,
    // 免得对话框一打开就是"已经存在同名版本"。取不到后端时原样返回。
    function availableVersionName(base) {
        var name = String(base || "").trim() || "ModPack";
        if (typeof download === "undefined" || download === null
                || typeof download.validateVersionName !== "function")
            return name;
        if (download.validateVersionName(name) === "")
            return name;
        for (var index = 2; index < 100; index++) {
            var candidate = name + "-" + index;
            if (download.validateVersionName(candidate) === "")
                return candidate;
        }
        return name;
    }

    // 选完文件: 只登记路径 + 算好默认名, **不**开始安装。默认名必须由对话框的
    // onOpened 在"打开完成"时才填进输入框 —— 绝不能在这里(或构造期)写 inputText,
    // 那样会让对话框的确认逻辑在用户还没看到框时就跑一遍(之前踩过的坑)。
    function askModpackName(path) {
        var text = String(path || "");
        if (text === "")
            return;
        modpackRequest.fromResource = false;      // 这条是本地文件导入
        mainWindow.pendingModpackPath = text;
        mainWindow.pendingModpackName = mainWindow.availableVersionName(
                    mainWindow.modpackDefaultName(text));
        modpackDialog.title = "安装本地整合包";
        modpackDialog.text = "将安装本地的 " + mainWindow.modpackDefaultName(text)
                + "（.mrpack）。\n可以修改版本名称，安装后会以此名字出现在版本列表里。";
        modpackDialog.open();
    }

    // 资源页(社区整合包)点「下载」: 默认名是后端算好报上来的 —— 用的就是安装整合包时
    // 同一套规则(_resolve_modpack_name: 非法字符清理 + 重名加 -2), 所以"已经装过"时
    // 预填的是 xxx-2, 用户**看得见**也能改; 后台不再自己静默避让。
    // 默认名同样只在对话框的 onOpened 里填(见 modpackDialog)。
    function askResourceModpackName(defaultName) {
        var base = String(defaultName || "").trim() || "ModPack";
        modpackRequest.fromResource = true;
        mainWindow.pendingModpackPath = "";       // 这条来源没有本地文件路径
        mainWindow.pendingModpackName = mainWindow.availableVersionName(base);
        modpackDialog.title = "安装整合包";
        modpackDialog.text = "将安装社区整合包 " + community.detailTitle
                + "。\n如果已经装过同名版本，默认名会加 -2（你可以改成别的名字）。";
        modpackDialog.open();
    }

    // 「确定」: 名字先过后端的 validateVersionName(非法 / 重名 → 红字留在屏幕上,
    // 任务数不变; 通过才真的安装 —— 自动避让逻辑仍在后端, 不绕过)。
    // 两条来源共用: 本地导入走 installLocalModpack(path, name), 资源页走
    // installPendingModpack(name)(后端在用户点下载时已经把待装条目快照下来了)。
    function confirmModpackName() {
        var fromResource = modpackRequest.fromResource;
        var path = mainWindow.pendingModpackPath;
        if (!fromResource && path === "")
            return;
        var name = String(modpackDialog.inputText || "").trim();
        var error = "";
        if (typeof download !== "undefined" && download !== null
                && typeof download.validateVersionName === "function")
            error = download.validateVersionName(name);
        if (error === "") {
            modpackRequest.fromResource = false;
            mainWindow.pendingModpackPath = "";
            if (fromResource)
                community.installPendingModpack(name);   // 名字真的传进安装逻辑
            else
                community.installLocalModpack(path, name);
            return;
        }
        modpackDialog.inputError = error;
        // FluContentDialog 的"确定"按钮自己会 close(), 所以校验失败时必须把对话框
        // **重新打开**一次, 否则红字会在框已关闭之后才写进去 —— 用户根本看不到
        // (与 InstallVersionPage.confirmName 完全同一处理)。
        modpackDialog.open();
    }

    function askInstallMod() {
        mainWindow.filePurpose = "install_mod";
        fileDialog.title = "选择 Mod 文件";
        fileDialog.nameFilters = ["Mod 文件 (*.jar *.zip *.litemod)", "所有文件 (*)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    function askExportPack(options) {
        mainWindow.filePurpose = "export_pack";
        mainWindow.filePayload = options;
        var name = options && options.pack_name ? options.pack_name : "整合包";
        fileDialog.title = "导出整合包";
        fileDialog.nameFilters = ["整合包 (*.zip)"];
        fileDialog.fileMode = FileDialog.SaveFile;
        fileDialog.currentFile = name + ".zip";
        fileDialog.open();
    }

    function askImportSettings() {
        mainWindow.filePurpose = "settings_import";
        fileDialog.title = "导入启动器设置";
        fileDialog.nameFilters = ["JSON (*.json)", "所有文件 (*)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    function askExportSettings() {
        mainWindow.filePurpose = "settings_export";
        fileDialog.title = "导出启动器设置";
        fileDialog.nameFilters = ["JSON (*.json)"];
        fileDialog.fileMode = FileDialog.SaveFile;
        fileDialog.currentFile = "CraftPilot-settings.json";
        fileDialog.open();
    }

    function askSkinFile() {
        mainWindow.filePurpose = "skin_file";
        fileDialog.title = "选择皮肤文件";
        fileDialog.nameFilters = ["皮肤 (*.png)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    function askJavaFile() {
        mainWindow.filePurpose = "java_file";
        fileDialog.title = "选择 javaw.exe";
        fileDialog.nameFilters = ["Java (*.exe)", "所有文件 (*)"];
        fileDialog.fileMode = FileDialog.OpenFile;
        fileDialog.open();
    }

    function toLocalPath(url) {
        var s = String(url);
        if (s.indexOf("file:///") === 0)
            s = s.substring(8);
        else if (s.indexOf("file://") === 0)
            s = s.substring(7);
        return decodeURIComponent(s);
    }

    // ================================================================ 后端信号
    Connections {
        target: backend

        function onMessageRequested(title, text, kind) {
            messageDialog.title = title;
            messageDialog.text = text;
            messageDialog.kind = kind;
            messageDialog.open();
        }

        function onConfirmRequested(title, text) {
            confirmDialog.title = title;
            confirmDialog.text = text;
            confirmDialog.open();
        }

        function onToastRequested(text) {
            toast.show(text);
        }

        function onWindowRequested(name) {
            if (name === "versionSelect")
                mainWindow.openVersionSelect();
            else if (name === "versionSettings")
                mainWindow.openVersionSettings();
            else if (name === "log")
                mainWindow.openLog();
        }

        // 任务全部结束后自动从「任务管理」回到主界面
        function onTasksChanged() {
            if (!backend.hasRunningTask && mainWindow.subPage
                    && mainWindow.pageTitle === "任务管理") {
                mainWindow.popPage();
            }
        }
    }

    Connections {
        target: settings

        function onChanged(key) {
            if (key === "ui.animation_speed")
                mainWindow.syncAnimationScale();
            else if (key === "check-update")
                backend.messageRequested("检查更新",
                    "当前版本 " + "1.0.0" + " 已是最新版本。\n（在线更新未实现，仅提示。）", "info");
        }
    }

    // 二级菜单返回后, 处理排队的一级切换 / 三级标签切换
    Connections {
        target: rootStack

        function onBusyChanged() {
            if (rootStack.busy)
                return;
            if (mainWindow.pendingRoot >= 0) {
                var index = mainWindow.pendingRoot;
                mainWindow.pendingRoot = -1;
                mainWindow.applyRoot(index);
                return;
            }
            if (mainWindow.pendingSection >= 0) {
                var section = mainWindow.pendingSection;
                mainWindow.pendingSection = -1;
                if (rootStack.currentItem && rootStack.currentItem.showSection)
                    rootStack.currentItem.showSection(section);
            }
        }
    }
}
