# 更新记录

本插件的版本变更史。版本号规则：小型 bug 修复 +0.0.1，功能/底层演进 +0.1。

## v1.5.0 — 输出质量修复：抽取语义重构 + 括号缺陷（2026-09-10）

> 用群里一条真实提示词（62 词）当基准实测后发现：**分类只是表症，抽取语义本身错了**。
> 修复前同配置下插件吐出 **200~213 个互相矛盾**的词，这一版把它压到 **33~60 个且不再自相矛盾**。

### 致命问题（实测数据，非推测）

修复前（5 个种子的真实输出）：

| 冲突类型 | 实例 |
|---|---|
| 年龄三/四重 | `toddler` + `middle-aged man` + `elderly man` |
| **白天与夜晚同现** | `daytime` + `starry night sky` + `eclipse night` |
| 天气全叠 | `snow flurry` + `light snow` + `heat haze` + `fog bank` + `meteor shower` |
| 鞋类 4 双 | `espadrilles` + `slides` + `high-top sneakers` + `soccer cleats` |
| 表情 6 重 | `grin` + `intense stare` + `bashful` + `giggle` + `calm` + `unconscious` |
| 人数与内容矛盾 | `1boy` + `faceless **female**` + `maid apron` + `thigh strap` |
| 人数词自身矛盾 | `0others` / `5girls` + `multiple others` |

三条根因，**没有一条是分类问题**：
1. `fill_master_min/max` 的语义是「**每个**槽位抽 N 个」，63 槽位相乘直接爆表；
2. **缺少"单选维度"概念** —— 年龄/情绪/表情/天气/时间/鞋类/场景地点天然只能选一个；
3. 没有总量预算与配比（风格该 1~2 个、鞋该 1 个、外貌可 5~8 个，却共用一组 min/max）。

### 新增 `slotpolicy.py` —— 逐槽位配额 + 互斥槽位组

- `SLOT_MAX`：63 个槽位各自的 `(最多, 至少)` 配额，取代"全局每槽位 N 个"。
- `EXCLUSIVE`：5 组**互斥槽位组**（同组至多一个槽位出词）——
  场景地点（室内/自然/城镇/幻想）、风格基线（写实⟂二次元）、光源（自然⟂人工）、
  姿态基线（站/坐/躺）、昼夜（时段⟂月与星空）。
- `SINGLE_COUNT_WORDS` / `MULTI_COUNT_WORDS` / `MULTI_ONLY_SLOTS`：
  人数语义 —— 单人场景不再抽「互动与双人」。

### 引擎改动

- 池循环重构为 `_slot_available()` + `_pool_fill()`，配额/互斥组/人数语义统一在该层判定。
- **真正实现 `total_min`**（该字段一直存在于 `DEFAULT_CONFIG` 但从未被使用）：
  第 2 遍补底，最多 3 轮、无进展即停（有界，不为凑数硬塞）。
- **修掉 `total_max` 的连带陷阱**：原实现是朴素截断（`(keep+rest)[:tmax]`），
  而 `rest` 按轴序排 → 靠后的 style/material/camera 会被**系统性砍光**。
  改为 `_trim_to_budget()`：按槽位贡献数从多到少削，并保证不低于各槽位配额下限。
- 顺手修掉一个自己引入的回归：`caps_for()` 返回 `(max, min)` 而调用处按 `(min, max)` 解包，
  导致所有 `min_n=0` 的槽位被整池跳过（外貌与服装全空）。现已统一为 `(min, max)` 并显式注释。

### 修复 `.md` 括号往返缺陷（Danbooru 官方语法）

- 根因：`tagfiles._TAG_RE` 的 zh 组只允许 `[^)]*`，于是 `1other(单人(其他))` 被整体当成 en。
  而 `(qualifier)` 是 **Danbooru 官方消歧语法**（`black_rock_shooter` 作品 /
  `black_rock_shooter_(character)` 角色），不是边缘情况。
- 修复：`_TAG_RE` 允许 zh 内**一层嵌套括号**；`schema.migrate_tag` 对历史数据就地还原，
  `migrate_subcategory` 按 en 同槽位去重。
