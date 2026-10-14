# PCL2 源码对照笔记

> 目的：对照 PCL2（`workspace\PCL`，VB.NET）的做法，找出我们（`pcl_py`）值得改进的地方。
> 由 4 个并行子代理分别阅读源码后汇总，所有结论都带 `文件:行号`。
> ⚠️ 读源码阶段**不改代码**，等结论确认后再动手。

---

## 一、下载器 / 任务进度 / 重试（已完成）

### PCL2 的做法

| 维度 | PCL2 实现 |
| --- | --- |
| 执行单元 | **全局单一下载引擎** `NetManagerClass`（`ModNet.vb:1639`），所有文件按 LocalPath 全局去重（`ModNet.vb:1646,1822`）；不是"每任务一个线程" |
| 并发 | `NetTaskThreadLimit = ToolDownloadThread + 1`，默认 **64**，上限 256（`ModNet.vb:311-315`） |
| 调度 | 两个 20ms 轮询线程按 `Uuid Mod 2` 分工（`ModNet.vb:1719-1772`）；仅当**全局速度低于下限**才给"进行中"文件追加线程（`ModNet.vb:1747`） |
| 分片 | 单文件分段；剩余量最大且 ≥256KB 的段切走 40%（`ModNet.vb:857-862`）；`未知大小 或 <1MB` 不分片（`ModNet.vb:674-678`）；bmclapi/github/optifine.net 等**禁用多线程**（`ModNet.vb:853-854`） |
| 进度 | 字节级（每 16KB，`ModNet.vb:991,1034`）+ **状态机分段映射**：连接 2% / 读取 4% / 下载 5%~98% 带 `1-(1-p)^0.9` 缓动 / 合并 99%（`ModNet.vb:728-752`） |
| 速度 | **单点计算**：三层都是 200ms 增量记速（`ModNet.vb:522-532,708-718`）；全局用**最近 30 次采样（≈3s）线性递减加权**（`ModNet.vb:1683-1696`），并有"只升不降"的下限（`ModNet.vb:1697-1703`） |
| 剩余时间 | **没有 ETA** —— UI 只有百分比/速度/剩余文件数/线程数（`PageSpeedLeft.xaml.vb:44-53`） |
| 重试 | 元数据三段式重试 10s→30s→4s，403/404 直接放弃，429 先等 10s（`ModNet.vb:44-88`） |
| 超时 | 动态：`Min(Max(连接均值,15000)*(1+失败次数), 30000)`（`ModNet.vb:909`）；>5s 且 <1KB/s 主动断线重连（`ModNet.vb:1025-1028`） |
| 源级失败 | 合并失败/不支持 Range(416)/502/404/403/429/连续失败 → **禁用该源**（`ModNet.vb:1079-1099`） |
| 两轮兜底 | 所有多线程源都废后，把全部源降级为**单线程重试一次**（`ModNet.vb:1105-1120`） |
| 校验 | 合并前后做**哈希/大小校验**，失败回到"源失败"（`ModNet.vb:1204-1219`）；失败时把各线程区间/已下载量写日志（`ModNet.vb:1214-1217`） |
| 多任务 | 支持并行，但**共享同一线程池**，同路径文件跨任务合并为一个对象（`ModNet.vb:1822-1835`）；任务树 = `LoaderCombo` 串行 + `Block`/`Show`/`ProgressWeight`（`ModLoader.vb:584-667`） |
| 取消 | 卡片按钮 → `Loader.Cancel()` 逐文件取消（`ModNet.vb:1621-1631`）；支持"重启任务"语义（`ModLoader.vb:283-380`）；**没有暂停** |

### 值得借鉴

1. 下载前先在本机找**同哈希文件直接复制**（`ModNet.vb:1474-1564`）→ 避免重复下载
2. **全局限速令牌**每 100ms 注入，兼作"是否扩线程"的信号（`ModNet.vb:996-1000,1779`）
3. 分段只存**内存账本**，失败点原地续传；`Reset()` 回滚已计字节，保证进度不虚高（`ModNet.vb:1147-1156`）
4. 大文件 >50MB 预检磁盘空间（`ModNet.vb:951-961`）；损坏缓存自动清理（`ModNet.vb:1804-1816`）
5. `IsBadNetwork` 区分"网络问题"与"程序 bug"，UI 层对超时类降噪（`ModNet.vb:286-290,1596`）

