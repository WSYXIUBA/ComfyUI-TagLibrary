# ComfyUI-TagLibrary 架构解析与 UI 优化方向

> 基线：**main 分支**，工作区干净，HEAD = `c975520`，版本 **v1.3.0**
> 方法：全仓通读（Python 5,157 行 / 前端 5,302 行 / 数据 4357 标签）+ 数据实测 + 调用点交叉验证
> 本文所有"死代码""零引用"结论均由 grep 计数与可达性分析交叉核对，非猜测

---

## 一、总体定位

| 项 | 事实 |
|---|---|
| 类型 | ComfyUI 自定义节点（无 pip 依赖，纯 Python + 原生 JS） |
| 节点签名 | `[selection_state, mode, seed]` + 可选 `prefix/suffix` → 输出 `(positive, tags_preview)` |
| 标签库规模 | 9 大类 / 63 子分类 / **4357** 标签 |
| 引擎规模 | 12 条拼装轴 / 18 份武器·物品档案 / 50 组全局互斥域 / 34 族 NL 句式 |
| 性能宣称 | 节点执行 1-4ms；10k 库 build p50 1.1ms（`tests/perf_build_test.py` 门禁） |
| 前端体量 | `taglibrary.js` **2668 行 / 134 KB**、`manager.js` 1474 行 / 63 KB、`tagpanel-css.js` 420 行、`manager.css` 525 行 |

**1.3.0 的核心架构决策**（这是理解全部代码的前提）：
> 分类树降级为 UI 浏览皮肤；组合语义由 **拼装轴 + 互斥组 + 资源预算 + 状态槽** 四套机制自动推导；旧的 81 条手写冲突规则退役大半。

---

## 二、代码组织结构

```
ComfyUI-TagLibrary/
├── __init__.py              入口：导出节点映射 + WEB_DIRECTORY + 注册路由
│
├── ── 数据层 ──
├── library.py        600   加载/合并/校验/保存 + 墓碑 + 乐观锁 + 文件夹热同步
├── tagfiles.py       682   .md 解析器 + 文件夹镜像(双向) + 指纹清单
├── schema.py         143   编辑层 v1→v2 只读迁移（补 type/priority/rarity/groups…）
│
├── ── 编译层 ──
├── runtime_snapshot.py 467 冷路径编译 → 只读 RuntimeSnapshot（双缓冲原子替换）
│
├── ── 引擎层 ──
├── engine.py         458   原子档案束抽取 + 资源账本 + 组互斥 + 状态槽
├── axes.py           126   12 条轴定义 + SUB_TO_AXIS 路径映射（决定输出次序）
├── profiles.py       192   武器/物品档案 schema + 校验 + 编译为 PoseEntry
├── grouprules.py      83   全局互斥域（组名→成员词），独立文件免疫重导入
├── tagconflicts.py   373   跨池结构性规则 + 引用解析 + 选择体检
├── nl.py             212   NL 尾段编译（查表填空，热路径零 LLM）
│
├── ── 节点层 ──
├── nodes.py          505   TagLibraryNode（build / _build_auto / _build_impl）
│
├── ── 接口层 ──
├── api.py            840   27 个 API 端点 + /taglib 页面 + 静态目录 = 29 条路由
│
├── ── 表现层 ──
├── web/taglibrary.js 2668  节点面板 + 挑选器 + executed 回显 + 设置注册
├── web/tagpanel-css.js 420 面板样式（JS 注入，ComfyUI 只自动加载 web/ 下 .js）
├── web/manager.html   215  独立管理页骨架
├── web/manager.js    1474  管理页逻辑（内存工作树 + 惰性加载）
├── web/manager.css    525  管理页样式
│
├── ── 数据 ──
├── data/default/tag_library.json        出厂默认库（随插件更新）
├── data/default/tag_library.user.json   用户库（管理页保存，升级不丢）
├── data/default/taglib/                 ★ 文件夹式镜像 + 规则真源
│   ├── profiles.json      28 KB   武器·物品档案（姿势束/手数/状态槽/NL）
│   ├── grouprules.json    25 KB   50 组全局互斥域
│   ├── nl_flavors.json    15 KB   NL 句式素材（34 族 + pose_map + 宾语池）
│   ├── conflicts.json     24 KB   跨池规则（兼容保留）
│   └── _sync_state.json    5 KB   热同步指纹基线
├── data/default/conflicts.json         1 KB   旧互斥域 (LEGACY_GROUPS_PATH)
│                                              仅新装时供 _migrate_legacy_groups() 迁移, 勿删
├── data/default/backups/               双备份（factory / user）+ _trash 回收站
│
├── ── 一次性脚本（见 §7 F2）──
├── tools/migrate_axes.py      221   1.3.0 库数据迁移（已执行完毕）
└── tools/m4_objects_patch.py  238   物品档案词表写入（幂等，已执行完毕）
```

