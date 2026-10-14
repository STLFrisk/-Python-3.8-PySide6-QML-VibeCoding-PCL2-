# 更新日志 · CraftPilot（`pcl_py`）

> **本文只写有据可查的改动。** 取证方式：备份目录名（`default-workspace/pcl_py_backups/`，名字里带代号与时间戳，
> 用作时间锚点；完整清单见 [`DOCS_BACKUPS.md`](DOCS_BACKUPS.md)）、代码里以 ASCII 标签写下的根因注释、
> `TODO.md` / `PCL2_ANALYSIS.md` / `README_分发.txt`，以及工作区里现存的实测记录文件。
> 凡本文写出的数字都有出处，出处在条目末尾用括号标出；拿不到出处的一律不写
> （见文末「未能取证、因而未写入正文的条目」）。
>
> **版本号**：仓库内唯一可考证的版本号是已打包分发的 **CraftPilot 1.0.0**（构建日期 2026-10-15，
> 见 `README_分发.txt` 首节）。仓库里没有 tag、也没有历史发布记录，因此下面的条目统一列在
> **未发布（Unreleased）** 之下，按主题分成若干小节；小节与条目括号里的日期取自备份目录名和
> 源文件时间戳（可考证范围 **2026-10-13 → 2026-10-15**），只用来标明先后与时间窗，不当作发布号。
>
> 完整备份（快照集合）作为 Release 附件发布，**不随仓库分发**。

---

## 怎么读这份日志

* **每条三段式**：现象/根因 → 修法 → 实测证据。
* **证据分级**：`实测` = 在本机跑出来的数字；`代码注释` = 代码里逐条写下的根因与实测值；
  `测试固化` = 已被 `tests/test_core.py` 的断言覆盖（数字为该测试的断言条数，可复跑）。
* **条目编号**（`V` / `C` / `D` / `E` / `F` / `G` / `X` / `P` 加序号）只用于本文件内部的互相引用
  （例如「见 F7」）。它既不是版本号，也不表示条目之间的先后关系。
* 括号里给出的是**出处**（代码路径、测试名、备份目录名或实测记录文件），可以按路径逐条复核；
  各条目对应的快照目录与时间见 [`DOCS_BACKUPS.md`](DOCS_BACKUPS.md)。

---

## 未发布（Unreleased）

### 启动链路：Java 选择、命令行占位符与 natives

> 快照时间锚点：2026-10-13 18:20 → 2026-10-14 01:58（`pcl_py_v1_20261013_1820` … `pcl_py_v19_20261014_0158`）。

**V1 启动立刻退出，退出码 1 —— Java 版本猜错**
现象：按 MC 版本号猜 Java（`26.3` 被猜成 21），而版本 json 写着 `javaVersion.majorVersion = 25`，
Java 21 加载 Java 25 的 class 直接 `UnsupportedClassVersionError`。
修法：读版本 json 的 `javaVersion` 选 Java，挑「够用的最低主版本」，并优先非 `javapath` 转发的真实 `javaw.exe`。
（代码注释）

**V2 进程在、窗口不出 —— jvm 参数指向的 natives 子目录没建**
根因：1.19+ 的 jvm 参数把 `-Djna.tmpdir=${natives_directory}/jna`（还有 lwjgl、netty）指向 natives 子目录，
而启动器只建了 `natives/` → `UnsatisfiedLinkError`。
修法：扫描 jvm 参数里所有指向 natives 目录的 `-D` 路径并自动建目录。（代码注释）

**V3 进程在、窗口不出（第二例）—— 输出读取线程静默死亡 → 管道写满**
根因：游戏输出走 `stdout=PIPE`，读取线程把文本模式的 `str` 当 `bytes` 调 `.decode()`，异常被吞掉后线程静默退出，
管道写满后游戏阻塞在写日志上。
修法：输出直接写 `versions/<版本id>/pclpy_launch.log`，界面用 `TailLogReader` 跟进；读取器兼容 str/bytes 并等进程真正退出。
（代码注释）

**V4 退出码显示成 `4294967294`**：Windows 下 `Popen.wait()` 可能返回无符号值，PySide 的 `int` 信号溢出 → 归一到 int32。（代码注释）

**V5 命令行残留 `${clientid}` / `${auth_xuid}`**：占位符表缺项 → 补上（置空）。（代码注释）

**V6 含 Forge/NeoForge 的版本报 `InaccessibleObjectException` 退出码 1**
根因：这类版本 json 的 jvm 参数用了 `${library_directory}` / `${classpath_separator}`，没替换 →
`-p` 模块路径变成带 `${...}` 的垃圾字符串，模块层建不出来。修法：补齐这两个占位符（以及 `primary_jar` 等）。
（代码注释）

**V7 Fabric 报 `duplicate ASM classes ... asm-9.6.jar and asm-9.9.jar`**
根因：加载器 json 同时列了原版自带的旧库和加载器自己的新库，之前全部塞进 classpath。
修法：按 `group:artifact:classifier` 去重，保留版本号更高的一个。（代码注释）

**V8 NeoForge 报找不到 `neoforge` 模块**
根因：这种版本的 json 既没引用 `neoforge-<ver>-client.jar` / `-universal.jar`，也没有 `-Dfml.modFolders`。
修法：从 libraries 自动补进 classpath、生成 `-Dfml.modFolders=neoforge=<universal>`，并按官方做法加
`-DmergeModules=<client>,<universal>`（两者自动模块名都叫 neoforge，必须合并成一个模块）。（代码注释）

**V9 下载页/按钮/圆角等外壳与观感项**：`PclButton` 文字居中（实测偏左 30px → +1px）、`RoundedPanel` 圆角
（四个角各 40 个透明像素，改前 23 即直角）、二三级菜单合并进单窗口、`--title` 参数无实际效果等。
（备份 `pcl_py_v1_20261013_1820` … `pcl_py_v19_20261014_0158`）

**V10 提速三件事**：版本扫描、Java 检测改后台线程（大 `versions` 目录不再阻塞 UI）、配置写盘加 600ms 防抖、
显式启用 `QSG_RENDER_LOOP=threaded`（仅非软件渲染）。（代码注释 `pclpy/core/config.py`、`pclpy/app.py`）

**V11 版本列表「示例数据」误判**
根因：`pclpy/backend/workers.py` **漏了 `import os`**，`os.path.isdir` 抛 `NameError`，又被
`except Exception: items = []` 静默吞掉 → 扫描永远返回空 → 回退示例数据。
修法：补 `import os`，并让线程里的异常打印出来（不再静默）；`use_demo_data` 默认关闭。
实测：真实 `.minecraft` 扫到 **17** 个版本、`demoMode = False`；vanilla **1.21.4** 通过启动器本体启动成功，
日志里 `Completely ignored arguments: [--title, PCL]` 印证现代版本忽略 `--title`。
（代码注释 `pclpy/backend/workers.py`）

---

### 任务页、主题色与对话框

> 快照时间锚点：2026-10-14 03:19 → 04:53（`pcl_py_c1_dialog_20261014_0319` … `pcl_py_c15_isolate_20261014_0453`）。