### 与我们的差异（也是我们 bug 的根因）

| 维度 | PCL2 | 我们 |
| --- | --- | --- |
| 执行单元 | 全局单引擎 + 每文件分段线程 | 每任务一个 QThread worker |
| **速度** | 引擎侧**单点**统一算（200ms × 30 点加权） | **每行各自定时器**（0.7s 字节增量）✗ |
| 剩余 | 无 ETA，用"剩余文件数" | `remainingText` 按剩余文件数（一致 ✓） |
| 进度 | 状态机分段 + 权重加权 | 每行 percent + 5 阶段 steps |
| 分片 | 动态分段 + 原地续传 + 校验拼接 | 单流 `.part` → rename，无分片 |
| **失败语义** | 单文件失败**即整体失败**，但把源/镜像/单线程重试**穷尽** | 单文件失败**不中断**，最后只提示"N 个失败" ✗ |

**结论（子代理给出）**：我们的"速度不显示 / 进度回退 / 只拿到失败计数"三个问题，根因正是
**per-row 计时器 + 字节账本不可回滚 + 失败不停整体**。

### 建议优先级（若只做一项，选 1）

1. **速度改为单点计算 + 时间窗口**（全局 `DownloadDone` + 采样窗口；任务行只读该值；废掉 per-row 定时器）
2. **进度账本可回滚**（重试/换源前把已计字节减掉）+ 进度改状态阶段映射
3. **镜像回退升级为"源级禁用 + 一次性全源单线程重试"**，并给备用源加 30s/60s 定时切换

## 二、整合包安装（已完成）

主文件：`PCL\Plain Craft Launcher 2\Modules\Minecraft\ModModpack.vb`（860 行）

### PCL2 的做法

| 维度 | PCL2 实现 |
| --- | --- |
| 支持格式 | **6+ 类**：CurseForge(`manifest.json`)、HMCL(`modpack.json`)、MultiMC/Prism(`mmc-pack.json`)、MCBBS(`mcbbs.packmeta`)、Modrinth(`modrinth.index.json`)、"带启动器的压缩包"（`ModModpack.vb:40-73`） |
| 识别容错 | 一级目录包裹容错 ✓；非整合包 zip 走"正则探测 `versions/X/X.json`"的普通客户端包路径（`:820-833`）✓；rar 明确报错（`:77-78`）✓ |
| 安装流程 | Modrinth 例：读 `dependencies`（`:380-396`）→ 定实例名（`:398-404`）→ 任务树 = [整合包安装(`Block=False`), 游戏安装, 最终整理]（`:462-486`）✓ **两件事并行** ✓ |
| 文件落地 | 整包解压到临时目录 + 复制 `overrides` / `client-overrides` 到版本目录（`:408-417`）✓；`overrides` 允许是 `.`（`:209`）✓；有目录穿越校验（`:439-443`）✓ |
| **版本 json** | `MergeJson` 把原版+加载器**平铺合并成单个 json** ✓ 并**显式删除 `inheritsFrom`**（`ModDownloadLib.vb:2144`）+ 复制原版 jar（`:2151`）→ **完全自包含、不用版本继承** |
| 加载器 | **全部自动装、无 UI 交互** ✓：Forge/NeoForge 走官方 installer + 内嵌注入器 + Java 自动选择/下载 ✓；Fabric 只下 meta profile ✓ |
| 加载器缺失 | Forge 会**拉列表比对**并抛"未能找到 Forge `<mc>-<ver>` 的详细信息" ✓；NeoForge/Fabric **不校验**，只在下载阶段 404 ✗ |
| 失败处理 | loader 失败 → 弹窗 + 清理半成品版本目录（`:1815-1829`）✓；已有 `saves`/`versions` 则不删 ✓ |
| **隔离** | **安装时强制隔离** ✓：向 `versions\<名>\PCL\Setup.ini` 写 `VersionArgumentIndie=1` + `VersionArgumentIndieV2=True` ✓（`:121-144`）——作者无法关闭 ✓；**顺序关键**：必须在"决定 mods/saves 路径"之前写入（`ModDownloadLib.vb:1968` 注释：版本隔离信息在此时被决定 ✓） |
| 命名 | 取包内 `name` ✓；非法则弹窗输入 ✓；**无后缀、无自动编号** ✓；同名版本已存在 → **直接报错取消**（`ModDownloadLib.vb:1908-1911`）|
| 可选文件 | Modrinth `env.client`：`optional` → 询问 ✓、`unsupported` → **跳过** ✓（`:421-432`）；CF `required=false` → 询问 ✓ |