---

## 三、分层架构

```
表现层  web/          节点面板(addDOMWidget) · 挑选器(dialog) · 管理页(独立页/iframe)
   │  fetch /taglib/api/*
接口层  api.py        27 个 REST 端点 + 管理页 + 静态资源
   │  调用 build()
节点层  nodes.py      TagLibraryNode：解析 selection_state → 分派 manual/auto
   │
引擎层  engine.py     原子束抽取 + 资源算账
        axes / profiles / grouprules / tagconflicts / nl   约束模型 + NL 产出
   │  只读
编译层  runtime_snapshot.py   冷路径编译 → RuntimeSnapshot（mtime key 命中即复用）
   │
数据层  library.py / tagfiles.py / schema.py
        tag_library.json + tag_library.user.json + taglib/ 镜像目录
```

**关键解耦点**

1. **编辑树（胖）与运行快照（瘦）分离**：`schema.py` 在内存里给标签补编辑元数据（type/priority/rarity/groups…），`runtime_snapshot` 只提取热路径需要的字段编译成并列数组（`tag_text[]` / `base_weights[]` / `nsfw_flag` bytearray…），避免热路径做字典查找。
2. **分类树降级**：标签的轴不再来自树路径的硬编码，而是 `axes.axis_of(大类名, 子类名)` 在编译期推导（`SUB_TO_AXIS` 是**路径名→(轴, 次序)** 的稳定键表）。
3. **规则真源外置**：`grouprules.json` 独立于标签字段，因为 **.md 热同步重导入会重建标签 dict、抹掉挂在标签身上的 `groups`**——这是代码注释里明确记录的踩坑，也是理解为什么规则要放独立文件的关键。

---

## 四、数据流

### 4.1 读路径（每次出图）

```
tag_library.json + tag_library.user.json
        │
        ├─ _folder_hot_sync()          1.5s 节流；文件夹有改动则 pull 入库
        │
   deep_merge(default, user)           按 id 三级归并；_tombstones 过滤已删 id
        │
   schema.migrate_library(merged)      内存只读迁移（不写盘）
        │
   ═══ get_merged() 返回，带 mtime 缓存 ═══
        │
   runtime_snapshot.get_snapshot()     key=(default, user, conflicts, grouprules, profiles) mtime
        │                               key 命中 → 直接返回旧快照（无锁无 I/O）
   build_snapshot() 冷路径编译
        ├── 逐标签：轴 / 组集 / 权重 / 性别标记 / 四个池（全量·非NSFW·无女·无男）
        ├── 跨池规则 → cross_rules + cross_banned（增量违禁集）
        ├── grouprules.en_membership() 并集进 group_sets（按 en 查表，免疫重导入）
        └── _compile_ext() 档案 → tags_ext + bundled_only + comp_groups
        │
   engine.run_auto(snap, state, seed)
        ├─ 0. 钉选（count 轴优先入账 → 性别宣言先锁场）
        ├─ 1. prop 池抽取 → 抽中身份词立即原子配一条姿势束
        ├─ 2. 逐池抽取，每步查 R1 组互斥 / R2 跨池 / R3 资源预算 / R4 状态槽
        └─ 3. 按轴次序排序，束成员紧贴挂载词 → AutoResult(picks, dropped, stats)
        │
   _format_tag() + nl.compile_tail(snap, picks, seed)
        │
   ┌────┴──────────────────────────────┬───────────────────────────┐
   │                                   │                           │
positive STRING (标签 + NL 尾段)    PNG extra_pnginfo["TagLibrary"]   ui.taglib_echo
   → CLIPTextEncode                  (节点/模式/种子/实际出词)        → 前端 executed 回显
```