- 数据修复（`tools/repair_malformed_tags.py`，幂等）：两个库文件 4357 → **4352 词**，
  畸形 6 → **0**；其中 `jiangshi` 是唯一丢失的真词（其余 5 个是已有词的重复副本），已恢复。
- 实测影响：修复前 300 个种子里有 **32 轮**把畸形词写进输出。

### 新增 `tests/quality_gate_test.py`（已纳入一键门禁）

6 项断言，300 种子（`--long` 为 10,000）：词数带 / 槽位配额 / 互斥槽位组 /
人数唯一 / 无畸形词 / 确定性。**当前 300/300 全过、零违规。**

### UI 同步

- 挑选器「总控制 min~max」→「**自动配额 总词数 min~max**」（写 `state.total_min/max`），
  并说明"各槽位配额已内置"。旧的 `fill_master_min/max` 在自动配额模式下不再被读取。

### 效果对比

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 输出词数 | 200~213 | 中位 **57** / 均值 56 / 区间 33~60 |
| 同维度互斥共现 | 每轮都有 | **0**（300 种子） |
| 人数词数量 | 0~4 个且自相矛盾 | **恒为 1** |
| 畸形词进输出 | 32/300 轮 | **0** |
| 群内基准覆盖率 | 55% | 55%（词表补齐见 v1.5.x） |

## v1.4.1 — 节点面板瘦身（2026-09-10）

UI 重写的第一步（方案见 `docs/UI-REDESIGN-PLAN.md`，S5 先做）。**纯前端改动，不涉及数据与引擎。**

**删除死 UI**
- **Fast/Smart 引擎切换**：`settings.random_configs` 根本不存在，
  实测 `resolve_config(default_fast)` 与 `resolve_config(default_smart)` 返回值完全相同
  —— 1.3.0 双引擎合并为单一结构引擎后按钮残留至今，点了没有任何效果。
  现已连同 HTML / JS（`syncEngSeg` 等）/ CSS（`.tl-eng-seg`）一并移除，
  调试预览里的"引擎 xxx"字样也一并去掉。

**低频操作收进 ⋯ 菜单**
- 面板常驻可见控件从 **12 个（含 1 个死的）降到 4 个**：
  头部只剩 `[NSFW] [⋯] [＋ 添加标签]`，底部只剩 `[🎲 填充]`。
- 性别过滤 / 防冲突 / 显示语言 / 预览模式 / 清空 五项移入 ⋯ 下拉，
  且菜单同时充当**状态读数板**（显示"⚥ 双性 / 已开启 / 双语 / 简洁"当前值）。
- ⋯ 上的小圆点在「性别非双性」或「防冲突被关闭」时点亮 —— 这两种状态的效果
  在 chip 上不易察觉，需要一个提示。

**菜单交互（实现细节，值得记一笔）**
- 关闭时机全部收在**面板作用域内**（面板内 pointerdown / 再点 ⋯ / Esc），
  **不用 document 级监听**。原因：画布类页面里同一个 holder 会有多份渲染克隆
  （实测 `document.querySelectorAll('.taglib-panel').length === 3`），
  document 级 click 监听会互相干扰，表现为"⋯ 刚打开就自动关闭"。
  这一点已用 CDP 实测定位（直接设 `hidden=false` 能稳定保持；走 click 就自关）。

**测试**
- `tests/ui_v13_check.py` 增加**面板结构断言**（不再是纯打印）：头部按钮数、
  死 UI 已删、⋯ 菜单默认隐藏且项数正确、清空按钮已移出、🎲 填充常驻、
  四个状态文案存在、菜单能正常展开；失败时退出码非 0。新增截图 `ui_panel.png`。
- `tools/run_gates.py` 补充说明：ComfyUI 运行期间其热同步会在还原后再次触碰
  `_sync_state.json`，提交前需停掉 ComfyUI 或补一次 `git checkout -- data/`。

## v1.4.0 — 主题一致性 · 性能 · 工程收敛（2026-09-10）

**修复**
- **`toast()` 未定义**：`taglibrary.js` 里有 13 处 `toast(...)` 调用但从未定义该函数
  （`manager.js` 里那个是 IIFE 内的局部函数，不是全局）。后果不止提示不显示——
  调用抛错会中断后续语句，例如保存/删除反冲突规则后紧跟的 `renderCfView()` 不执行，
  列表要重开页签才更新。已补上模块级实现（复用面板主题变量）。