**C1 下载进度不再模态，改为「任务管理」页**
改动：新增二级页 `TaskPage.qml`；`install.py` 增加 `phase_cb`/`bytes_cb`，能报告 7 个安装步骤的进度与下载字节数；
后端 `taskModel` + 700ms 定时器算实时速度；删除模态 `ProgressDialog`；右下角常驻圆标（`z: 900`，Canvas 进度环）。
实测（端到端脚本跑一次真实 Fabric 安装任务）：进度 20%→100%、速度 172K/s ~ 914K/s、
7 个步骤全部完成、`versions/1.20.1-Fabric_0.15.11` 与 8 个依赖库落盘。（代码注释 `qml/pages/TaskPage.qml`、`pclpy/core/install.py`）

**C2 主题色实时生效**：`theme.py` 改为可通知对象，`setPrimary()` 重算派生色并发 `primaryChanged`，
QML 里所有 `theme.*` 绑定自动刷新；新增 `PersonalizationSettings.qml`（8 预设 + 取色器 + 预览 + 悬浮按钮开关）。
实测：主题改色后标题栏像素由 `(60,130,212)` 变为 `(210,94,91)`。（代码注释 `pclpy/theme.py`）

**C3 对话框关不掉 / 文字被裁**：`PclDialog` 消息区原用 `Text.implicitHeight`（宽度未定时偏小）→ 改
`contentHeight`；`Flickable` 的 `implicitHeight` 恒为 0 → 补 `implicitHeight: height`，上限 320 → 380px，
按钮固定底部并允许 Esc 关闭。（代码注释 `qml/components/PclDialog.qml`）

**C4 对话框输入框错位 / 校验红字看不见**：`PclTextField` 上的 `bottomPadding` 把文字顶上去 → 改成在其后放占位 Item；
安装改名统一用对话框自带的输入框（本来就在按钮上方），并新增 `inputError` 红字提示显示在输入框正下方。
（代码注释 `qml/components/PclDialog.qml`、`qml/components/PclTextField.qml`）

**C5 重命名对话框「一打开就是空的、还 already 报错」**
根因：`onPositiveClickListener` 是 vendor 声明的**属性**，写成 `onXxxClickListener: { ... }` 是**属性绑定**，
绑定在**对象构造期**就求值 → 构造 `PclDialog` 的一瞬间把 `accepted()` 发了一遍（调用方还没在 `onOpened` 里填默认名）
→ 校验失败写下「名称不能为空」→ 真正打开时默认名被 `inputError` 挡住。
修法：加 `confirmArmed` 闸门，`onOpened` 之后才允许确认。
（代码注释 `qml/components/PclDialog.qml`；`TODO.md`）

**C6 校验失败时对话框被 vendor 追着关掉**
根因：`vendor/.../FluContentDialog.qml` 的按钮点击是 `if (onPositiveClickListener) { ... } else { positiveClicked(); control.close() }`
—— 只挂信号就走 `else`，调用方在校验失败时 `renameDialog.open()` 重开的框，会在信号返回后被 vendor 那句
`control.close()` 又关掉（实测 `opened=False visible=False`）。
修法：用**函数字面量**接管 listener，关不关由 `_handleConfirm()`/`_handleCancel()` 按「调用方有没有报错」决定；
键点：`function () { ... }` 是函数字面量，构造期只赋对象不执行函数体，与上一坑的语句块写法语义完全不同。
（代码注释 `qml/components/PclDialog.qml`；`TODO.md`）

**C7 加载器勾选互斥失效**：复选框写 `checked: modelData.selected === true`，用户点击会**打断绑定**，
之后互斥逻辑取消勾选时界面不跟着变 → 改 `Binding on checked { ... }`（命令式赋值后自动恢复）。
实测两个方向互斥都生效。（代码注释 `qml/pages/LoaderVersionPage.qml`）

**C8 OptiFine 下载失败**：镜像地址本身可用（实测 200 + `application/java-archive`），但通用下载器对
**没有 Content-Length 的响应**会失败 → 新增直连下载兜底（流式写入 + 体积校验），实测下到 **6.78 MB** 真安装包。
（代码注释 `pclpy/core/remote.py`）

**C9 版本列表排序**：原用清单里的 `time`（"最后修改时间"，很多条目是错的）→ 改 `releaseTime`（真正的发布时间），
显示与排序都用它。（代码注释 `pclpy/core/versions.py`）

**C10 安装改名要同时改磁盘**：`renameVersion` 做**真正的改名**：目录 + json 文件名 + json 里的 `id` 一起改，
并同步显示名与当前选中版本；重名/非法字符/文件被占用都提示且不改。（代码注释 `pclpy/backend/launcher.py`）

**C11 安装前命名校验 + 自动避让**：非空、不含 `\ / : * ? " < > |`、不能以点结尾、不能与现有版本目录重名；
不通过就在输入框下方红字提示且不开始安装。（代码注释 `pclpy/backend/download.py`；`TODO.md` 记有离线回归项）

**C12 复制/重命名副本要真正独立**：自定义命名 = **完整独立副本**：先链式合并父 json（库/参数/资源索引）
再清 `inheritsFrom`，并补齐自己的客户端 jar → 与源版本互不依赖。
（代码注释 `pclpy/core/versions.py`；备份 `pcl_py_c13_copy_*`、`pcl_py_d4/d5_selfcontained*`）

**C13 删除/改名时的依赖提示**：检查是否仍有版本声明继承它（只剩**外部导入**的版本会命中），命中就明确提示
「删除后将无法启动」。（`pclpy/backend/launcher.py` 的告警文案；备份 `pcl_py_d6_orphanwarn_*`）

---

### 下载校验、占位标记与隔离标记

> 快照时间锚点：2026-10-14 05:03 → 14:23（`pcl_py_d1_hash_20261014_0503` … `pcl_py_d10_readme_20261014_1423`）。

**D1 整合包按索引 sha1 校验，坏源不再静默留损坏文件**（备份 `pcl_py_d1_hash_*`）
依据：`PCL2_ANALYSIS.md` 指出「我们**完全不校验**，坏源会静默留下损坏文件」。
修法：按 `.mrpack` 索引里的 `sha1` 校验；本机已有同大小文件**直接复用**（跨实例省流量）。
代码注释把这条与本地复用合并记在 `_reuse_local`：**必须大小一致且 sha1 一致**才复用，且**复制后必须复核 sha1**。

**D2 本机复用只比大小的坑（重要）**
根因：`_reuse_local` 以前**只比大小**（注释还写着"不做哈希，得不偿失"）→ 别的整合包/版本里"同名同大小但内容不同"
的文件被当成它复制过来 → 整合包 mod 数量对但内容不对；复制完也不复核。
修法：候选必须大小 + sha1 都一致；复制后再复核一次，不过就删掉复制结果返回 False 去老实下载。
（代码注释 `pclpy/core/resources.py`）
**测试固化**：`test_modpack_install_regression` 断言「同名同大小但 sha1 不同 → 不复用，真下载」「内容一致 → 复用，0 次下载」
「复用过来的内容正确」「复用的文件没有把错误内容带进来」等（4 条）。（`tests/test_core.py`）