### 4.2 写路径

| 操作 | 端点 | 落盘对象 | 备注 |
|---|---|---|---|
| 管理页保存 | `POST /taglib/api/library` | `tag_library.user.json` | 载荷骤减护栏（<50% 拒绝）+ `X-TagLib-Mtime` 乐观锁 |
| 清空标签库 | `DELETE /taglib/api/library` | user.json `_cleared:true` | 不动默认库/备份，同时清空镜像文件夹 |
| 存为默认库 | `POST .../backup` | `backups/user_backup.json` | 出厂备份永不被覆盖 |
| 恢复默认库 | `POST .../restore-backup` | user.json | 用户备份优先，回落出厂 |
| 导入模板 | `POST .../tagfiles/import` | user.json | 解析 → 跨库 en 去重 → **按名称**归位合并 |
| 档案 / 互斥域 / NL | `POST .../profiles|grouprules|nl` | `taglib/*.json` | 保存前自动 `.bak`；保存后 `invalidate_snapshot()` |
| 面板 🎲 填充 | `POST /taglib/api/draw` | 无（只读） | **与节点执行同一 `run_auto` 代码路径** |

---

## 五、UI 实现方式

### 5.1 三个 UI 载体

| 载体 | 实现 | 打开方式 |
|---|---|---|
| **节点面板** | `node.addDOMWidget("taglib_panel", "panel", holder, { serialize:false })`；`holder` 加 `.taglib-panel` | 节点自带 |
| **挑选器（➕ 添加标签）** | 动态创建 `<dialog>` + `showModal()` → `mountTagPicker()` 纯 DOM 渲染，**8 个页签** | 面板按钮 / Extensions 菜单 |
| **管理页** | 独立 `manager.html`，内存工作树 + 显式保存 | 浏览器直达 `/taglib`、顶栏 🏷、挑选器内嵌 iframe（`/taglib?embed=1`） |

### 5.2 面板的四个关键工程技巧（都是踩坑产物，重构时不能丢）

1. **CSS 由 JS 注入** —— ComfyUI 只自动加载 `web/` 下的 `.js`，独立的 `.css` 根本不会被加载（注释里明确记录）。
2. **翻译扩展免疫** —— 面板与挑选器都加 `p-inputtext` + `translate="no"`。`p-inputtext` 位于翻译扩展 `shouldSkipNode` 的排除链，整棵子树跳过翻译，避免 `night→夜晚` 造成"雨靴雨靴"式重复。
3. **高度交给官方机制** —— 用 CSS 变量 `--comfy-widget-height: 60%` / `--comfy-widget-min-height: 160px`，由前端 `_arrangeWidgets` 弹性分配，不做手动 `onDraw`/rAF 同步。
4. **`serialize` 必须赋在实例上** —— 新版前端序列化读的是 widget 实例属性而非 `options.serialize`；还需 `serializeValue = () => undefined` 兜底，否则面板会在 `seed` 的 `control_after_generate` 之后插一个多余槽位，导致按位置保存/加载错位。

### 5.3 兼容与自愈（大量防御性代码的来源）

`nodes.py` / `taglibrary.js:onConfigure` 承担了 **v2→v3→v4 三代工作流签名迁移**：

- 旧 `mode` 值归一：`random_mix→auto`、`random_by_category→manual`
- v3 `nsfw_mode=on` → 迁移进 `selection_state.nsfw`
- v2 错位的 8 个旧参数（min/max/category_weights/search_text/separator/use_weights/dedupe/pinned）从 `widgets_values` 按位置抢救回 `selection_state`
- `selection_state` 非法则重置 `{}`；`seed` 非数字则归 0

### 5.4 状态同步的三条通道

| 通道 | 用途 |
|---|---|
| `node._taglibPanelApi` | 面板内部 API：`syncMode()` / `refresh({reloadLib})` |
| `app.api.addEventListener("executed")` | auto 模式回显：服务器 `taglib_echo` → 只替换 `_auto` 标记的标签，📌 钉选与手动词永久保留 |
| `setInterval(pollSettingsSync, 2000)` | 全局偏好兜底轮询（该版本前端无 settings change 事件面） |

---

## 六、需要保护的既有正确性设计

重构 UI 时以下机制**不要碰坏**：

