# 待办清单（唯一事实来源）

> 顺序（用户明确）：**A → B → C → D**。A、B、C 已完成；**当前进行中：D 阶段（代码可读性治理，由另一个代理执行，本清单只登记状态、不动代码）**。
> 历史改动（哪一轮改了什么、实测数字多少）不在本文件重复，统一看 **`CHANGELOG.md`**（按轮次，含证据出处）。
> 每条改动必须：一次只改一个文件 → `python tools/smoke.py`（SMOKE PASS + 运行期 QML 错误 0）→ `python tests/test_core.py`（全过）→ 备份 `pcl_py_backups\pcl_py_sub_<stamp>`。
> 新增代码先确认该文件已 import（本项目已 4 次因缺 import 静默失败）。
> 绝不用中文正则过滤命令输出（GBK 丢字符）；pwsh 不支持 heredoc，临时脚本用 write 写成 `.py`。
> **清理临时文件时必须限定"只删自己的 `_*`"**（曾有无差别删除把别人探针删掉）。

---

## A 阶段 ✅ 已完成（已复核）

- A1 重命名对话框：根因 = `onPositiveClickListener` 被当**属性绑定**在**构造期**求值 → `accepted()` 提前发出。已加 `confirmArmed` 闸门。
- A1b 追加：校验失败时对话框不再被 vendor 的 `control.close()` 追着关掉 → 红字可见。改用**函数字面量**接管 listener。
- A2 服务端大类子组标题补游戏版本（`服务端 1.8.9`）。
- A3 `remote.py` facet 映射：`"全部"` 不再塞进 facet；`plugin` 及各类别名归一（原来会静默按 mod 搜）。
- A4 新增 `test_modpack_install_regression`（19 条、离线、0 网络），并把 `core.resources` 补进测试 import。

## B 阶段 ✅ 已完成（复核：smoke PASS + **211 OK / 0 FAIL** + 14 张截图 stderr 零报错）

- B5 加载器标签不再截断（`loaders[:3]`/`[:2]` 全去掉）。
- B3 服务端独占时不挂"数据包版本"假文案（跳转条隐藏）。
- B7 `tools/shots.py` 新增资源详情页截图（`resource-detail-mod-sodium.png`、`resource-detail-datapack-terralith.png`），离线也能出图。
- B8 关窗期 19 条 `of null` 全部清零：`OtherSettings.qml`（16 处）+ `VersionExportPage.qml`（4 处）加空安全，回落值逐个对齐 `config.py` 的 DEFAULTS。
- B2 `.mrpack` 的 `env.client=unsupported` 文件跳过（不计失败/未完成）。
- B4 Forge/NeoForge 也写 `.pclpy_installing` 占位（监视 versions/ 新目录）。

### B 阶段遗留 ✅ 本轮已全部完成
- **B0 ✅ 多连接分片下载（PCL2 式）** —— `core/remote.py`：Range 分段；在"剩余最大且 ≥256KB"的段上切走 **40%**；未知大小或 `<1MB` 不分片；bmclapi/github/optifine.net/momot.rs/pcl2-server/meloong 禁多线程；小文件内存拼装；**失败回滚字节账本**；拼接前后 sha1/大小校验；416/502/403/429 与合并失败 → 源级禁用 + 全源降级单线程重试。接口只**末尾追加**可选 `expect_sha1`（调用方不变）。实测：6MB→8 段 sha1 PASS；300KB/无 Content-Length→单流 1 请求；200/416→自动退单流；污染段→`ROLLBACK bytes_before=196608 bytes_after=0`→降级单流后 sha1 PASS；取消→无目标文件、无 `.part`；`install_file` 端到端 sha1 OK。
- **B1' ✅ 本地整合包导入补命名对话框** —— `Main.qml` 新增 `modpackDialog`（默认名只在 `onOpened` 填、重名走后端 `download.validateVersionName` 自动避让 `-2`、失败时红字留屏）；实测 22 项：选完文件**不自动安装**、取消=不装、确定=**恰好 1 个任务**、重名红字 **449** 危险色像素可见。
- **B3' ✅ 服务端独占时的跳转条文案** —— 后端 `_switch_text()` 给出 `switchText`（客户端两句**逐字保留**）；实测 essentialsx（纯服务端）显示相符文案、luckperms/terralith 逐字不变、老数据无 `switchText` 时 QML 回退原句。
- **B4' ✅ Forge 占位监视竞态** —— 抽出共享 `_forge_watch_matcher` + 新增**零副作用**的 `_forge_watch_new_dirs`；收尾改为「先 join 到线程**真停** → 停稳后补扫并清除」。实测：目录在最后一次轮询之后出现也能被补扫清除；**对照组用旧代码复现出残留**（证明窗口确实被消掉）；已存在/名字不匹配的目录不受影响；`ok=False` 仍保留占位。
- **B9 ✅ 两个版本页空安全** —— `VersionOverviewPage.qml` / `VersionConfigPage.qml`；确定性探针（删掉 context property 背后的对象后泵事件）实测 **6→0 / 12→0 / 19→0**；外观三重证据（探针 23 OK 逐条一致、像素差 **0/614400**、截图 14/14 同名）。
- **B10 ✅ 给 B2 跳过路径补测试** —— `tests/test_core.py` 新增 ④-5 共 **10 条**断言（unsupported 不下载/不落盘/不计 pending/不计失败/不标未完成、optional 照装、跳过条数在文案可见）；总数 **201 → 211 OK / 0 FAIL**。