**D3 磁盘上被改坏的半成品被无脑认下**
根因：以前只写 `if os.path.isfile(dest): continue` → 上次安装留下的半个/损坏/同名不同内容的文件被认下，
"重装之后还是少文件/内容不对"。
修法：必须 `_matches_entry()`（大小 + sha1）通过才算已有，否则重下。
**测试固化**：`④-4 磁盘上被改坏的文件 → 重新下载`、`④-4 重下后内容正确`、`④-4 重下成功 → 不写未完成标记`（3 条）。
（代码注释 `pclpy/core/resources.py` + `tests/test_core.py`）

**D4 索引里没有 downloads 的文件被静默跳过（"少一大半 mod，失败清单还是空的"）**
根因：以前这里**静默跳过**。`.mrpack` 里 CurseForge 托管的文件就是没有 `downloads`，需要 CurseForge API 才能换到地址。
修法：记进 `missing` 清单并让用户看见，不再假装全成功。
（代码注释 `pclpy/core/resources.py`；CurseForge 需官方 API Key 一事也记在 `TODO.md`）

**D5 整合包下载线程因元组解包全部死掉（最隐蔽的 bug 之一）**
根因：`pending` 里是**四元组** `(url, dest, sha1, size)`，`_runner` 里写成 `url, dest = pending[i]`
→ 每个工作线程立刻抛 `ValueError: too many values to unpack` 死掉，一个文件都下不下来；版本目录只剩 overrides 解压出来的那点文件，
而 `failed` 还是空的 → "装完了但 mod 少一大半，失败清单却是空的"。
修法：整条解包 `url, dest, sha1, size = pending[i]`；并补上**当时完全没有 import** 的 `pclpy.core.resources` 回归测试。
（代码注释 `pclpy/core/resources.py`；`tests/test_core.py::test_modpack_install_regression` 的 docstring 明确写了这条事故）

**D6 校验失败与删除的顺序错**：以前控制流是「成功也走失败分支」——下完的文件被 `os.remove` 删掉又记进失败清单。
修法：成功就 return，失败才清理 + 记账。（代码注释 `pclpy/core/resources.py`）

**D7 未装完的版本写占位、扫描时隐藏、失败清理**
修法：`core/install.py` 的 `mark_installing` / `clear_installing` / `cleanup_unfinished`；Forge/NeoForge 也写占位
（目录监视版，见 F1）。**测试固化**：`④-3 有文件下不下来 → 写 .pclpy_installing`、`④-3 状态文案含「未完成」`、
`④-3 失败不影响别的文件落盘` 等（4 条）。（`TODO.md`；`tests/test_core.py`）

**D8 残留占位导致版本凭空消失（自愈）**
根因：占位可能是**残留**——安装其实早就成功了（有完整 json + 能用的客户端 jar），但占位还在 → 版本不列出。
修法：扫描时若 `_looks_installed()` 成立就删掉占位并正常列出；「有存档一律保留」。（代码注释 `pclpy/core/versions.py`）

**D9 版本隔离标记写进版本 json（污染 Mojang json）**
根因：`PCL2_ANALYSIS.md` 第 143/187 条指出，把 `pclpy:isolate` **写进了版本 json**，其它工具可能视为非法字段、
重装导出时丢失。
修法：隔离标记改写到 `versions/<id>/PCL/Setup.ini`（PCL2 的存放位置），版本 json 保持纯净；
同时写 PCL2 兼容键 `VersionArgumentIndieV2=True/False` 与遗留键 `VersionArgumentIndie=1/2`，两个启动器互认。
（`pclpy/core/install.py::write_isolation_flag` 注释；`PCL2_ANALYSIS.md` 建议 2；备份 `pcl_py_c14_unified_*`、`pcl_py_d3_isolate_*`）

**D10 `Download/Download` 套娃目录**
根因：`download_dir()` 对「未知类型 / 空 / 本来就叫 Download」的入参照旧拼一层子目录。
修法：这类入参直接返回 `Download` 根；子目录名再兜一层「不能为空、不能和 Download 同名」。
（代码注释 `pclpy/core/paths.py`）

**D11 版本隔离规则的三态与「决策冻结」**
修法（对齐 PCL2）：`open` / `mod` / `close` 三态；首次运行 `migrate_isolation_default()` 把档位**写死**进配置
（PCL2 的 Decide & Freeze 语义）；判据基于**合并后**的 json 而不是自身 json（继承自 Forge 的副本不会被误判）。
（`pclpy/core/launch.py` 注释 + `PCL2_ANALYSIS.md` 第三节；`tests/test_core.py` 有 `launch.isolation` 三态断言）

---

### 内容区 FluentUI 组件与资源详情页

> 快照时间锚点：2026-10-14 14:46 → 16:01（`pcl_py_pre_fluentcomp_20261014_1446`、`pcl_py_e1_fluentui_anchor_20261014_1448` … `pcl_py_e9_switch_20261014_1601`）。

**E1 5 个基础组件换回 FluentUI 版**：`PclButton` / `PclCheckBox` / `PclTextField` / `PclComboBox` / `PclSlider`
+ `Main.qml` 补 `import FluentUI` 与 `FluTheme.primaryColor`。窗口/标题栏/圆角/拖拽一律不动，只改内容区。
（备份 `pcl_py_e1_fluentui_anchor_*`、`pcl_py_e3_all5_*`）
**为什么叫"换回"**：这类组件在早期版本里曾是自绘替代品，属于历史包袱；这里把内容区组件交还给套件，
外壳仍保持 PCL2 风格。

**E2 资源详情页两级分组与折叠**
* 加载器 → 适配版本 → 文件两级结构；加载器按常见顺序排列、同组内版本新的在前；
  实测 Sodium：`fabric`(18 个版本) / `fabric/quilt`(11) / `neoforge`(14) 三组，组内版本新→旧。
* 两级分组标题都可点击折叠：内容高度在 0 与内容高度之间做 `OutCubic` 动画（时长乘全局 `animationScale`），
  左侧 `chevron_right` 箭头 0°↔90° 带 `Behavior` 动画。
（备份 `pcl_py_e2_groups_*`、`pcl_py_e4_tree_*`）

**E3 加载器标签被截断**
根因：`"/".join(names[:2])`、界面侧 `loaders[:3]` —— 一个版本文件支持 3 个以上加载器时，组名只留前两个，
标签**不代表**这组文件实际支持的加载器（用户报的"多加载器标签显示不全"）。
修法：完整拼接 —— 组名 = 该组文件的加载器集合。
（代码注释 `pclpy/core/resources.py` 与 `pclpy/backend/resources.py`）

**E4 服务端独占时挂错"数据包版本"文案**
根因：文案原本**写死在界面里**（`qml/pages/ResourceDetailPage.qml`），且默认按"第一大类是客户端"来写；
项目只有服务端核心版本时 `groups[0]` 是服务端大类，文案却照旧宣称"以下是数据包版本"。另有一种做法是
"这种情形干脆不挂跳转条"，但那样用户没有入口。
修法：后端 `_switch_text()` 给出整句 `switchText`（客户端两句**逐字保留**），谁带跳转条谁负责说清楚；
界面优先读 `switchText`，读不到才回退原句。
实测：essentialsx（纯服务端）显示相符文案、luckperms/terralith 逐字不变、老数据无 `switchText` 时 QML 回退原句。
（代码注释 `pclpy/backend/resources.py`）