- **出厂库缺 `axis` 字段**：`data/default/tag_library.json` 的 4356 个标签全部没有
  `axis`，而用户库与两份备份都有。引擎侧因 `t.get("axis") or axis_of(...)` 有兜底
  不受影响，但挑选器「🎯 拼装轴」视图用 `t.axis || "misc"`——一旦用户库被清空后
  由 md 模板重建，全部词会塌进「📦 未归类」。现改为在 `schema.migrate_tag()` 里按
  `axes.axis_of(大类, 子类)` 兜底注入（已有值 `setdefault` 原样保留），修好故障路径。
- 挑选器分类项颜色被 JS 内联写死（`#cfd6e4`/`#aab3c5`），浅色主题下不可读 → 交由
  CSS 变量；JSON 编辑器状态色、顶栏按钮配色同样改为跟随主题。

**主题适配（新增）**
- 抽出共享主题作用域 `.tl-scope`：一套变量同时服务**节点面板 / 挑选器弹窗 / 管理弹窗**，
  覆盖 ComfyUI 六套内置主题（arc/dark/github/light/solarized/nord）的深浅与色偏。
- 挑选器 170 行内联硬编码色值全部改为消费变量；管理页补齐浅色主题（原先零适配），
  新增 `?theme=&light=` 参数 + `postMessage` 双通道下发（iframe 不继承父页 html 类）。
- 顶栏 🏷 按钮、chip 右键菜单、toast 一并接入主题变量。

**性能**
- **新增 `GET /taglib/api/panel-index`（轻量索引）**：面板只需要分类名/图标 + 每个词的
  树路径 + 性别/NSFW 标记，却每次拉取含标签正文的全量库。索引用（子分类下标, 孙分类下标）
  二元组编码避免重复内联分类名，实测 **336KB → 110KB，比全量库小约 12 倍**；含正文的
  全量库改为**打开挑选器时才懒加载**。
- 全局偏好轮询改为**模块级单例**：原先每个节点各起一个 `setInterval(2s)`，多节点画布下
  开销线性叠加；现在一个定时器驱动所有面板，面板脱离 DOM 后自动注销。
- 挑选器轴视图的按轴分桶结果加缓存（库对象变了才重建），不再每次渲染都遍历 4300+ 词。
- chip 右键菜单改为单例复用，不再每次右键都新建/销毁 DOM。

**交互**
- 挑选器设置页三个分区改为可折叠（`<details>`），原先 36 个控件扁平铺开。
- 补 `:focus-visible` 样式与搜索框 focus 态，键盘操作有可见反馈。

**工程收敛**
- `api.py`（880 行 / 27 端点）拆为 `api/` 包：`_common` / `library_routes` /
  `tagfiles_routes` / `conflicts_routes` / `v13_routes`，对外契约
  `from .api import register_routes` 不变（路由逐条核对：29 → 30，新增的即 panel-index）。
- 前端与后端死代码清理：删除重复定义的 `getFillRange`（2 处）与零调用的
  `pickFrom`/`buildSubPools`/`fetchConflicts`（前端约 108 行）、
  `weighted_sample`/`_tag_matches`/`_norm` 及不可达的 auto 回显分支（后端约 48 行）；
  `tagpanel-css.js` 清掉 18 个零引用 CSS 类（约 106 行）。
- `tests/` 分层：13 个门禁保留，52 个历史诊断脚本移入 `tests/_scratch/`（并修正其仓库根定位）。
- 新增 `tools/run_gates.py` 一键门禁：自动快照/还原 `data/default/taglib/`，
  解决部分门禁真实写入镜像目录、污染工作区的问题。
- 新增 `tests/ui_theme_check.py`（CDP 主题巡检，22 项断言）与最小 CI
  `.github/workflows/gates.yml`。
- 一次性脚本 `migrate_axes.py` / `m4_objects_patch.py` 移入 `tools/` 并加"勿重复执行"标注；
  删除空目录 `src/`。
- README 测试章节重写（一键门禁 + 门禁清单 + 在线/离线区分）。