### 仍存的小尾巴 → 已归并到下面的「C 阶段遗留」

---

## C 阶段 ✅ 已完成（C1 / C3 / C4 / C5 均已落地；细则见 `CHANGELOG.md` 的 e 轮与 g 轮）

> 约束（当时）：窗口 / 标题栏 / 圆角 / 拖拽 **一律不动**，只改内容区。
> 工具：`python main.py --shot shots` 能拍 14 张（含两张资源详情页）用于逐页核对。

- C1 ✅ 已完成：5 个基础组件换回 FluentUI 版（`PclButton`/`PclCheckBox`/`PclTextField`/`PclComboBox`/`PclSlider`）+ `Main.qml` 补 `import FluentUI` 与 `FluTheme.primaryColor`。
- C2 ✅ 已完成：任务圆环 → `FluProgressRing`（`Main.qml`，替代自绘 Canvas）；折叠 → `FluExpander`（`components/Accordion.qml`）；页面容器 → `FluArea`（`components/Card.qml`、`components/ColorPickerDialog.qml`，圆角 + 1px 描边卡片容器）。
- C2 遗留（未做，按需处理）：取色器仍是自绘 `ColorPickerDialog`（内部已套 `FluArea`），**未**换成 `FluColorPicker`；一级导航仍是 `SideItem`，**未**换成 `FluNavigationView`（已按 `FluNavigationView.qml:22 / 485-488 / 539 / 579-590 / 574` 逐项对齐高度、内缩、圆角、图标尺寸等指标，见 `components/SideItem.qml` 顶部注释）；`FluScrollablePage` / `FluItemDelegate` 未采用。
- C3 ✅ 已完成：资源详情页顶部加「转到 Modrinth」/「复制名称」（`ResourceDetailPage.qml`，与「打开下载文件夹」并排）；PCL2 那排**筛选胶囊**（加载器 / 适配版本）已实现（用**未过滤**的数据收集候选，胶囊不会因筛选而消失）。
- C4 ✅（实现层）已完成：整合包 / 资源包 / 光影包三类详情页共用 `ResourceDetailPage.qml` 的**加载器 → 适配版本 → 文件**两级分组、两级都可折叠、按项目 id 打开并快照筛选条件；数据包区分客户端/服务端两大类。
  - ⚠️ **未取证**：没有找到"逐个对照 PCL2 截图核对"这一步的记录（`shots/` 里只有 `resource-detail-mod-sodium.png`、`resource-detail-datapack-terralith.png` 两张，整合包/资源包/光影包没有截图）。若要做这项核对，需先补截图。
- C5 🔶 部分完成：启动页账号区居中 ✅、启动按钮文字居中 ✅；**标题栏按钮/图标观感未逐项核对**（未取证，维持"未做"）。