**E5 跳转条出现两条**：以前额外往 `children[0]` 上写了一份 → Mods 页同时出现两条一模一样的
"以下是该项目的「Mod」版本…"（客户端大类下一条、客户端 · fabric 子组下一条）。
修法：跳转条只挂在最外面的大类**本身**上，有且只能有一个。
（代码注释 `pclpy/backend/resources.py`）

**E6 详情页按行号取项目 → 点到别的资源**
根因：详情页按**列表行号**取项目，而搜索是异步的 —— 搜索一完成行号就全变了。
修法：改按**项目 id** 打开（`openProjectById`），并把当时的分类/版本/加载器条件一起**快照**。
实测：行内容是 `Fabric API / P7dR8mSH` → 详情标题与文件完全一致。
（代码注释里的 `self._detail_kind` 快照）

**E7 二级菜单点已选中项会"取消选中"**：`SideItem` 是 `checkable: true` 的 Button，再点一次自己会取消 `checked`
→ 改 `checkable: false`，选中状态完全由外部绑定 `checked` 决定。（备份 `pcl_py_e7_sidetop_*`）

**E8 页面切换前后两页内容重叠**：原来是"交叉淡入淡出"（两页同时半透明），而页面本身透明 → 必然重叠。
修法：退出页在动画前 35% 时间就淡出到 0，进入页只做纵向滑入。
**随之而来的回退页不可见**：退出页的 `opacity` 淡到 0 后**回到该页时没人恢复它**（现象：页面不显示但仍能点到组件）
→ `pushEnter`/`popEnter` 各加一条 `from:1 to:1` 动画显式恢复。
（备份 `pcl_py_f1_center_*`、`pcl_py_f2_anim_*`）

**E9 启动页几何对齐**：启动页账号区居中 ✅、启动按钮文字居中 ✅；标题栏按钮/图标观感未逐项核对。
（`TODO.md`）

---

### 整合包闭环与日志降噪

> 快照时间锚点：2026-10-14 16:29 → 17:02（`pcl_py_f1_center_20261014_1629` … `pcl_py_f6_missing_20261014_1702`）。

**F1 Forge/NeoForge 占位监视竞态（零副作用补扫）**
现象：Forge 安装器自己创建版本目录，等我们收尾时占位可能已经来不及写/来不及清。
修法：抽出共享 `_forge_watch_matcher` + 新增**零副作用**的 `_forge_watch_new_dirs`；收尾改为
「先 join 到线程**真停** → 停稳后补扫并清除」。
实测：目录在最后一次轮询之后出现也能被补扫清除；**对照组用旧代码复现出残留**（证明窗口确实被消掉）；
已存在/名字不匹配的目录不受影响；`ok=False` 仍保留占位。
（代码注释 `pclpy/core/resources.py`；`TODO.md`）
遗留：该竞态的验证脚本是一次性的，未并入 `tests/test_core.py` 成为永久回归（`TODO.md` 记着这条）。

**F2 `.mrpack` 的 `env.client=unsupported` 文件跳过**
修法：客户端装了也用不上的文件**不下载、不安装**，也**不算失败/未完成**；判定必须放在「没有 downloads」判定**之前**
（这类纯服务端文件常常也没有 downloads，先走 missing 会把它记成"缺下载地址/未完成"）；
`optional` **保持原有行为：照装**（跳过 optional 会让整合包功能缺失，属超出"跳过 unsupported"的行为变更）。
跳过条数在进度文案里可见（**文案里刻意不出现 `n/m`**，避免和真正的 pending 计数混淆）。
**测试固化**：`④-5` 共 **10 条**断言（不被下载 / 不落盘 / 不计 pending / optional 照装 / 其余正常落盘 /
unsupported 且无下载地址不算"缺地址" / 跳过条数可见 / 不算失败 / 版本没被标成未完成 / 全程 0 次真实网络请求）。
离线测试总数因此 **201 → 211 OK / 0 FAIL**。（`tests/test_core.py`）

**F3 整合包安装步骤对齐 PCL2 + 两处进度不一致**
现象：任务 96% 而"下载整合包文件"还是 0%；速度恒为 `--`；看起来卡在 98%。
根因：① 整合包文件这一步只更新任务总进度、没更新步骤进度；② 下载步骤没喂字节增量（速度）而只按"已完成文件数"上报
（大文件长时间不动 → 观感卡死）。
修法：两者同步上报；按字节增量累加；每个文件下载时都按字节回调进度。实测速度已能显示 `1006 K/s`。
（`TODO.md` 的 `MODPACK_STEPS`；备份 `pcl_py_g5_steps_*`、`pcl_py_g6_stepsfixed_*`）

**F4 本地整合包导入补命名对话框**
现象：选完 `.mrpack` 直接开装，用户改不了版本名。
修法：`Main.qml` 新增 `modpackDialog` —— 默认名只在 `onOpened` 填（构造期求值的坑见 C5）、
重名走后端 `download.validateVersionName` 自动避让 `-2`、失败时红字留屏。
实测 22 项：选完文件**不自动安装**、取消=不装、确定=**恰好 1 个任务**、重名红字 **449** 危险色像素可见。
（备份 `pcl_py_g6_namedlg_*`）

**F5 整合包会自动装好依赖（否则只能当纯原版启动）**
现象：整合包安装成功，但启动时只是一个纯原版 Minecraft，包里的 Mod 一个都不生效。
根因：整合包版本 json 的 `inheritsFrom` **只在「对应的加载器版本已经装过」时才填**，否则退化成原版、甚至写成空字符串。
修法：新增 `ensure_modpack_parent()` —— 安装整合包时**自动装好需要的原版 + 模组加载器**
（按 `.mrpack` 里 `dependencies` 指定的版本），并用安装器返回的**真实版本 id** 作为 `inheritsFrom`；
任务步骤新增「安装原版与模组加载器」。
实测：依赖 `fabric-loader 0.19.4`（本地**未安装**）的整合包 → 自动装好 → `inheritsFrom = 1.20.1-Fabric_0.19.4`
且父版本文件确实存在 ✓ **PASS**。（备份 `pcl_py_f4_modpack_*`、`pcl_py_f5_modpackfix_*`）
顺带修：没有可下载文件的整合包会崩 —— `failed` 变量只在"有文件要下"的分支里定义，空文件列表会 `UnboundLocalError`
→ 提到分支外初始化。（代码注释 `pclpy/core/resources.py`）

**F6 整合包端到端实测：143 个 mod**
实测：真实 Modrinth `.mrpack` 下载 → 解包 → 按索引下载文件到 `mods/`（拿到 `sodium-fabric-0.5.13+mc1.20.1.jar`）
→ 解压 overrides（`config/test.toml`、`mods/extra.txt`）→ 生成继承对应加载器的版本 json ✓ **PASS**；
后续整包实测 **143 个 mod** 端到端通过。（`TODO.md` 的已完成清单）
`TODO.md` 另记着 skip 语义下的数字口径：**"包里 143 个文件、装出来 138 个"会被当成丢文件**，
所以跳过条数必须在文案里出现。（代码注释 `pclpy/core/resources.py`）