### 与我们的差异

| 维度 | PCL2 | 我们 |
| --- | --- | --- |
| 格式 | 6+ 类 | 仅 `.mrpack` ✓（我们额外做了"误选 Mod jar 自动识别"✓，PCL2 没有 ✓） |
| 版本 json | **平铺合并 + 删 `inheritsFrom`**（自包含但重复占空间 ✓） | 用 `inheritsFrom` 指加载器版本 ✓（**更省、更贴规范** ✓ —— 子代理评价 ✓） |
| 加载器 | Forge/NeoForge/Fabric/OptiFine/LiteLoader，**无 Quilt** | Fabric/Quilt/Forge/NeoForge + OptiFine 安装器 ✓ |
| **隔离** | 安装时**写死实例标记** ✓ 且在决定路径之前 ✓ | 只靠 modded 启发式 ✗ |
| **校验** | mrpack 的 `sha1` 会校验（`ModModpack.vb:445`）✓ + 下载前查 ContentLength ✓ + 合并后校验 ✓ | **完全不校验** ✗（坏源会静默留下损坏文件 ✗） |
| 同 hash 复用 | 下载前扫描所有实例按 size+hash 找同文件**直接复制** ✓（省几 GB ✓） | 无 ✗ |
| `env.client` | `unsupported` 跳过 / `optional` 询问 ✓ | 忽略 ✗（可能下到客户端不支持的文件 ✗） |
| 同名冲突 | 直接报错取消 ✗ | 自动加 `-2` 后缀 ✓（更友好 ✓） |

### 建议优先级（性价比排序）

1. **索引校验 + 本地同 hash 复用**：mrpack 自带 `sha1/sha512` ✓ —— 现在裸 8 线程下载**不校验** ✗，坏源会静默留下损坏 jar ✓；顺带加"扫描已有实例按 hash 复制" ✓
2. **整合包实例显式隔离标记**：安装时写死 per-instance 标记 ✓，并确保在"决定 mods/saves 路径之前"写入 ✓（不要只依赖 modded 启发式 ✗）
3. **`env.client` 规范 + 可选文件开关**：`unsupported` 跳过 ✓、`optional` 询问 ✓；并给"加载器版本不存在"做前置校验与可读提示 ✓、加"未完成标记"以免半成品实例出现在列表 ✓


## 三、版本隔离（已完成）

源码版本：PCL2 **2.13.1.1**（`ModBase.vb:9`）。唯一实现点：`McInstance.PathIndie`（`ModMinecraft.vb:227-266`）。