### C 阶段遗留（不阻塞 D，按需处理）
- （原 B 阶段遗留，现已归并到这里）本地整合包命名框的默认名用**文件主名**（要读 `.mrpack` 索引里的 `name` 需先给 `community` 加槽位）；选到普通 `.zip/.jar` 也会多弹一次框（确定后走后端既有逻辑）。
- B4' 的竞态验证是一次性脚本，**未沉淀**为永久回归（建议并入 `test_core.py`）。
- `_switch_text` 只覆盖 `mod`/`datapack`；日后新增第三类跳转目标需同步扩 `_SWITCH_LABELS`。
- **环境噪声（改前就有、非本阶段引入）**：`--shot` 收尾偶发 `QThread: Destroyed while thread is still running` 或 `0xC0000409` 拆解期崩溃；14 张图均在崩溃前写出。（主入口的退出收尾已在 g 轮加固，见 `CHANGELOG.md` 第八节。）

---

## D 阶段 · 代码可读性治理（✅ D1 / D2 已完成并取证；D3 已覆盖故跳过；D4 按用户要求不动删除）

> 本轮由代理执行；**公共接口未变**（`from pclpy.backend.launcher import LauncherBackend` / `INSTALL_STEPS` 照旧）。
> 改前备份：`pcl_py_backups\pcl_py_sub_20261015_0249`。
> 每步验收（D1 每删一个函数、D2 每抽一个模块都跑）：`python tools/smoke.py` = SMOKE PASS；
> `python tests/test_core.py` = **211 OK / 0 FAIL**；`python main.py --shot shots` = **14 张、文件名不变、输出里 0 条报错**。

- D1 ✅ 已完成：删除 5 个死函数。删前逐个全项目 grep（含 `tests/`、`tools/`、`qml/`）复核：**除定义处外零引用**，无 `__all__` 导出，无 `getattr`/字符串动态调用。逐个删除、每删一个跑一次 smoke + test_core，5 步全绿。
  - `pclpy/core/launch.py`：`pcl_isolation_flag`(:530) —— 已被 `_per_version_isolation`(:587，多认 V2 与遗留 V1) 取代；`bootstrap_classpath`(:828) —— 已被 `_forge_extra_jvm_args`(:729 起，用 `-DmergeModules` / `-Dfml.modFolders` 把 client+universal 放上 classpath) 取代；`window_titles`(:1273) —— 诊断用，实际在用的是 `set_window_title`(:1186)。
  - `pclpy/core/versions.py`：`installed_versions`(:395) —— 已被 `scan_folder`(:250) 取代；`find_installed`(:438) —— 已被 `select_version`(:395) 取代。
  - 行数变化：`launch.py` **1339 → 1267**（−72）；`versions.py` **459 → 407**（−52）。
  - **更正**：`java_for_version` **不在** `versions.py`，实际在 `pclpy/core/launch.py:198`（`tests/test_core.py` 6 处在用）；它与 `select_version`（`versions.py:395`）一样**未动**。
- D2 ✅ 已完成（保守策略：只抽 2 个模块，**纯搬运**、不改逻辑、注释一字未丢）：`pclpy/backend/launcher.py` **1616 → 1141** 行。
  - 新增 `pclpy/backend/launcher_tasks.py`（292 行，`TaskMixin`）：原「任务管理」整段（`tasksChanged` 信号 + `taskModel` / `taskCount` / `hasRunningTask` / `overallPercent` / `speedText` / `remainingText` + `_new_task`…`clearFinishedTasks`，**268 行**，文本 sha1 `272dc1a26b9bc35def6f2705ffb5f0e2433cf010`）。
  - 新增 `pclpy/backend/launcher_launch.py`（232 行，`LaunchMixin`）：原「Java」+「启动游戏」整段（**212 行**，文本 sha1 `e81fdaec72b7b91cd064eb5137e80d70a2b8593e`）。
  - 兼容入口：`launcher.py` 顶部保留 `from .launcher_tasks import TaskMixin` / `from .launcher_launch import LaunchMixin`，类改为 `class LauncherBackend(TaskMixin, LaunchMixin, QObject)`；ROLES / STEPS 常量**原地未动**；**不加 `__all__`**（不加即导出全部，加了只会缩小导出面）。文件头已写明「本模块是兼容入口」。
  - 实测两个坑（已写进新模块头注释）：① mixin 里**不能写 `__init__`**（会顶掉 `QObject.__init__` 调用链，实测 `RuntimeError`）；② `tasksChanged` 只在 `TaskMixin` 声明**一次**，子类再声明会 shadow 掉它、`@Property(notify=…)` 静默失效。已验证 PySide6 会把 mixin 里的 `@Slot` / `@Property` / `Signal` 注册进元对象（`logLines` 的 `notifySignal()` 仍是 `launchStateChanged()`）。
  - 行为等价证据（A/B：改前 / 改后各自连跑两次）：改前自差 **2/14**、改后自差 **2/14**，A/B 差集**恰好等于**那两张（`settings.png`、`version-settings-config.png`）→ 这 2 页是**改前就存在的非确定性**（Java 扫描时序），与拆分无关；其余 12 页 sha1 全同。证据目录 `_d2_ab_before/`、`_d2_ab_before2/`、`_d2_ab_after/`、`_d2_ab_after2/`（可删）。