**F7 调试日志从"磁盘与 GIL 全被吃死"到每秒一条**
根因：下载循环里的重复事件（同一段反复收缩等）以前**一行一行刷爆 stderr**。
修法两道刹车：① 同类事件每个 key 每秒最多一条（`_DBG_MIN_INTERVAL`），被压掉多少条会汇总补一句
`(suppressed N in last 1s)`；② 只保留 ASCII 标签，输出行数与"事件种类 × 持续秒数"成正比、与重试次数无关。
代码注释记录的旧版观测值：**一次下载写出 97.9MB / 111 万行**。
实测（改后）：一次 4MB×8 文件的压力跑，引擎 stderr **12 行**，日志里带 `suppressed 9 in last 1s` 这类汇总行。
（代码注释 `pclpy/core/remote.py`；`_sub_evidence.txt`）

**F8 关窗期 19 条 `of null` 全部清零**
根因：窗口关闭时，QML 仍会对**存活的绑定**再求值一次，那时 context property 背后的对象已经是 `null`，
直接读 `.versionId` / `.subtitle` / `.icon` / `.title` / `.favorite` 或调 `.value()` 会抛
`Cannot read property 'x' of null` / `Cannot call method 'value' of null`。
修法：`OtherSettings.qml`（16 处）+ `VersionExportPage.qml`（4 处）+ `VersionOverviewPage.qml` / `VersionConfigPage.qml`
加空安全，回落值逐个对齐 `config.py` 的 DEFAULTS。
实测（确定性探针：删掉 context property 背后的对象后泵事件）：**6→0 / 12→0 / 19→0**；
外观三重证据：探针 **23 OK** 逐条一致、像素差 **0/614400**、截图 **14/14** 同名。
（代码注释 `qml/pages/version/VersionOverviewPage.qml`、`VersionExportPage.qml`；`TODO.md`）

**F9 截图工具新增资源详情页**：`tools/shots.py` 增加资源详情页截图
（`resource-detail-mod-sodium.png`、`resource-detail-datapack-terralith.png`），**离线也能出图**；
总数到 **14 张**。（`shots/` 目录里的 14 张 PNG 即其产物）

---

### 版本隔离判定顺序、下载速度与任务模型

> 快照时间锚点：2026-10-14 17:11 → 23:23（`pcl_py_g1_isolationorder_20261014_1711` … `pcl_py_g9_before_remote_rollback_20261014_2323`）。

**G1 PCL2 装的整合包 mod 一个都加载不到 —— 隔离判定顺序**
现象：PCL2 隔离安装的整合包，在 CraftPilot 里启动后 `versions/<id>/mods` 里的模组一个都不加载。
根因：判定顺序把**我们自己的全局默认**（`launch.isolation`）排在 PCL2 的**单版本标记之前**，
全局值把单版本标记整个短路掉了 → 本该隔离的实例被当成"不隔离"。
修法：把 PCL2 写在版本目录里的**单版本标记提到最权威**，顺序改为
① 单版本 `versions/<id>/PCL/Setup.ini` → ② 旧版写进 json 的 `pclpy:isolate`（今后只读） →
③ 版本目录里已有 `mods`/`saves`（PCL2 启发式）→ ④ 全局 `launch.isolation` → ⑤ PCL2 全局档位 `LaunchArgumentIndieV2`（0..4）
→ ⑥ 兜底「带 Mod 加载器就隔离」→ ⑦ 都没有就关闭。
实测就是这个问题（代码注释原话）；mods 真实加载验证见 G2。
（代码注释 `pclpy/core/launch.py`；备份 `pcl_py_g1_isolationorder_*`）

**G2 mods 到底会不会被加载 —— 46/46 实测**
实测：把版本目录里的 **46 个模组**复制到可写 gameDir 后**真实启动**，日志里 **46/46** 全部出现、Mod List 正常输出 ✓
（沙箱不允许游戏写只读的 `.minecraft`，所以测试用可写目录代替）。（代码注释 `pclpy/core/launch.py`）

**G3 空值覆盖父版本 → `ClassNotFoundException: net.minecraft.client.main.Main`**
根因：子版本 json 里一个空的 `mainClass`（或空 `libraries`）会把父版本（例如 Forge 的 `BootstrapLauncher`）清成空，
空的 `libraries` 又会把父版本的全部库清掉 → 启动就是 `ClassNotFoundException: net.minecraft.client.main.Main`。
修法：`_merge_two` 里空值（`""` / `[]` / `{}` / `None`）**不算"覆盖"**；只有父版本本身也没有值时才写下空值。
（代码注释 `pclpy/core/launch.py`）

**G4 加载器副本真正独立 / 安装即自包含**
改动：Fabric/Quilt/Forge/NeoForge 装完即自包含、**不再有父子依赖**；整合包实例完全独立（自带 jar + 合并 json，
**删父版本仍可用**）。（备份 `pcl_py_d4/d5_selfcontained*`、`pcl_py_c14_unified_*`）

**G5 NeoForge 模块解析崩溃的三种补法实测（把失败的尝试也记下来）**
背景：某版本 json 被启动器改写后缺失加载器库条目，`net.neoforged:neoforge:<ver>:client` 指向的是 NeoForm 的
`client-<mc>-<neoform>-srg.jar`，而 json 里既没有 `client` 也没有 `universal` 条目。三种补法实测：
(a) 只补 universal → `ClassNotFoundException: LoadingOverlay`；
(b) 补 universal + 把 srg jar 当游戏本体 → `Module minecraft contains package ...`（和 FML 自己建的 minecraft 模块抢包）；
(c) 补 universal + `<loader>-client.jar` + `-DmergeModules` 合并 → 能走到 Mod List（**46 个模组全部识别**），
但模块层仍会与 minecraft 模块冲突。
结论：**这个版本的 json 本身不完整，建议用启动器「可安装 Mod」重新安装一遍该版本**，
而不是继续给残缺 json 打补丁。（代码注释 `pclpy/core/launch.py`）

**G6 速度改为单点计算（学 PCL2）**
根因：以前每个任务各自 `delta/0.7` 定时器算速度，并行下载时某个文件回调一稀疏就会显示 `--` 或乱跳。
修法：全局字节账本 + **200ms 采样** + 15 点递减加权平均；任务行与左栏共用同一数值。
（代码注释 `pclpy/backend/launcher.py`；`PCL2_ANALYSIS.md` 第一节「速度」；备份 `pcl_py_d2_speed_*`、`pcl_py_g7_speedfix_*`）

**G7 任务模型更新只报"真正变化的角色"，并给进度推送加最小间隔**
根因两处：
* `DictListModel.update_row` 以前"无论改什么都发全部角色的 dataChanged"，而任务页委托里嵌套着 **12 行步骤的 Repeater**
  → 每个进度回调都把整张卡片（含全部步骤行）重建一遍。代码注释记录的实测：**单次更新 30ms 上下，峰值 1.3s**；
  高并发下载（几十条连接每秒几百次回调）时主线程被这些重建占满，界面直接"未响应"。
  修法：只为真正变化的角色发 `dataChanged`，全都没变时连信号都不发。