1. **钉选语义常开**：📌 标签在随机/填充/回显中必含且不被覆盖，并占用所在子分类配额。
2. **回显只替换引擎部分**：`_auto` 标记是区分"引擎抽取"与"用户手挑"的唯一依据。
3. **墓碑 `_tombstones`**：用户删过的 id 记入墓碑，默认库日后重新带出也被过滤；重新添加自动除名。
4. **载荷护栏 + 乐观锁**：防止"懒加载未完成就保存"把库清空，以及双开互相覆盖。
5. **双备份语义**：factory（随包，永不被用户操作覆盖） vs user（用户基准，升级存活）。
6. **热同步指纹双向核对**：`_sync_state.json` 同时记「文件夹指纹」与「库 mtime」，用于区分 baseline / pull / mirror / none 四种动作，并防止刚写出的文件被回吸。

---

## 七、优化点与改进方向

按 **风险从低到高 / 收益从高到低** 排序。UI 相关项已标 ★。

### A. 前端：可直接清理的死代码与死样式（零风险，建议第一批）★

| # | 位置 | 问题 | 证据 |
|---|---|---|---|
| A1 | `taglibrary.js:520` 与 `:618` | `getFillRange` **重复定义两次**，后者覆盖前者 | grep `function getFillRange` → 2 处 |
| A2 | `taglibrary.js` | `pickFrom` / `buildSubPools` / `fetchConflicts` **仅存定义、零调用**（1.3.0 改为服务端真抽后的遗留本地引擎） | 各 grep 计数 = 1（仅定义行） |
| A3 | `tagpanel-css.js` | 约 **14 个 CSS 类零引用**：`tl-catbar(-row)` / `tl-fillmode` / `tl-catchip` / `tl-selzone` / `tl-selected` / `tl-sel-tag` / `tl-switch` / `tl-cats` / `tl-cat-pill` / `tl-badge` / `tl-nsfw-pill` / `tl-sub-head` | 跨 `web/*.js/html` 复核：仅出现在 `tagpanel-css.js` 自身 |
| A4 | `nodes.py:490` | `weighted_sample()` 模块级函数零调用（引擎已内置 Efraimidis-Spirakis 加权抽样） | 全仓 grep 仅 1 处定义 |
| A5 | `nodes.py:162` | `_tag_matches()` 零调用 | grep 计数 = 1 |
| A6 | `nodes.py:277, 461-478` | `_auto_chosen` 恒为 `None`，`if mode == "auto":` 回显分支**不可达**（338 行 `if mode != "manual": return` 已早退） | 可达性分析 |

> 预估：一次性删除约 **150 行前端死代码 + 110 行死样式 + 40 行后端死代码**，不改变任何行为。

### B. 数据一致性：default 库缺 `axis` 字段（★ 结构性风险）★

**现象（实测）**

| 文件 | 标签数 | 带 `axis` |
|---|---|---|
| `data/default/tag_library.json` | 4356 | **0** |
| `data/default/tag_library.user.json` | 4357 | 4356（1 个缺） |
| `data/default/backups/factory_backup.json` | 4356 | 4356 |
| `data/default/backups/user_backup.json` | 4356 | 4356 |

**根因**：`schema.migrate_tag()` 会补 `type / priority / rarity / groups / requires / mutex_with / aliases / desc / meta / weight / enabled / gender`，**唯独不补 `axis`**。合并库里的 axis 完全来自用户库（`deep_merge` 同 id 用户版整体优先）。

**影响面（需精确区分）**
- ✅ **引擎不受影响**：`runtime_snapshot` 用 `t.get("axis") or axis_of(cname, sname)`，有路径兜底。
- ❌ **挑选器「🎯 拼装轴」视图受影响**：`renderAxisChips()` 用 `t.axis || "misc"`，一旦用户库缺失/被清空后由模板重建，**全部 4357 词会塌进「📦 未归类」一个组**，轴视图事实上失效；同时 `chipEl()` 的悬停提示「轴: …」全部显示错误。
- 触发路径：「🗑 清空标签库」→ 导入 md 全量模板（`parse_tagfile` 不产 axis）；或用户库文件丢失/损坏被改名 `.corrupt`。