**说明**
- 库格式只增字段不改语义，旧工作流与旧库文件直接兼容。
- `data/default/conflicts.json` 经核实**不是**遗留文件：它是 `tagconflicts.LEGACY_GROUPS_PATH`，
  新装时 `_migrate_legacy_groups()` 会用它迁移 20 组旧互斥域，予以保留。

## v1.3.0 — 底层重构（2026-09-09）

**架构（四板斧）**
- **拼装轴**：4356 词按 12 条轴重新聚合，二级树降级为浏览皮肤；挑标签面板「🌲 分类树 / 🎯 拼装轴」双视图，每个词悬停显示轴+树双出处
- **武器·物品档案（⚔ bundle）**：7 武器 + 11 日常物品 = 18 份档案、27 束成员词、93 行姿势表。每条姿势=标签组+手数+视线+状态槽+排斥声明；武器必带持握姿势出生、姿势必随武器出生——裸武器/双持单手刀/弓蹭枪姿势结构性消失（万 seed 压测束出生率 100%）
- **资源预算冲突模型**：同轴/同组互斥 + hands/gaze 账本 + 状态槽 + 50 全局互斥域自动推导，旧 81 条手写规则退役大半（跨池规则保留 `conflicts.json`）；性别锁、嘴部域池级+出口级双保险
- **NL 尾段**：标签主体后追加 1-3 句英文描写，34 组句式族查表编译（人称回指/句式轮换/叙事顺序反拼接三律），热路径零 LLM、seed 可复现、可关闭

**界面**
- ➕ 挑选器 5 页签 → 8 页签（新增 ⚔ 武器档案 / 🧬 互斥域 / ✍ NL 句式），三新页全量中英双语 + 「文A」切换
- 🎲 填充改走服务端真引擎：面板预览 = 排队实出，不再两套引擎打架
- ⚙ 设置新增 1.3.0 引擎区（NL 开关/带束概率/武器上限/配件概率）
- 档案可视化：挂载诊断徽章 + JSON 编辑保存即生效

**引擎**
- Fast/Smart 双引擎合并为单一结构引擎；`random_engine.py` / `rules_engine.py` 退役删除

**数据真源新增**
- `taglib/profiles.json`（档案）、`taglib/grouprules.json`（全局互斥域）、`taglib/nl_flavors.json`（句式素材）

**兼容**
- 库格式只增字段不改语义，旧工作流直接加载；`selection_state` 协议不变

**测试**
- 9 套 Python 门禁全绿；万抽长跑零违规；真机 ComfyUI HTTP queue 全过；CDP 浏览器逐 tab 截图巡检

## v1.2.2 — 2026-09

- 反冲突压测优化：300 次生成压测驱动规则 55→81 条、零失效（服装套数互斥、姿势基态单选、鞋/下装/袜单选、ahegao↔微笑矛盾、幼儿安全、降雨↔降雪等）
- 同义重复清理（judo uniform / judo gi）
- 用户库 4356 标签同步默认库与备份，恢复往返字节级一致

## v1.2.1 — 2026-09

- 发布修补

## v1.2.0 — 标签库 v2 大版本，2026-08

- 标签库 v2 结构重组：9 大类 / 63 子分类 / 1615 词条（表情/武器/裙装/光影等全维度拆分归位）
- 补充词库合并 +2700 标签（旧分类自动路由、三层去重）
- 出图元数据：PNG 写入 `TagLibrary` 键，自动模式可查可复现
- 翻译扩展免疫（DD-Translation 不再改写标签英文）
- 性别过滤全链路一致；自动回显保留手动标签；🔒→🗑 一键清空；钉选必含常开

## v1.1.x — 2026-08

- 反冲突系统（规则文件导入导出、tag/sub/cat 任意组合互斥）
- 文件夹式标签库 + 双向热同步
- AI 协作闭环（模板导出 → AI 扩写 → 导入归位去重预览）
- 独立管理页 `/taglib`、分类图标自定义、批量粘贴导入

## v1.0 — 初版，2026-08

- 标签库节点：分类面板、点选/🎲填充、自动模式、钉选、NSFW 分级、中英显示
- 输出 STRING 直连 CLIPTextEncode；seed 决定论、权重语法、prefix/suffix