* worker 侧以前每次回调都跨线程 `emit`，主线程事件队列被灌满 —— 代码注释记录的实测：
  **界面每秒只能处理 11 次左右**，队列越积越多 → "未响应"。
  修法：字节账本只累加不发信号；文本/百分比/步骤进度累积在对象上，由界面 200ms 定时器 `take_ui_state()` 统一 pull；
  补推最小间隔 `PUSH_INTERVAL = 0.1`，百分比首次到 100 强制补推（不丢最后一帧）。
（代码注释 `pclpy/backend/models.py`、`pclpy/backend/workers.py`）

**G8 任务字典刷新会丢字段 / 落盘路径存在共享变量里**：改为按任务 id 记录落盘路径，并修正任务字典刷新丢字段的隐患。
实测（多任务并行，3 个 Mod 并行下载）：三个任务各自独立（进度 5%→28%→73%→100% 互不干扰）、
落盘路径互不相同且文件都正确生成、速度与剩余文件数都正常 ✓ **PASS**。（代码注释 `pclpy/backend/launcher_tasks.py`）

**G9 关闭动画 / 启动动画**：启动与关闭淡入淡出；任务全部结束时若停留在「任务管理」页则自动返回；
右下圆标显示完成后等待 5 秒、再用 400ms 淡出。（`TODO.md` 的已完成清单；`qml/Main.qml`）

**G10 设置页「下载分片调参」上线（含"当前实际生效"一行）**
为什么这样取值：`remote.py` 顶部的默认值注释明确写着**默认值被调大是 A/B 实测的结果** ——
「上游 CDN 对**单条连接**限速，单连接吞吐有天花板；总吞吐 ≈ 连接数 × 单连接上限。分片不是元凶，反而在帮忙」。
于是三件事一起调高：分片阈值 **4MB→1MB**、单文件段数上限 **4→8**、全局 Range 连接预算 **16→32**；
并保留自适应加段（起步 4 段，实测慢才加）。
落地：`pclpy/core/config.py` 的 `download.*`（`segments_enabled` / `segments_max` / `segments_start` /
`connections` / `min_size_mb` / `slow_kbps` / `debug_log`，默认 True/8/4/32/1/1024/False），
`SettingsBackend.downloadTuning` 只读属性 + `OtherSettings.qml` 的「— 下载分片调参 —」区与
「当前实际生效: …」那一行（把环境变量也算进去）；生效顺序 = 环境变量 > 设置项 > 代码默认值，**下一次下载**就生效。
（代码注释 `pclpy/core/remote.py`、`pclpy/core/config.py`、`qml/pages/settings/OtherSettings.qml`；
`README_分发.txt` 第 3 节；备份 `pcl_py_g7_speedfix_20261014_2227` → `pcl_py_sub_20261015_0014`）

**G11 内容区改造收口**：明细见 E1 / E9；对应快照 `pcl_py_g8_Cdone_20261014_2254`。

---

### 下载引擎：PCL2 式多连接 Range 分片

> 本节内容**先有实测、再改代码**：先用一份"可注入停滞的本地 HTTP 服务器"把旧版跑崩，记下数字，再改。
> 证据记录：`_sub_evidence.txt`（工作区根目录，全部数字实测于 2026-10-15）。
> 相关快照：2026-10-14 23:31 → 2026-10-15 03:23（`pcl_py_sub_20261014_233139` … `pcl_py_sub_20261015_0323`）。

#### 现象与根因（为什么旧版会被自己的重试拖死）

**(1) 段被自适应扩容切走后，被切的那条连接再也没法重开 —— 活锁**
`abort` 是**一次性**事件，而 `_pipe_range` 的读循环每轮都会看它；段被切走时只置位 `abort`，于是
被切的那条连接一进门就看到 `abort` 已置位而**立刻返回 0 字节** → worker 在 `_segment_worker` 的 while 里
0 字节空转 → 直到 attempts 用尽整段判死 → **整份文件回退单流从 0 重下**。
代码注释记录的实测：**840292 次 `_pipe_range` / 14 秒 / 3 条空转线程**；另一处注释写
**活锁实测 6 万次/秒/线程，能把主线程饿到"未响应"**（`pclpy/core/remote.py`）。

**(2) 调试日志本身成了瓶颈**：旧版一次下载写出 **97.9MB / 111 万行**（见 F7）。

**(3) 探测请求白耗正文**：Range 探测以前发的是 `Range: bytes=0-`（= 请求整个文件），服务端会开始推整份文件，
只能靠 reset 打断；实测正文开销 **64-90KB**。（代码注释 `pclpy/core/remote.py`）

**(4) 单段尝试上限太小**：`MULTI_SEGMENT_ATTEMPTS` 以前上限 6，一次拥塞就会把整段判死 →
整份文件退回单流**从 0 重下**（本地实测**多花 12-33% 字节**）。

#### 修法

* **切段改成「一次性的 abandon 标记 + 重连」**（`_PipeAbandon`）：`abort` 不再进函数入口，只有**正在 read 的连接**会停；
  重试的 `_pipe_range` 能从"上次写到的位置"继续。
* **加段五道刹车片**（关键）：冷却 `MULTI_EXPAND_COOLDOWN = 3.0s`、看疗效 `MULTI_EXPAND_MIN_GAIN = 1.2`、
  连续无收益 `MULTI_EXPAND_NO_GAIN = 2` 次就彻底不再加、单文件生命周期硬上限 `MULTI_EXPAND_MAX = 3`、
  同段连续 0 字节 `MULTI_ZERO_BYTE_LIMIT = 12` 判死该段。
* **单段尝试上限 6 → 12**（`MULTI_SEGMENT_ATTEMPTS`），失败退避 `MULTI_RETRY_BACKOFF = 0.2s` 逐次翻倍封顶。
* **调试日志每秒一条 + 汇总被压条数**（见 F7）。
* **探测只取 2 字节**（`PROBE_PREFIX = 2`，`Range: bytes=0-1`）。
* **全局连接预算**：`MULTI_MAX_CONNECTIONS = 32` 是**唯一**能真正压住并发的开关 —— 调用方想开多少线程都行，
  超出预算的请求在信号量上排队（等预算最长 `MULTI_SEGMENT_ACQUIRE_TIMEOUT = 120s`，防死锁）；
  单文件分片工作线程池 `MULTI_POOL_SIZE = 8`（段在池里排队，线程复用）。
* **规格逐条对照 PCL2 `ModNet.vb`**（`PCL2_ANALYSIS.md` 第一节）：剩余量最大且 ≥256KB 的段切走 **40%**；
  未知大小或 `<1MB` 不分片；`bmclapi / github / optifine.net / momot.rs / pcl2-server / meloong` **禁多线程**；
  416/502/403/429 与合并失败 → **源级禁用** + 全源降级单线程重试。
* **进度不许虚高**：失败回滚字节账本（学 `NetFile.Reset()`）；`.part` 是**稀疏文件**（各段按绝对偏移写），
  所以账本合并必须精确 —— 否则 `sum(seg.written)` 比文件还大（实测出现过
  `MULTIPART INCOMPLETE written=4232052/4194304`，多出 **37KB**）。
* **取消路径干净**：取消后不留目标文件、不留 `.part`。

#### 实测证据（同一台机器、同一注入条件，改前 vs 改后）