**建议**（二选一，推荐第一种）
1. **编译期注入**：在 `library.get_merged()` 或 `/taglib/api/library` 返回前，按 `axes.axis_of(cat_name, sub_name)` 给缺失 axis 的标签补上（后端单点，前端零改动，且对旧数据自愈）。
2. **数据补齐**：把 `migrate_axes.py` 的 axis 补齐逻辑作用于 `tag_library.json` 出厂库，随包发布。

### C. 主题一致性：浅色主题下的观感断点 ★

| # | 位置 | 问题 |
|---|---|---|
| C1 | `manager.css` | **零主题适配**（实测 0 处 `dark-theme` / `prefers-color-scheme` / light 规则），管理页恒为深色 |
| C2 | `taglibrary.js:788` / `:2114` | 挑选器与内嵌管理页弹窗背景**硬编码深色**（`#15171d` / `#17191f`），并写死 `color:#e3e7ee` |
| C3 | `taglibrary.js:2459-2461` | `applyTheme()` 往 `dialog.taglib-dialog, #taglib-picker-dialog` 写 `data-theme` / `tl-light`，但**没有任何 CSS 选择器消费这两个属性** → 死写入 |
| C4 | `taglibrary.js:880-1050` | 挑选器样式全部为内联硬编码色值（`rgba(255,255,255,.09)` 等），仅 4 处用到 CSS 变量 |

**建议**：把面板已验证的 `--tl-*` 变量体系抽成共享主题层，`manager.css` 与挑选器内联样式改为消费变量；让 `applyTheme()` 写入的 `data-theme`/`tl-light` 真正有 CSS 响应（面板已可用，弹窗与管理页补齐即可闭环）。

> 补充：ComfyUI 内置 6 套主题（arc/dark/github/light/solarized/nord），面板已覆盖，弹窗与管理页目前是漏网区。这是**最直观的 UI 优化收益点**。

### D. 性能与加载策略 ★

| # | 问题 | 实测/证据 | 建议 |
|---|---|---|---|
| D1 | 面板 `fetchLibrary()` 全量拉取合并库 | 实测 JSON **1.27 MB**（代码注释仍写"避免无谓的 200KB 请求"，已过期 6 倍） | 后端已备好 `?mode=skeleton` + `/api/subtags` 懒加载，面板复用即可；或加 `ETag`/`If-None-Match` |
| D2 | 每个节点 `setInterval(2s)` 轮询 6 个设置键 | 多节点画布下成倍开销 | 改为事件驱动 + 单例轮询 |
| D3 | `renderTags()` 每次 `innerHTML = ""` 全量重建 | 4357 词场景下滚动/筛选有掉帧风险 | 差异更新或 `DocumentFragment` 批量替换 |
| D4 | `renderAxisChips()` 每次重建全库分组 + 全量 DOM | `eachTag()` 遍历全部标签 | 缓存 axis 分桶，仅在库变更时失效 |
| D5 | chip 右键菜单每次交互都新建 DOM | `oncontextmenu` 内联创建 | 复用单例菜单节点 |
| D6 | 无 gzip / 无响应缓存头 | `_json_response` 直出 | 大 payload 加压缩 |

### E. 交互与信息架构 ★

| # | 问题 | 建议 |
|---|---|---|
| E1 | 面板无「🌲 分类树 / 🎯 拼装轴」视图切换 | 挑选器已有双视图，面板可复用同一渲染函数，让节点上直接按轴浏览 |
| E2 | 设置页 36 个控件扁平罗列（节点参数 / 1.3.0 引擎 / 全局偏好三区，无折叠） | 改可折叠分区 + 锚点跳转 |
| E3 | 挑选器顶栏 8 个页签横向平铺，窄窗口下拥挤 | 分组（浏览 / 编辑 / 管理）或溢出菜单 |
| E4 | 无键盘可达性：无 Tab 顺序设计、无 `:focus-visible` 样式、右键菜单自绘不可键盘触发 | 补 focus 样式 + `role`/`aria` + 键盘快捷键（如 `/` 聚焦搜索） |
| E5 | 死写入的主题属性、`.tl-switch` 等死控件样式残留 | 随 §A 一并清理 |
| E6 | `axis`/树双出处提示只在挑选器悬停可见 | 面板 chip 增加轴标识 tooltip |

### F. 后端与工程卫生（非 UI，但影响可维护性）