```
PathIndie = If(Settings.Get("VersionArgumentIndieV2", Instance:=Me), PathVersion, McFolderSelected)   ' :264
```
隔离时 = `<root>\versions\<id>\` ✓；不隔离 = `<root>` ✓ —— **这条与我们完全一致** ✓✓

### PCL2 的规则

| 层级 | 键 | 取值 / 默认 | 位置 |
| --- | --- | --- | --- |
| 全局默认 | `LaunchArgumentIndieV2` | **0..4，默认 4 = 隔离所有版本** ✓（`Settings.vb:95`）；语义：0 关闭 / 1 仅隔离可装 Mod / 2 仅隔离非正式版 / 3 非正式版+可装 Mod / 4 全部隔离（`ModMinecraft.vb:249-260`） | `<启动器目录>\PCL\Setup.ini` |
| **单版本（真正生效）** | `VersionArgumentIndieV2` | 布尔；**存在即最终答案** ✓；不存在则自动判定（`ModMinecraft.vb:229-264`） | **`versions\<id>\PCL\Setup.ini`** ✓ |
| 遗留单版本 | `VersionArgumentIndie` | -1 未决定 / 0 跟随全局 / 1 手动开 / 2 手动关（`ModMinecraft.vb:234-237`） | 同上 |

**自动判定顺序**（无 V2 键时，`ModMinecraft.vb:232-261`）：
1. 遗留 V1 > 0 的手动值优先；
2. **版本文件夹里已有 `mods\`（含文件）或 `saves\`（含子目录）→ 强制隔离** ✓；
3. 否则用全局 `LaunchArgumentIndieV2`（默认 4 = 全部隔离 ✓）。

**"可装 Mod" 判据**（`Modable`，`ModMinecraft.vb:303-309,745-780`）：对**合并后**的 JSON 文本做子串匹配
（`net.fabricmc:fabric-loader` / `org.quiltmc:quilt-loader` / `minecraftforge` / `net.neoforge` / `liteloader`）
**或** 用户手动把版本标成 `DisplayType=2 (API)` ✓ —— 不是只看 mainClass ✓。

**其它**：整合包安装**显式强制隔离**（写 `VersionArgumentIndie=1` + `VersionArgumentIndieV2=True`，`ModModpack.vb:132-142` ✓）；反向：根目录整合包自动**关闭**隔离（`PageSelectLeft.xaml.vb:221-240` ✓）；PCL2 **不允许同名重复版本**（同名直接报错取消 ✓）✓。

### 值得借鉴

1. **只隔离用户数据，不隔离大缓存** ✓：`assets`/`libraries` 永远指向根 ✓（`ModLaunch.vb:1524-1540`）✓；`appdata` 环境变量也重定向到根 ✓
2. **正交维度**：(是否正式版, 是否可装 Mod) 两个布尔组合出 5 档 ✓，把"非正式版"单列为 2/3 档 ✓
3. **一次性 Decide & Freeze** ✓：判定结果写回版本自己的 ini ✓，之后不受全局设置影响 ✓（全局改动只影响新装版本 ✓）
4. **关键 UI 都有解释/劝告** ✓：改隔离前警告"存档看似消失、改回可恢复" ✓；装带加载器版本时若全局未开隔离则劝阻 ✓
5. **崩溃日志同时兼容两种布局**（隔离目录 + 根目录 ✓）

### 与我们的差异（按重要性）

| # | PCL2 | 我们 | 建议 |
| --- | --- | --- | --- |
| 1 | 全局默认 **4 = 隔离所有版本** ✓ | 兜底是"**带加载器就隔离**" ✗ | 缺省兜底改为 **open** ✓（与 PCL 默认一致 ✓）；2/3/4 → open ✓、1 → mod ✓、0 → close ✓ |
| 2 | **单版本键存在即最终答案** ✓ | 只读全局键 ✗ | 加入优先级：显式 cfg > 单版本 V2（存在即采用）> 单版本遗留 V1>0 > 我们的启发式 > 全局键 > 默认 open ✓ |
| 3 | 三条自动规则（`mods/saves` 存在→强制隔离 ✓；根目录整合包→强制不隔离 ✓；整合包安装写死标记 ✓） | 都没有 ✗ | 至少补前两条 ✓ |
| 4 | `Modable` 判据基于**合并后** JSON ✓ + 用户手动 API 标记 ✓ | 只判自身 json ✗（继承自 Forge 的副本会被误判 ✗） | 先做 `inheritsFrom` 链合并再判 ✓ |
| 5 | 无"非正式版"维度 | 三态 open/mod/close ✓（更易懂 ✓ 子代理评价"保留即可" ✓） | 保留三态 ✓，只把空值解析改对 ✓ |
| 6 | 版本级元数据放 **`versions\<id>\PCL\Setup.ini`** ✓，版本 json 保持纯净 ✓ | 我把 `pclpy:isolate` **写进了版本 json** ✗ | **改为写 `versions\<id>\PCL\Setup.ini`** ✓，并**同时写 PCL 兼容键**以便两个启动器互认 ✓ |
| 7 | 复制/重命名**沿用**源版本的隔离标志 ✓，不因复制而强制隔离 ✓ | 我做成"副本强制隔离" ✗ | ⚠️ **这是你明确要求的行为** ✓ → 建议保留你的选择 ✓，但把标记写进 ini（见 #6 ✓）+ 首次给一次提示 ✓ |



## 四、版本命名 / 安装 / 重命名（已完成）

### PCL2 的做法

**命名**（`PageDownloadInstall.xaml.vb:412-420`）：默认名只是输入框初值 ✓，落盘用输入框文本 ✓，目录/json/id 三者同名 ✓。

| 加载器 | 命名规则 |
| --- | --- |
| 原版 | `<mc>` |
| Fabric | `<mc>-Fabric <ver>`（**空格** ✓） |
| Forge | `<mc>-Forge_<ver>` |
| NeoForge | `<mc>-NeoForge_<ver>`（砍掉 `+snapshot-1` 后缀 ✓） |
| OptiFine | `<mc>-OptiFine_<ver>`（空格→下划线 ✓） |
| LiteLoader | `<mc>-LiteLoader` |
| **Quilt** | **不支持安装** ✗（整合包带 quilt 直接提示不支持 ✓） |

**名字校验**（`ModValidate.vb:259-311`）：1–100 字符 ✓ 禁 `!;%` 与非法字符 ✓ 不能以空格/点结尾 ✓ 禁 `CON/PRN/LPT…` 保留名 ✓ 禁 NTFS `~数字` 短名 ✓ **与现有版本重名直接报错**（不加 `(1)` 后缀 ✓）。

**重复安装 + 自定义名** ✓：**不是复制目录** ✗，而是**重新执行一次完整安装** ✓ 装进新名字的目录（`ModDownloadLib.vb:1908-1911` 重名即取消 ✓）；产物自包含 ✓（`MergeJson` 把父 json 全部字段合并 → 删 `inheritsFrom/jar` → `id` = 目录名 → 复制原版 jar ✓，`:2110-2151` ✓）。
另外它有**"已存在文件查找 + 本地复用"** ✓（`ModNet.vb:1474-1563` ✓：assets/libraries 按同路径+大小/hash 复用 ✓，`versions\` 下跨所有实例按大小+hash 找同款文件直接复制 ✓）—— 但客户端 jar 因 `Size=0` 的坑基本命中不了 ✗，仍会重下 ✓。

**重命名**（`PageInstanceOverall.xaml.vb:105-158`）：移动目录 ✓ → **只改三个确切名字**（`<old>-natives` 目录、`<old>.jar`、`<old>.json` ✓，**绝不遍历替换** ✗ ← #6443 的教训 ✓）→ 替换 `PCL\Setup.ini` 里的旧绝对路径 ✓ → json 改 `id` 后**先删旧再写新** ✗（小概率丢 json ✗）→ **`inheritsFrom` 完全不动** ✓（**不扫描子版本** ✗ → 有子版本引用时子版本立即失效 ✗，只报"需要安装 X 作为前置版本" ✓）。

### ⚠️ 对我们实现的严重警告（子代理原文要点）

> **"清空 `inheritsFrom`"只有在 json 已经合并了父版本全部字段时才安全** ✗。
> PCL2 敢清，是因为它清之前先 `OutputJson = MinecraftJson` 再逐层 Merge（`ModDownloadLib.vb:2110-2140` ✓）。
> 如果只是把 `<old>.jar` 改名为 `<new>.jar` 就把 `inheritsFrom` 去掉 ✗，得到的 json 里**只有加载器自己那部分** libraries/arguments ✗，缺原版库与 natives、缺原版启动参数（Forge 的 `--fml.*`/`--launchTarget`、`minecraftArguments` 都在父 json ✓）→ **游戏会启动失败或行为异常** ✗✗

对我们的影响分析：
* **原版副本**：原版 json 本身就是完整的 ✓（libraries/assetIndex/mainClass 齐全 ✓）→ 清 `inheritsFrom` **安全** ✓
* **加载器副本**：我们的 `copy_version_as` 只在"目录里有 `<old>.jar`"时才清 `inheritsFrom` ✓ —— 加载器版本目录通常**没有** jar ✓ → **会保留 `inheritsFrom`** ✓ → **不会触发这个启动失败** ✓✓ 但代价是：**加载器副本不是真正独立** ✗（父版本被删/改名就失效 ✗）——与你要的"两份独立示例"有差距 ✗

### 其它差异

| 维度 | PCL2 | 我们 |
| --- | --- | --- |
| 自定义命名 | 重新安装 + 合并出自包含 json+jar ✓ | `copytree` 整个目录（连 mods/saves/PCL 配置一起复制 ✓）|
| 磁盘占用 | 每版本 ≈ json + jar ✓ | 每副本 = 整目录字节（含完整 client jar ~20-30MB ✓，mods/存档也翻倍 ✗）|
| 版本级元数据 | 全在 `versions\<id>\PCL\Setup.ini` ✓（json 保持对 Mojang 纯净 ✓） | 我把 `pclpy:isolate` 写进 **json** ✗（其它工具可能视为非法字段 ✓/重装导出时丢失 ✓）|
| 命名前缀 | Fabric 用**空格** ✓、其它用下划线 ✓ | 我们统一下划线 ✓（子代理建议保持统一 ✓）|
| 重名冲突 | 直接拒绝 ✓ | 我们自动加 `-2` 后缀 ✓（更友好 ✓ 但与 PCL 不同 ✓）|
| 安装中占位 | `.pclignore` 占位 ✓ + 失败清理 ✓ | 无 ✗（半成品可能出现在列表里 ✗）|

### 建议（性价比排序）

1. **加载器副本要真正独立**：做一次 **json 递归合并**（把父 json 的 `libraries`/`arguments`/`mainClass`/`assetIndex`… 合并进来 ✓）+ 复制父版本的 client jar ✓，**之后**才清 `inheritsFrom` ✓（照 PCL2 `MergeJson` 的思路 ✓）—— 否则保持现状（继承 ✓，但会在父版本改名/删除后失效 ✓，需给用户提示 ✓）
2. **版本级元数据改存 `versions\<id>\PCL\Setup.ini`** ✓（把 `pclpy:isolate` 从 json 里搬出来 ✓），并**同时写 PCL 兼容键** `VersionArgumentIndieV2=True` ✓ → 两个启动器互认 ✓、版本 json 保持纯净 ✓
3. **改名后扫描子版本引用** ✓（PCL2 的短板 ✗）：若有版本 `inheritsFrom` 指向被改名/删除的版本 ✓ → 明确提示或同步更新 ✓
4. **安装中占位标记 + 失败清理** ✓（避免半成品出现在列表 ✓）
5. 命名统一（下划线 ✓、截断 `+` 后缀 ✓）+ 冲突处理保留"自动后缀" ✓ 但提示更明确 ✓

---

## 附：改造方案草案（**待用户批准后再动代码**）

### A. 速度改为单点计算（对应建议 1）

* 在 `LauncherBackend` 里维护**全局字节账本**：`self._bytes_total`（累计已下载字节）。
* worker 侧统一改走一个入口：`add_bytes(delta)` → 累加到全局账本（用锁），worker 自己不再算速度。
* 保留现有的 `_speed_timer`（0.7s ✓ 或改成 0.2s 对齐 PCL2 ✓）**只算一个全局速度**：取最近 N 次采样做加权平均（PCL2 是 30 点递减加权 ✓）。
* 任务行 / 左栏「下载速度」都读这个全局值 ✓；`remainingText` 继续按剩余文件数 ✓（与 PCL2 一致 ✓）。
* 顺带修正：**速度不显示**的根因消失 ✓（不再依赖某个文件回调是否稀疏 ✓）。

### B. 字节账本可回滚（对应建议 2）

* `TaskWorker.add_bytes(delta)` 增加负数支持 ✓；重试/换源前先 `add_bytes(-已计字节)` ✓（学 `NetFile.Reset()` ✓）。
* 每次重试记录 `stream["last"] = 0` ✓（现有代码已有类似结构 ✓，只需在重试分支里回滚 ✓）。

### C. 失败语义对齐（对应建议 3，较大 ✗ 建议缓做）

* 单文件失败 → 先穷尽"换源重试"（源级禁用 ✓），仍失败才让整个任务失败 ✓；
* 现状"N 个文件下载失败"改为"失败清单 + 可一键补下" ✓（更接近 PCL2 的"失败即整体失败但重试穷尽" ✓）。