来源：`_sub_evidence.txt`（工作区根目录；原始 JSON 由 `_sub_dl_repro.py` / `_sub_stall.py` 产出，
对照跑脚本 `_sub_verify.py`，改前代码取自备份 `pcl_py_sub_20261015-003724`）。

| 场景 | 指标 | 改前 | 改后 |
| --- | --- | --- | --- |
| 停滞注入（服务端中途只吊着连接不吐字节），8 文件 × 4MB | 完成/成功 | `done=2 ok=2 sha1_all=false` | `done=8 ok=8 sha1_all=true` |
| 同上 | 耗时 | **40.05s** | **4.83s** |
| 同上 | CPU | **35.7%** | **11.0%** |
| 同上 | 引擎 stderr 行数 | **628174**（对应文件 101 MB） | **22** |
| 主配置（4MB × 8 文件、8MB/s 总量、`--tick-work 20000`，带进度回调，3 次） | `_pipe_range` 调用次数 | **1404827 – 1583540** | **37 – 38** |
| 同上 | 引擎 stderr 行数 | **1404911 – 1583635** | **12 – 14** |
| 同上 | 耗时 | **12.03 – 12.06s** | **3.19 – 3.20s** |
| 同上 | 完成/成功 | `done=7/8 sha1_all=false` | `done=8/8 sha1_all=true` |
| 同上（不带进度回调） | `_pipe_range` / stderr | **731037 – 1600645** / **731204 – 1600737** | **35 – 38** / **11 – 13** |
| 同上（不带进度回调） | 耗时 | **12.01 – 12.06s** | **3.12 – 3.14s** |
| CPU 直接测量（`time.process_time()`，同配置） | CPU 占比 | **86.2%**（12.11s / 14.05s）、**89.3%**（12.58s / 14.08s） | **14.1%**（0.45s / 3.20s）、**12.7%**（0.41s / 3.19s） |
| 主循环速率（同批跑） | `MAIN_LOOP_TICKS_PER_SEC` | **62.5** | **62.4**（不倒退） |

**吞吐与升级路径（`TODO.md` 记录的实测值）**：6MB → **8 段 sha1 PASS**；
300KB / 无 `Content-Length` → 单流 1 请求；200/416 → 自动退单流；污染段 →
`ROLLBACK bytes_before=196608 bytes_after=0` → 降级单流后 sha1 PASS；取消 → 无目标文件、无 `.part`；
`install_file` 端到端 sha1 OK。

**接口兼容**：`install_file` 只在**末尾追加**可选 `expect_sha1`，调用方签名不变。

---

### 退出与稳定性

> 证据目录：`_exitfix_tmp/logs/`（2026-10-14 22:45 → 22:49 的 `before_run1..6` / `after_run1..6`）。

**X1 退出期 `0xC0000409`（STATUS_STACK_BUFFER_OVERRUN）**
现象：收尾时偶发退出码 `0xC0000409`，stderr 只有一行 `QThread: Destroyed while thread is still running`；
它是**间歇性**的（取决于线程是否刚好跑完），而且 abort 会吞掉已经写好的 stdout（截图路径的 `saved:` 列表）。
根因：收尾那一刻后台 QThread 有可能仍在运行，解释器析构它时 Qt 直接 abort。
修法（`main.py::_exit_now`，三步缺一不可）：
① 用 `findChildren(QThread)` 枚举所有后台线程 → `requestInterruption()` + `quit()` + 限时 `wait()`（总预算 1500ms）；
② `config.save(force=True)` —— 配置平时是"改一次写一次盘 + 600ms 防抖"，事件循环一停那个定时器永远不触发，
   跳过析构会丢最后一次设置改动；
③ 冲刷 stdout/stderr；然后 `os._exit(code)` **跳过所有清理**（atexit / 缓冲刷新 / Qt 析构）。
实测（`_exitfix_tmp/logs/`）：
**改前 6 次里有 1 次**（`before_run4.log`）出现 `QThread: Destroyed while thread is still running` 且那一次进程非正常收尾；
**改后 6 次全干净**（每份日志都以最后一行 `saved: resource-detail-datapack-terralith.png` 结束，没有那行 stderr）。
（代码注释 `main.py`）

**X2 退出期 fail-fast 的反面教材**
根因：诊断用的 `qInstallMessageHandler` 会在**解释器退出期间**被回调 → 导致退出码非 0 的 fail-fast。
修法：移除，改用 `engine.rootObjects()` 判断 QML 是否加载成功。（代码注释 `main.py`）

**X3 QML 连锁失败导致启动即崩 `0xC0000409` 且无任何输出**
根因：① 用脚本删除一个 QML 块时切多了，`Main.qml` 残留两处**语法错误**（孤立的属性块、注释吞掉函数声明）→ 引擎加载失败；
② `PclDialog` 里给 `Text` 加了 `selectByMouse`，而这个 Qt 版本**没有该属性** → PclDialog 不可用 →
HomePage 不可用 → Main 不可用（连锁失败，表现为启动即崩且无任何输出）。
修法：修复语法、去掉不存在的属性。（代码注释 `qml/Main.qml`、`qml/components/PclDialog.qml`）
**教训**：删除/改写 QML 块后必须跑 `tools/smoke.py`（本项目已因为"缺 import / 属性名不存在"静默失败多次，
`TODO.md` 把这条列为硬性流程）。

**X4 主界面卡死（未响应、CPU 占满）—— 一个 QML 循环绑定**
根因：搜索面板里有个 `Text` 写在**没有宽度的 Row** 里并用了 `width: parent.width - 380`：Row 的宽度由子项决定
→ 循环绑定 → QML 陷入死循环。定位方式：逐步打点（每步写一行到文件），定位到 `setPage(1)` 之后的 pump 卡住。
修法：`Row { width: parent.width }` + 显式宽度，修完 4 秒跑完。（代码注释 `qml/components/`）

**X5 上下文属性名和 QML `Item.resources` 撞名**
根因：上下文属性名 `resources` 和 QML `Item` 自带的 `resources` 属性（资源列表）撞名，QML 一律解析到 Item 自己的列表上
→ 所有 `resources.xxx` 都是 undefined（标题显示「搜索undefined」、结果列表空）。
修法：改名成 `community`。实测无任何 QML 报错、30 条结果正常渲染。（代码注释 `pclpy/app.py`）

**X6 无差别清理把别人的探针删了**
根因：清理临时文件时用了不加限定的删除。
修法：**只删自己的 `_*`**。这条已写进 `TODO.md` 的硬性规则。（`TODO.md`）

**X7 本项目 "缺 import 静默失败" 已有 4 次**
做法：新增代码先确认该文件已 import；线程里的异常必须打印、不许被 `except Exception` 静默吞掉。
（`TODO.md`；`import os` 事故见 D1；`pclpy/backend/download.py` 里同样根因的注释）

---

### 打包与分发