| # | 问题 | 建议 |
|---|---|---|
| F1 | `api.py` 840 行 / 27 路由单文件 | 按域拆分（library / tagfiles / conflicts / v13） |
| F2 | 根目录一次性脚本：`migrate_axes.py`、`m4_objects_patch.py`（含 238 行硬编码词表） | ✅ 已移入 `tools/`，修正 `ROOT` 路径基准，并加"⚠ 一次性，勿重复执行"标注 |
| F3 | ~~`data/default/conflicts.json`（5 KB）无任何代码读取~~ **【已更正】** | 初版报告误判为遗留文件。**实测该文件是活代码依赖**：`tagconflicts.LEGACY_GROUPS_PATH` 指向它，`_migrate_legacy_groups()` 会在全新安装（`taglib/conflicts.json` 不存在）时把它携带的 **20 组旧互斥域**迁移进新规则表。**不可删除**，删除会导致新装丢失旧互斥组迁移。 |
| F4 | `tests/` 混装 12 个门禁与约 20 个一次性诊断脚本（`_m1_diag*` / `_patch_*` / `*_check` / `repro_*`） | 拆 `tests/`（门禁）与 `tests/_scratch/`（诊断），README 测试清单与之对齐 |
| F5 | `src/` 空目录 | ✅ 已删除（空目录，git 本就不跟踪） |
| F6 | 无 CI 配置、无 lint 配置（ruff/eslint） | 门禁脚本已齐备，接一个最小 CI 即可防止回归 |
| F7 | `api.py` 三处函数内 `import shutil`；`engine.py` 内嵌闭包 `_pose_fits`/`_commit_ext` 每次调用重建 | 低优先级，顺手清理 |
| F8 | `nodes.py._build_impl` 手动/自动两套路径混杂，含不可达分支 | 拆分为 `_build_manual` / `_build_auto` 两方法，消除不可达代码（与 §A6 合并处理） |

### G. 建议的推进顺序

| 阶段 | 内容 | 风险 | 验收 |
|---|---|---|---|
| **P0** | §A 死代码/死样式清理 + §B axis 注入 + F3 遗留文件确认 | 极低 | 12 套门禁全绿；挑选器轴视图在"清空→导入模板"后仍正常 |
| **P1** | §C 主题一致性（管理页 + 弹窗接入 `--tl-*` 变量） | 低 | 6 套内置主题下逐页截图巡检 |
| **P2** | §D 性能（面板改懒加载/diff 渲染/去轮询）+ §E 交互（面板轴视图、设置页分区、键盘可达） | 中 | 4357 词场景首屏 <200ms；`ui_v13_check.py` 逐 tab 截图 |
| **P3** | §F 工程卫生（拆 api.py、分 tests、接 CI） | 低-中 | CI 跑通全部门禁 |

---

## 八、回归验证清单（每次改动后建议执行）

```bash
python tests/m1_engine_test.py        # 轴/组/跨池/确定性
python tests/m2_weapon_slice_test.py  # 武器束 + 旧缺陷翻案
python tests/m3_nl_test.py            # NL 编译 + 反拼接断言
python tests/m4_objects_test.py       # 物品档案（--long 万 seed 长跑）
python tests/quality_audit.py         # 30 条完整提示词审计
python tests/smoke_test.py            # 后端全链路
python tests/conflicts_test.py        # 反冲突引擎
python tests/folder_template_test.py  # 文件夹热同步
python tests/parser_conflict_test.py  # .md 解析器
python tests/perf_build_test.py       # 性能门禁
python tests/real_http_test.py        # 真机 HTTP queue
# 以下需已启动的 ComfyUI 实例（CDP 浏览器）
python tests/ui_v13_check.py          # 逐 tab 截图 + 断言
```

**UI 改动必查的风险点**：
1. `serialize:false` 与 `serializeValue` 兜底是否仍生效（否则工作流保存错位）
2. `p-inputtext` + `translate="no"` 是否仍在面板与挑选器上（翻译扩展免疫）
3. 回显是否仍保留 📌 钉选与手动词（`_auto` 标记语义）
4. `--comfy-widget-height: 60%` 是否有被硬编码高度取代
5. 旧版工作流（v2/v3 签名）加载后 `onConfigure` 自愈是否仍工作