- D3 ⏭️ 跳过（判定为「已覆盖」）：治理清单本身就在本段；`CHANGELOG.md:584` 明确写着「D 阶段（代码可读性治理）的任何条目…不进更新日志（进 `TODO.md`）」；`PCL2_ANALYSIS.md` 内 grep `D 阶段|治理|死函数|可读性|D1|D2|D3|D4` = **0 命中**。故不再往 `PCL2_ANALYSIS.md` 写一份重复清单。
- D4 ⏸️ 按用户要求**不做删除**：`pcl_py_backups\pcl_py_discarded_20261014_0313`（在工作树之外的备份目录里）现为 **130 个文件 / 2,338,881 字节 ≈ 2.2 MB**，最后修改 2026-10-14 03:13。等稳定后再决定。README 的最后一次补齐**本轮未做**（属 D4 原描述，留到稳定后与删除一并处理）。

### D 阶段结束时的实测行数（Python 计数，含新模块）

| 文件 | 行数 | 文件 | 行数 |
| --- | --- | --- | --- |
| `backend/launcher.py` | **1141** | `backend/launcher_tasks.py`（新） | 292 |
| `backend/launcher_launch.py`（新） | 232 | `backend/resources.py` | 1024 |
| `backend/workers.py` | 483 | `backend/download.py` | 445 |
| `core/launch.py` | 1267 | `core/versions.py` | 407 |
| `core/remote.py` | 2479 | `core/install.py` | 1290 |
| `core/resources.py` | 972 | | |

> 说明：本清单原先记的 `launcher.py 1458` / `core/launch.py 1137` / `remote.py 2021` 等数字**与磁盘实际不符**（实测分别 1616 / 1339 / 2479），已用上表更正。
> **D2 未做**：`launcher.py` 里「版本与文件夹 / 账号 / 版本详情管理 / Mod 管理 / 导出整合包 / 安装下载」这些段仍留在原文件（任务系统与启动已抽出）。进一步拆分要动 `@Property(notify=…)` 引用的信号，按「宁可少做」原则停在这里。

---

## 已完成（累积清单，供核对）

> 详细轮次与实测数字见 `CHANGELOG.md`。

外壳 PCL2 风格自绘标题栏 + QML 圆角（放弃 Win32 region/mask）；资源检索树（Mods 加载器→正式/快照→游戏版本→资源版本；整合包/资源包/光影 游戏版本→资源版本；数据包客户端/服务端两大类；服务端 游戏版本→核心分区→资源版本；客户端做成大类且加载器含在其内；跳转条只出现一次且置顶；资源自身快照与游戏快照分离）；加载器互斥单选；整合包安装 143 个 mod 端到端实测通过；安装前命名校验/自动避让；安装步骤对齐 PCL2（含 `MODPACK_STEPS`）；整合包实例完全独立（自带 jar + 合并 json，删父版本仍可用）；PCL2 装的整合包能加载 mod（隔离判定顺序修复）；空值不再覆盖父版本；sha1 复用 / 失败重试 / 未完成标记；启动与关闭淡入淡出动画；截图工具支持资源详情页；PCL2 式多连接分片下载（含活锁修复、日志降噪、失败回滚字节账本）；退出期 `0xC0000409` 加固；设置页「下载分片调参」（三处默认值一致：`core/remote.py` / `core/config.py` / `qml/pages/settings/OtherSettings.qml`）。