**P1 单目录（onedir）冻结版打出来**：`craftpilot_20261015.zip` → `craftpilot_20261015_exe\`
（`CraftPilot.exe` + 同级 `_internal\`，**必须整目录解压**）；构建环境
Windows 10 19045 / Python 3.8.10 / PySide6 6.6.3.1 / PyInstaller 6.11.1；版本号 CraftPilot 1.0.0、构建日期 2026-10-15。
（`README_分发.txt` 附节；工作区根目录现存该 zip 与对应的 exe 目录）

**P2 分发说明面向外测**：`README_分发.txt` 给出 T1–T6 六项任务（流畅性 / 功能闭环 / 日志刷屏 / SSL 报错 /
下载速度硬指标 / 其他）、结果表格模板、以及需要的反馈材料清单。
**合格线可当验收口径**：不出现"未响应"；进度到 100% 且版本出现在列表、能启动；
`pclpy_launch.log` 行数**几十行量级**；不出现 `SSL` / `DECRYPTION_FAILED_OR_BAD_RECORD_MAC` / `SINGLE GIVE UP`；
平均速度 **≥ 本机带宽 25% 且 ≥ 10 Mbps**（带宽 <40 Mbps 时只看 25%）。

**P3 下载速度可调四档验证法**：① 默认 → ② 段数 16 / 并发 64 → ③ 再加分片阈值 0 → ④ 环境变量
`PCLPY_DOWNLOAD_SEGMENTS=0` 单流对照；判读规则：②③ 明显更快 = 单连接被限速，④ 反而最快 = 我们的并发策略有问题，
四档一样慢 = 上游对总量限速。（`README_分发.txt` T5）

---

## 当前状态与验证结果

| 项 | 值 | 出处 / 复现方式 |
| --- | --- | --- |
| 核心离线测试 | **211 OK / 0 FAIL** | `python tests/test_core.py` |
| 界面自检 | `SMOKE PASS` + 运行期 QML 错误 **0** | `python tools/smoke.py` |
| 截图 | **14 张**（含两张资源详情页） | `python main.py --shot shots`；`shots/` 下 14 个 PNG |
| 隔离判定顺序 | 单版本标记 > 旧 json 标记 > `mods`/`saves` > 全局 > PCL 档位 > 加载器兜底 > 关闭 | `pclpy/core/launch.py` |
| 下载分片默认值 | 阈值 1MB / 起步 4 段 / 上限 8 段 / 全局 32 连接 / 低速阈值 1024 KB/s | `remote.py` + `config.py` + `OtherSettings.qml` 三处一致 |
| 已知环境噪声 | `--shot` 收尾偶发 `QThread: Destroyed while thread is still running` 或拆解期崩溃（早于相关改动即存在，非某次改动引入）；14 张图均在崩溃前写出 | `TODO.md` 的未决项记录 |

**注意（三处默认值必须一起改）**：`pclpy/core/remote.py` 顶部常量、`pclpy/core/config.py` 的 `DEFAULTS["download"]`、
`qml/pages/settings/OtherSettings.qml` 的 `downloadTuningDefault()` 字面量 —— 改默认值要三处同步。
（代码注释 `pclpy/core/remote.py`）

---

## 未能取证、因而未写入正文的条目

以下数字**未能在仓库内取证**（没有备份锚点、没有代码注释、没有实测记录文件），
按「不编造」的原则**不写进正文**，在此如实列出，供后来者补证后再收编：

1. **`_pipe_range` 「150 万次 → 35 次」**：本文实测到的是 **1404827 – 1583540 → 37 – 38**（见上文实测证据表）。
   上限 1583540 与「150 万」可能是同一个观测。若上游记录指的是另一台机器/另一次跑，需要原始 JSON 才能对齐。
2. **日志「158 万行 → 12 行」**：本文实测到的是 **1404911 – 1583635 → 12 – 14**（同批跑）。同 1。
3. **「CPU 86% → 13%」**：本文实测到的是 **86.2% / 89.3% → 14.1% / 12.7%**（`time.process_time()`）。
   13% 与实际 12.7% 接近，但为免"对号入座"仍以实测值为准。
4. **任务模型更新「217 → 13 次/秒」**：**未取证**。当前代码里能查到的是
   `pclpy/backend/models.py` 的「单次更新 30ms 上下、峰值 1.3s」与 `pclpy/backend/workers.py` 的
   「界面每秒只能处理 11 次左右」；全工作区（含备份、脚本、文本记录）搜不到 217/13 这组数字。
5. **「整合包元组解包导致线程全死：『16 个 mod』变 143 个」**：**未取证**。
   元组解包事故本身有据（D5，代码注释 + 测试 docstring）；但「16 个 mod」这个具体数字在
   备份、脚本、注释、文档里都找不到，而 **143 个 mod** 是**另一次**成功的端到端实测（F6）。
   很可能是两件事被并成了一句话，故只用有据的写法。
6. **整合包占位竞态（F1）的验证未沉淀**：验证脚本是一次性的，没有并入 `tests/test_core.py`（`TODO.md` 记着这条）。
7. **`pcl_py_discarded_20261014_0313` 的废弃原因**：只知道它被标记为 `discarded`，没有配套说明，故不写。
8. **代码可读性治理相关的条目**：尚未落地，属于未来计划，故不进本日志（记在 `TODO.md`）。

---

## 如何自行验证

三条命令都**不需要联网**（`tests/test_core.py` 全程 0 次真实网络请求），在仓库根目录执行即可：

| 命令 | 用途 | 通过判据 | 产物 / 位置 |
| --- | --- | --- | --- |
| `python tests/test_core.py` | 核心逻辑离线测试：路径/配置、版本扫描与继承链、命令行组装、下载校验与复用、整合包安装、导出等 | `[OK]` 行 **211** 条、`[FAIL]` **0** 条，末尾打印 `ALL CORE TESTS PASSED` | 无文件产物，结果打在 stdout |
| `python tools/smoke.py` | 界面自检：加载 QML、逐页切换，捕获运行期 QML 报错 | 输出含 **`SMOKE PASS`**，且运行期 QML 错误为 **0** | 无文件产物；加 `--anim` 可另查页面切换动画 |
| `python main.py --shot shots` | 离屏渲染 14 个界面为 PNG 后退出 | `shots/` 下 **14** 张 PNG（含两张资源详情页），stdout 有 14 条 `saved:` | 截图写在 `shots/` 目录 |

日志与截图的位置：

* **游戏进程日志**：`<游戏目录>/versions/<版本id>/pclpy_launch.log`；版本目录不可写时退回 `<配置目录>/logs/<版本id>.log`。
* **界面内日志页**：启动器「日志」页，最多保留最近 500 行，页面上有「复制全部」。
* **截图**：`python main.py --shot <目录>` 的输出目录（仓库内为 `shots/`），14 张中含
  `resource-detail-mod-sodium.png`、`resource-detail-datapack-terralith.png`。
* **配置目录**：默认 `~/.pclpy`，可用 `--home <目录>` 或环境变量 `PCLPY_HOME` 指定；对照测试请各用一个独立目录。
* 跑测试与截图时建议带上 `PYTHONDONTWRITEBYTECODE=1`：否则会生成内嵌本机绝对路径的 `.pyc`
  （`.gitignore` 已排除 `__pycache__/` 与 `*.py[cod]`，仓库里不应出现这些文件）。

> 本节三条命令的结果，就是上文「当前状态与验证结果」表里那三行的来源。

---

*本文件所有条目均可按括号内的出处复核；完整备份的清单与用途见 [`DOCS_BACKUPS.md`](DOCS_BACKUPS.md)。*
