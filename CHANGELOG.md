# 更新记录

本插件的版本变更史。版本号规则：小型 bug 修复 +0.0.1，功能/底层演进 +0.1。

## v1.7.1 — 输出质量真审：未成年锁定 / 人数词分类补全 / 人称一致（2026-09-12）

用户问"完整提示词质量到底如何、你真验证过吗"。回答：门禁全过 ≠ 没毛病 ——
把真机输出**当人读**后抓到 4 类门禁管不到的语义缺陷，全部修复并固化为新断言。

### 真审抓到什么（真实输出实例）

| 缺陷 | 实测输出 | 根因 |
|---|---|---|
| **未成年 × 成人内容** | `toddler` + `side-tie panties` | 年龄词与成人词散布 9 个槽位，配额/互斥槽位组/跨池规则全管不到 |
| **群像配单数人称** | `large group` + "She has asymmetric bangs..." | 人数轴 30 词里 9 个没进 MULTI 表；`_pronouns` 按 `_INTRO_KEYS` 扫描，扫不到回落 "She" |
| **摄影 × 手绘媒介** | `product photography` + `shin-hanga` | style_base 互斥只盖 写实摄影⊥二次元向 |
| (连带发现) | `4girls/5girls/6+girls/1other/0others` 缺人称行 | 同上，Q10 建好后由门禁自己抓出来 |

### 修了什么

- **未成年锁定 (slotpolicy + engine)**：`MINOR_AGE_WORDS` (toddler/infant/child/
  preteen/loli/shota/teen/…) 一经出生（抽取或钉选），`MINOR_BLOCK_WORDS`
  (~55 个成人向词：裸露/内衣/泳装/体型/表情/氛围情绪的成人子集) 在候选级
  全池屏蔽。**词级**而非槽位级 —— 裸露槽的 "bare shoulders"、腿袜槽的
  "thighhighs" 等日常词保持可用。
- **人数词分类补全 (slotpolicy + nl)**：group of girls/boys、trio、quartet、
  ensemble、pair、large/small group、crowd 进 MULTI 表；全部 30 个人数轴词
  进 `_PRONOUN` + `_INTRO_KEYS`（缺了任何一张表都会回落 She）。
- **NL 群像开箱句 (nl_flavors.json)**：给 23 个复数/中性人数词补 intro 句
  （此前只有 1girl/1boy/solo 有，群像从来不出引入句）。
- **摄影⊥艺术媒介 (slotpolicy.EXCLUSIVE)**：新增 style_photo_art 互斥组；
  二次元向不参与（anime style + oil painting 是合法组合）。
  题材风格的 art nouveau 等流派词不锁（摄影配流派语义成立）。

### 新断言

- `quality_gate_test` **Q10 人数词分类完备**：人数轴每词必须进三张分类表 +
  `_PRONOUN`/`_INTRO_KEYS`（建好后立即抓出 crowd/4girls/5girls/6+girls/1other/
  0others 六个漏网，全部补齐）。
- `quality_gate_test` **Q11 未成年锁定**：钉选 toddler + NSFW 全开，30 seed 内
  成人向词必须零出现。
- `prompt_quality_test` **P4 新增 4 对未成年矛盾**、**P9 NL 人称与人数词一致**
  （人数词为复数时尾段出现 She/He/her/his 即违规）。

### 修复后实测

```
[seed2]  count='group of girls' → The group of girls fills the scene. They have swept bangs and wolf cut, ...
[seed6]  count='5girls'         → They hold katana between their teeth, both hands free. ...
[seed8]  count='large group'    → A large group fills the frame to its edges. They hold sword ...
```

### 验证

离线门禁 14/14；在线 node_output_test（真机 60 次生成 × 文本层断言）通过。

## v1.7.0 — 结构优化：编辑层字段完整往返 + 前端拆模块（2026-09-12）

体检第 3 期。两个底层演进：`.md` 文件夹镜像不再丢编辑层字段；3156 行的前端
单文件拆成三个职责清晰的 ES 模块。

### 1. 编辑层字段 sidecar `_tagmeta.json` (`tagfiles.py`)

`.md` 镜像只承载**输出层**字段 (en/zh/weight/nsfw/gender)。aliases / priority /
rarity / enabled=false 这些**编辑层**字段此前在"文件夹重建库"（热同步 pull、
清空后重导、user.json 损坏重建）时**静默丢失** —— grouprules 当年就是为同样
的问题独立成文件的，这次把剩下的编辑层字段也补上等价物：

- `sync_to_folder` 落镜像时同步写 `_tagmeta.json`（按 en_lower 查表，**只存非默认值**
  控体积；`_` 前缀 = 指纹扫描/导入扫描/清空保留都跳过，不会形成同步循环）
- 吸入路径（`import_files_into` 热同步 pull / 管理页 `_parse_and_merge_tree`）
  在 parse 之后调 `apply_tag_meta` 还原：aliases/priority/rarity 只填缺省，
  enabled 只做单向还原（sidecar 说停用 → 覆盖 parse 物化的 True，绝不反向）
- 新离线门禁 `tagmeta_roundtrip_test`（第 14 项）：写出/还原/全链路吸入/不进指纹

### 2. 前端拆模块 (`web/`)

`taglibrary.js`（3156 行）按职责拆三份，段落逐行搬运零改写 + 导入完整性脚本校验：

| 模块 | 行数 | 职责 |
|---|---|---|
| `taglib-common.js` | 265 | 转义/toast/设置读写/主题/偏好轮询/两级库缓存/selection_state 语义 |
| `taglib-picker.js` | 1669 | 全库挑选器五页签 + 三个行内编辑视图 |
| `taglibrary.js` | ~1290 | 节点面板 / executed 回显 / 管理弹窗 / registerExtension 入口 |

共享的可变缓存（LIB_CACHE/PANEL_CATS/LIB_PATH…）放 common 用 ESM 活绑定：
applyPanelIndex 在 common 内重新赋值，所有导入方立即看到新值。

### 3. deep_merge 索引化 (`library.py`)

用户库分类/子分类建一次 id 索引，取代每个子分类的线性扫描（65 子分类 × 用户库
规模的 O(n²) → O(n)）；`_find_user_tags` 等四个私有 helper 随之退役。语义不变
（首见优先与旧扫描一致），smoke_test 全链路逐项通过。

注：`_pool_fill` 补底轮的候选表缓存经评估**不做** —— 候选过滤依赖每次抽取的
动态账本（used_lower/性别锁），缓存整表要么失效要么加失效逻辑，p50 已在 1-4ms，
复杂度不划算。

### 仓库瘦身说明

`node.zip` / `ComfyUI-TagLibrary-v1.2.0-r2.zip` / `tests/*.png` 在 v1.6.4 前后的
`.gitignore` 调整中已全部移出 git 跟踪（HEAD 与发布包不再包含，仅剩 docs/ 下
README 引用的 5 张截图）；磁盘上的两个旧 zip 是从未入库的本地文件，留待自行处理。

### 验证

离线门禁 14/14；在线 4/4（拆模块后 ui_v13 面板结构/五页签/三视图可编辑 +
ui_theme 深/浅主题全过）。

## v1.6.6 — 安全加固：CSRF 防护 + 导出确认 + 双向删除精确匹配（2026-09-12）

体检发现的第 2 期加固项。ComfyUI 主应用无鉴权，用户浏览器里打开的**任意网页**都能把
请求打进 `localhost:8188` —— 用 `text/plain` 的"简单请求"即可绕过 CORS 预检
（响应虽然读不到，但删库/覆盖库/导文件已经真实执行了）。

### 1. CSRF 防护中间件 (`api/_common.py` + `api/__init__.py`)

- 只作用于 `/taglib/api/*` 的写方法 (POST/PUT/DELETE/PATCH)，ComfyUI 其余路由零影响
- 判定：请求带 Origin/Referer 且 authority 与 Host 不一致 → 403
- 三类合法调用者全部放行：同源页面（面板/管理页）、无 Origin 的脚本客户端
  （curl/测试脚本/第三方工具）、反代后同域页面（authority 归一含默认端口剥离）
- `Origin: null`（沙箱 iframe / file://）与形态怪异的 Origin 保守拒绝
- 真机验收进 `real_http_test`：跨站 403 / 同源放行 / 无源放行 / 外目录导出无 confirm 403

### 2. 整库导出到外部目录需显式确认 (`api/tagfiles_routes.py` + `web/manager.js`)

`export-folder` 的 `dir` 原先只查绝对路径——任何同源请求都能把整库镜像写到任意
可写路径。现在：`data/` 子树内直接放行；之外要求 `confirm: true`，管理页同步加了
确认弹窗（镜像会覆盖/删除目标位置库结构内的 .md，值得让用户看清目标路径）。

### 3. 双向删除反向匹配改精确 (`library.py`)

`_apply_folder_deletions` 找"子分类对应的 md 还在不在"原先用包含式模糊匹配
（`fn.replace("()","") in 子分类名`）——子分类名互为子串时（"上装" ⊂ "上装细节"）
会把**文件已删的子分类误判成还在**，双向删除静默失效。改为只认三种精确形态：
原名 / `sanitize_fsname` 净化名 / 净化名`(n)` 去重后缀。

### 门禁

新增离线门禁 `api_security_test`（第 13 项）：
- S1 CSRF 中间件：aiohttp TestServer 真跑 —— 跨站/null/跨端口 Origin 拒绝，
  同源/Referer 兜底/无源/GET/非本插件路径放行
- S2 导出目录：相对路径拒 / data/ 内放行 / 外部无 confirm 拒 / confirm 放行
- S3 双向删除：子串误匹配回归（上装/上装细节）、净化名、`(n)` 后缀

### 验证

离线门禁 13/13；在线 4/4（real_http 含新 CSRF 真机断言）。

## v1.6.5 — 全仓体检修复：一个隐藏 bug、一处从未生效的设置、热路径减负（2026-09-12）

全仓通读体检（后端 ~4.5k 行 / 前端 ~5k 行）后修复四个缺陷、清理死代码，并补两条门禁防回归。

### 修了什么

1. **快照被过滤树污染（后端，最重）** `nodes.py`
   auto 模式曾把 `_apply_nsfw` 过滤后的库喂给 `get_snapshot()`，而快照缓存键只有文件
   mtime —— 后果：同一进程先以 NSFW 关生成过一次，之后打开 NSFW 开关**也抽不出任何
   NSFW 词**（旧快照永久命中）。现在 auto 一律喂全量库，NSFW/性别由引擎在池层面处理
   （`pools_nonsfw` / `pools_nofemale` / `pools_nomale` 本来就是为此设计的）。

2. **「新节点的默认模式」设置从未生效（前端）** `web/taglibrary.js`
   旧判断 `Object.values(modeW.options).includes(defMode)`：新前端 combo widget 的
   options 是 `{values:[...]}` 对象，`Object.values` 拿到 `[[...]]`，includes 永远
   不命中。因默认值恰好也是 manual 一直没暴露。现按数组/对象两种形态取值判断。

3. **NSFW 开关的 null 语义前后端不一致（前端）** `web/taglibrary.js`
   `state.nsfw=null` 时面板按全局设置显示（可能开）、后端按 false 过滤 —— 预览≠生成。
   现在 `getState()` 就地物化成显式布尔；工作流载入（onConfigure）与新建节点两个入口
   都写回显式值，state 自带语义。

4. **README/README_EN 停在 v1.3.0** —— "8 页签挑选器"/"分类树+轴双视图"等均已是
   前几个版本的旧账。两份 README 重写到当前口径（5 页签 / 单一视图 / 12 轴 66 槽位
   4458 词 / 画师轴 / 12+4 门禁）。

### 热路径减负

- **手动模式不再每次生成做全库过滤拷贝**：原流程每轮 `_apply_nsfw` 深拷贝整棵树 +
  三次全库遍历建 `full_by_en`/`en_path`/`by_en`。现在 NSFW/性别/排除全部在 chosen 层
  复核（与原出口级过滤同规则），en/id 查表索引按库 mtime + dict 身份缓存，库没变就
  零扫描。
- **死代码清理**：`min_tags`/`max_tags` 解析块（v3 签名后无人读取）、`_apply_nsfw`
  （随 1/3 项退役）、`_build_auto` 的 `mode` 形参、前端 `(getState(node).seed|0)`
  （`state.seed` 从未被写入过）。
- **面板/挑选器 HTML 注入面收口**：`chipLabel` / 挑选器 `chipEl` / 侧栏 `mkRow` /
  排除抽屉卡片原先把库内 en/zh/分类名原文塞 `innerHTML`，统一走转义（库内容来自
  可导入的 .md/JSON，不能信）。

### 门禁

- `quality_gate_test` 新增 **Q9 NSFW 往返**：同一快照先关后开 —— 关=零泄漏，
  开=30 seed 内必能抽出 NSFW 词（正是缺陷 1 的回归特征）。
- `ui_v13_check` 新增 **默认模式生效断言**：设置 `TagLibrary.default_mode=auto` 后
  新建节点 mode 必须是 auto（正是缺陷 2 的回归特征；设置 API 不可用时显式跳过）。

### 验证

`tools/run_gates.py` 12 项离线全过（smoke_test 覆盖手动双路径 + NSFW 三态 +
排除 + 权重 + 去重，行为与改前逐项一致）。

## v1.6.4 — 真机节点输出测试：补上一直缺的一层（2026-09-10）

### 起因：用户问"节点输出你就测了几次？"

老实回答：**差一个数量级。**

| 层级 | 之前实际跑了多少 |
|---|---|
| 引擎层（直接调 `run_auto`） | 约 **5,500 次**抽取 —— `quality_gate_test` 300×7 轮、`prompt_quality_test` (200+800)×2 模式、加各种临时验证 1,400+ |
| **真机节点**（ComfyUI HTTP queue） | 只有 **约 30 次** —— `real_http_test` 是 7 个固定用例 + 1 次复现 + 20 个 seed 的**性别锁**，**没做文本层质量断言** |

而真机路径恰恰多出节点这一段：前后缀拼接 / `_format_tag`（权重语法、画师 `@`）/
分隔符 / NL 尾段拼接 / `executed` 回显。这些在前两个测试里都是**我手工模拟**的 ——
节点那段逻辑一旦改错，它们都不会报。

### 新增 `tests/node_output_test.py`

经真实队列跑 N 次（3 种状态 × N 个 seed），读 `history` 里节点**实际吐出的 positive 字符串**，
做 7 项文本层断言：词数带 / 无重复 / 无畸形 / **语义互斥对不共现** / 负向词不漏入 /
NL 尾段 ≥2 句 / 标签段纯净且尾段在末尾。

### 它立刻抓到一处"测试与产品不一致"

首轮 180 次生成报 **N6 120 次失败（"NL 0 句"）**，看起来像 NL 尾段根本没输出。
追下去发现是**我的测试写错了**：节点是用 `". "`（句号+空格）把尾段接在标签后面的，
而我按 `"\n\n"` 切分 —— 永远切不出尾段。真机 positive 实际长这样：

```
..., floating runes. They hold katana between their teeth, both hands free.
Eyes lowered, they seem to listen to something far off.
```

尾段在，而且正好 2 句。已把切分改为「标签段不含句号 → 第一个 `. ` 之后即尾段」。
**这正是这一层测试的价值：引擎层永远发现不了"节点把尾段接成了别的样子"。**

### 门禁

`node_output_test` 纳入 `run_gates.py` 的**在线组**（需要 ComfyUI 在跑）。
默认 20×3 = 60 次生成（约 4 分钟）；发布前重度跑 `--n 200`（600 次）。
同时把在线组抽成独立的 `ONLINE` 列表，便于核对。

## v1.6.3 — 画师轴：留空 + 默认关闭 + 自动 `@` 前缀（2026-09-10）

用户要求：**画师类目不预置任何词、默认关闭这个类目**。

### 为什么这样设计才对

画师是**"选定"而不是"随机"的维度** —— 你定了某个画风就固定用它，
让引擎随机抽一个画师只会毁掉整体观感。而且 Anima 官方明确要求
**artist 必须带 `@` 前缀**（`@wlop`），不带前缀效果很弱。

所以：

| 设计 | 说明 |
|---|---|
| **轴留空** | 新增 `画师` 轴（段位 ⑤）与空槽位「画师名」，不预置任何名字 —— 由你自己填 |
| **默认关闭** | 新节点的 `exclude_categories` 默认含 `"画师"`，自动抽取永不碰它 |
| **要就勾上** | 侧栏「画师」那一行的勾选框勾上即可参与抽取（或直接手动往节点加名字） |
| **自动补 `@`** | 库里存裸名（`wlop`，方便你编辑），**输出时自动补成 `@wlop`** |

`@` 补前缀在两处生效，覆盖两条路径：
- 随机抽到 → `engine.make_pick()` 里按轴补前缀；
- 手动挑选/钉选 → `nodes._format_tag()` 按 `_cat`（轴名）补前缀。

同时 `engine._lib_key()` 让**带 `@` 的引用也能查回库** —— 否则把 `@wlop` 钉选后再加载
工作流会解析不到（库里存的是裸名）。

### 端到端验证（三条都过）

```
画师轴 tag 数: 1 (临时注入 wlop 模拟用户自己填)
A) 画师关闭时: 画出 无                  <- 默认状态确实不抽
B) 画师开启时: seed 2 输出 @wlop        <- 自动补 @ 前缀
C) 钉选 "@wlop": ['@wlop']              <- 带 @ 也能查回库
```

### 结构变化

轴 12 → **13**（`画师` 插在 `角色身份` 之后、`外貌特征` 之前，段位 ⑤）。
`smoke_test` 的轴数断言同步更新。**15 项门禁全 PASS。**

## v1.6.2 — 单一视图 + 每轴开关 + 完整提示词重度测试（2026-09-10）

### 1. 删掉"两种显示方式"，只留好用的那个

用户反馈"段位序和分类树什么玩意，两种显示方式？没必要"。确实是我留的冗余 ——
两个视图现在结构相同（树的第一级也已经是轴），差别只是分组方式。
**删掉分类树与视图切换按钮**，只保留「段位序」（它就是引擎真实结构）。

原来挂在树视图上的**逐槽位配额输入框**已迁到新侧栏槽位行上，功能没丢。

### 2. 每个轴 / 槽位 / 孙类都加了启用开关 ← 回应"类目怎么关"

用户指出：自动模式下**所有类目都会被抽**，但"有的用户可能绑定这个角色，
那么角色相关的要可以关"。原来只有一个藏在折叠抽屉里的排除页签，很难发现。

现在侧栏每一行（轴 / 槽位 / 孙类）行首都有一个勾选框：
- 关掉「角色身份」→ 整条轴不参与抽取（绑定了角色 LoRA 的场景）
- 关掉某个槽位 → 只有它跳过
- 关父级会自动清理子级的零散排除项；关子级会清掉父级整条排除
- 状态写进 `exclude_categories`，与折叠抽屉、与引擎里的排除判定是同一份数据

### 3. 完整提示词重度测试（新增 `tests/prompt_quality_test.py`）

在**最终提示词文本**层面做断言（不是只看抽取结果）—— 这才是用户看到/喂给模型的东西。
800 种子 × 2 模式（开/关 NL 尾段），15 项断言：

| 断言 | 说明 |
|---|---|
| P1 词数带 | 28~72 |
| P2 无重复词 | 大小写不敏感 |
| P3 无畸形词 | `x(y(z))` |
| P4 **语义互斥对不共现** | 24 组人工整理的高置信矛盾对（含跨槽位的） |
| P5 段位序不回退 | 文本层复核 |
| P6 人数与性别一致 | `1boy` 时不得有 ♀ 词 |
| P7 NL 尾段 ≥2 句 | Anima 官方要求 |
| P8 负向词不漏入正向 | `worst quality` / `blurry` / `score_1` … |

**它当场抓出两个真问题**：

1. **P4：`bare feet` + `boots` 同现**（2/200）—— 两者分属不同槽位，配额与互斥槽位组都拦不住。
   新增 `slotpolicy.BLOCK_SLOTS_BY_WORD` / `BLOCK_WORDS_BY_SLOT` **双向屏蔽**
   （词→槽位、槽位→词都要写，先抽到哪一侧另一侧就停）。修复后 500 种子 0 例。
2. **P7：66% 的 seed 只出 1 句 NL 尾段** —— 因为 intro 只认 `1girl/1boy`，
   动作句只认武器束，环境/光线句只认少数关键词。Anima 官方明确"纯自然语言至少 2 句"。
   新增 `describe` / `wear` / `scene` 三个句式族做**兜底**（按有无人物分流：
   `no humans` 时不再写人，改描场景），并做**主谓一致**（`She has` / `They have`）。
   修复后 200 种子全部 2~3 句，主谓不一致 0 例。

### 门禁

新增 `prompt_quality_test` 纳入一键脚本，**共 15 项全 PASS**。

### 过程中修掉的测试问题（值得记）

`ui_v13_check` 里 `_nodes.find(x=>x.type==='TagLibraryNode')` 会读到**第一个**节点，
而 ComfyUI 会恢复上次打开的工作流（实测页面里有 **5 个**同类型节点）——
于是断言读到了旧的空节点，表现为"开关没生效"，实际写入的是打开挑选器的那个节点。
已改为**建节点前先清场 + 统一取 `pop()`（最后一个）**，并加面板就绪轮询。
另把 ⋯ 菜单的断言从 `offsetHeight>0` 改为语义判定（`hidden`/`display`）——
合成场景下节点不一定被画布渲染，布局高度为 0 属于测试环境而非产品问题。

## v1.6.1 — S4 分类重构：9 大类 → 12 轴（2026-09-10）

### 为什么要改

原结构第一级是"作者视角"的大类（人物主体 / 服装系统 / …），而系统真正的骨架是**轴**
（`axes.py` 自己的注释就写着"分类树降级为 UI 视图"）。实测：

- 9 个大类里 **8 个恰好等于 1 条轴**（纯冗余）；
- 唯一例外「**人物主体**」一个类跨了 **5 条轴**（count 38 / character 106 /
  appearance 934 / clothing 38 / prop 265 = 1381 词）—— 大类这一级在最该细分的地方塌成一锅。

### 改成什么

```
旧:  大类(9)  →  子类(65)              + 轴由 axes.py 的路径映射表外部推导
新:  轴(12)   →  槽位(65)              ← 轴就是第一级
     大类降级为标签上的 facet 字段 (非结构, 仅搜索用)
```

新轴名（与前端 `AXES_ZH` 一致，避免用户重新认路）：
`画质规格 / 人数 / 角色身份 / 外貌特征 / 服装 / 道具武器 / 动作姿态 / 场景环境 / 光影氛围 / 构图镜头 / 风格媒介 / 材质特效`

### 迁移是纯机械的（已逐项校验）

编写 `tools/migrate_to_axes.py`（幂等、带 dry-run）：

| 校验项 | 结果 |
|---|---|
| 槽位重名冲突 | **0**（按 `axes.axis_of` 重挂，可程序化完成） |
| 词数变化 | **4458 → 4458**（不变） |
| 槽位次序 vs 旧表 | **65/65 完全一致**（输出顺序零漂移） |
| `facet` 覆盖 | **4458 / 4458** 全部打上原大类名 |

同时处理了三处连带改动：
1. `axes.SUB_TO_AXIS_V2`（新路径表）+ `AXIS_NAME_ZH`，`axis_of()` 同时兼容新旧两种结构；
2. `slotpolicy.py` 的 65 个槽位键从 `大类/子类` 改写为 `轴名/槽位名`
   （不改写会让所有配额静默回落到默认值、输出质量倒退）；
3. `conflicts.json` 里 51 处 `cat`/`sub` 路径引用迁移到新路径
   （唯一例外「人物主体」跨 5 条轴，脚本会在遇到时明确报出来，当前数据里没有引用它）。

### md 文件夹镜像

顶层目录从「大类」变成「轴」：`轴/槽位/槽位.md`（例如
`外貌特征/发型/发型.md`），符合"文件夹结构 = 真实结构"的设计承诺。

### 旧工作流自愈

S4 之前保存的节点里 `exclude_categories` 存的是旧「大类[/子类]」路径，
新结构下会**永远匹配不上 → 表现为"排除了却照样抽"**。
`engine._migrate_excludes()` 在读取时就地转换（幂等）：
`人物主体` → 展开为 `人数/角色身份/外貌特征/服装/道具武器`，
`人物主体/发型` → `外貌特征/发型`。

### 过程中修掉的两个自己引入的问题

1. **`SUB_TO_AXIS_V2` 没写进去** —— 工具里用正则替换多行 dict，
   而插入的是单行空表，正则不匹配 → 表为空 → **所有标签掉进 `misc`**
   （`m2` 的"束成员紧贴武器"当场报 29 次失败）。已改为按整行替换并逐项校验。
2. **`smoke_test` 硬编码旧大类名** —— 改为断言"轴数 = 12 且外貌特征轴存在"，不再写死单个名字。

### 门禁

**14 项全 PASS**（含真机 HTTP + `ui_v13_check` + `ui_theme_check`）。
`m2` 的束相邻、`perf_build`、`folder_template` 等行为门禁在重构后全部保持通过。

## v1.6.0 — 挑选器重构：页签 8→5 + 三个数据视图可编辑（2026-09-10）

用户反馈"改完看不到变化、界面还是原来那样、很多地方只能看不能改"。根因有两条：
**上一版只删了 1 个页签（8→7）**，且**段位分组只在"轴视图"下可见，而默认是树视图** —— 所以看不到。

### 页签 8 → 5

| 原 | 去向 |
|---|---|
| 挑标签 | 保留（默认进入，且默认视图改为**段位序**，不再默认树视图） |
| ⚔ 武器档案 | 保留，**改为可编辑** |
| 🧬 互斥域 | 保留，**改为可编辑**，并**合并「🧷 防冲突关系」**（33 条跨池规则） |
| ✍ NL 句式 | 保留，**改为可编辑** |
| 🚫 排除类目 | **删页签 → 并入左侧栏「🚫 排除类目」可折叠抽屉**（排除本来就是"少抽哪些"，与浏览是同一件事的两面） |
| 🏷 标签库管理 | 已删（v1.5.3，iframe 嵌同一管理页，顶栏 🏷 已有入口） |
| 🧷 防冲突关系 | 已并入互斥域 |
| ⚙ 设置 | 保留 |

### 三个数据视图从"只读卡片 + JSON 兜底"改为真正的行内编辑

新增共享编辑原语（`fillChips` / `bindEditable` / `applyFieldInput` / `saveBarHtml` / `postJson`），
三个视图复用同一套，不再各写一份只读渲染：

- **⚔ 武器档案**：档案 id / 中文名 / 挂载槽位 / 身份词（chip 可增删）全部可改；
  每条束的 id、中文、出词、手数、视线、权重、状态槽（`k=v,k=v`）都可改；
  支持「＋ 新增档案 /＋ 姿势 /＋ 配件」与逐条删除。实测 579 个可编辑单元格、64 个 chip、37 个增删按钮。
- **🧬 互斥域**：域 id 与成员 chip 可增删（成员输入带全库 datalist 补全）；
  「＋ 新增互斥域」；下方并入跨池规则列表 + 新增表单（33 条）。
- **✍ NL 句式**：句式族可改名（保序重建并**同步更新 pose_map 指向**）、变体可增删改；
  动作词→句式族的映射可改键、改目标族、增删。实测 847 个可编辑单元格、48 个下拉。

JSON 入口保留为「高级」折叠项（批量粘贴/脚本生成时更快），**默认走表单**。

### 门禁

`ui_v13_check` 增加断言（失败即非 0）：页签恰好 5 个、三个已删页签确实消失、
排除抽屉在侧栏内、三个视图存在 `input.tp-ecell` 与增删/保存按钮、跨池规则已并入。
**14 项门禁全 PASS。**

## v1.5.3 — S4a 输出段位 + S7 挑选器收敛（2026-09-10）

### S4a · 输出段位（Anima 官方 tag order）

Anima 作者规定六段拼接序，而原 `AXIS_ORDER` 把 **`style` 排在第 11 位（倒数第二）**
—— 与目标模型口径直接冲突（style 是"换一个词就换整体观感"的控制点，必须在第 1 段）。

新增 `axes.AXIS_SECTION` / `section_of()` / `output_order()`，输出次序改为
`段位 × 10000 + 轴次序`：

```
① quality·meta·year·safety + style slot  ② count  ③ character
④ series  ⑤ artist  ⑥ general
```

⚠ **段位只决定输出次序，抽取次序（`pool_order`）保持不变** —— 人数词必须先抽到
才能锁性别（`led.gender_lock`）；若让 style 先于 count 出生，性别锁会失效、
重新出现 `1boy + faceless female`。这一点已写进 `axes.py` 注释。

### 人数语义：三类实测驱动的修复

1. **「人数」槽混了 6 个非人数词**（`faceless` / `faceless female` / `faceless male` /
   `out of frame` / `upper body only implied` / `solo focus`）—— 人数据配额是 (1,1)，
   被它们占掉就没有 `1girl`/`1boy` 出场，性别锁永不置位。已归位到「构图镜头/构图」。
2. **多人数性别词没有 `gender` 标记**（`2girls` / `multiple girls` / `2boys` …）——
   实测只有 **33%** 的轮次能锁上。已补。
3. **`no humans` 不抑制人物轴** —— 会产出 `no humans + long hair`。
   新增 `slotpolicy.NO_HUMAN_COUNT_WORDS` / `NO_HUMAN_SKIP_AXES` + 引擎判定。

### 顺带修掉一个会静默污染输出的机制问题

归位换槽位后必须同时清掉 `id` / `axis` / `type` —— 三者都从"大类/子类路径"推导。
实测 `out of frame` 搬到构图槽后 `axis` 仍是 `count`，于是它成了**第二个人数词**、
段位序也回退。已在 `schema.migrate_tag` 加**陈旧 axis 自愈**，同类问题不会再犯。

### S7 · 挑选器收敛（第一步）

- **删除「🏷 标签库管理」页签** —— 它是 iframe 嵌的同一个管理页，顶栏 🏷 已有入口，
  属于重复入口。挑选器 **8 页签 → 7 页签**。
- **轴视图按段位分组**：侧栏出现 `① 质量·元信息·风格 / ② 人数 / ③ 角色 / ⑥ 通用`
  分隔标题，轴列表也按段位序排列 —— 用户能直接看到"这一轴在输出时落在第几段"。
  效果：质量词与风格词现在紧挨在第 1 段（此前 style 被排到最后）。

### 门禁扩充到 14 项 / 质量断言 8 项

`quality_gate_test.py` 新增 **Q7 段位序**（段位不得回退）、**Q8 no humans 语义**。
当前 300 种子 8 项全过；**14 项门禁全 PASS**。

| 指标 | 数值 |
|---|---|
| 性别锁置位率 | 33% → **42%**（其余为 `solo`/`group`/`crowd` 等本就不声明性别的词，属正确行为） |
| 性别矛盾轮次 | **0/200** |
| `no humans` 清空人物轴 | **6/6** |
| 词数带 | 300/300 落进 40~60 |

## v1.5.1 — 词表补齐：基准词 + 质量词，基准覆盖率 55% → 97%（2026-09-10）

承接 v1.5.0。用群内那条真实提示词（62 词）当尺子量覆盖率，起点只有 **55%**。

### 缺的不是生僻词，是最基础的"基准词"

系统扫描 82 个常见 Danbooru 基准名词，**缺 40 个**：
`breasts` / `thighs` / `hair` / `eyes` / `legs` / `arms` / `hands` / `feet` / `ears` / `stomach` /
`bow` / `socks` / `shoes` / `boots` / `apron` / `hood` / `jewelry` /
`water` / `fire` / `moon` / `sun` / `star` / `sky` / `cloud` / `tree` / `flower` / `snow` / `blood` /
`cup` / `bottle` / `chair` / `window` / `door` / `tongue` / `teeth` / `lips` / `nose` …

库里有 `small breasts` / `huge breasts` 却**没有 `breasts`**，后果有两层：
1. 表达不了"普通"状态，只能抽到带修饰的（`只有 thick thighs` → 永远是粗腿）；
2. 大/小、粗/细可能同时被抽中（`large breasts` + `small breasts`）。

同时质量/细节层整层缺失：`score_*` 全部 0 词、`ultra-detailed` / `huge filesize` /
`detailed pupils` / `sharp focus` / `amazing quality` 等（Anima 与群内提示词都在用）。

### 补齐方式

新增 `tools/add_base_vocab.py`（幂等，可复核）：按「槽位 → 词表」的显式清单补齐，
**只用真实标签、不生成组合**。共两轮：
- 第一轮 81 词：基准身体部位 / 服装 / 场景 / 物件 / 质量细节；
- 第二轮 25 词：全部取自群内那条提示词（即在用的词），含颜色+物体复合词
  （`black choker` / `white bow` / `black sailor collar` / `black pantyhose` …）。

⚠ 两个必须同时写的库：`library.get_merged()` 走 `deep_merge` 且**用户库优先**，
只写出厂库时新增词会被用户库同 id 子分类整个覆盖（实测 81 词只生效 16 个）。

⚠ 每条标签必须有 `id`：`deep_merge` 是按 id 归并的，无 id 的标签会全部塌成同一个
`None` 键互相覆盖。已把 **id 兜底**加进 `schema.migrate_subcategory`（`{子类id}.{en把空格换成-}`，
同槽位冲突自动加序号），历史数据一并回写。

### 质量槽配额调整

参考提示词的质量/细节块约 16 个词，故放宽这两槽：
`画质规格/画质增强` (3,2) → **(5,3)**；`画质规格/细节强化` (2,1) → **(4,2)**。

### 结果

| 指标 | 起点 | 现在 |
|---|---|---|
| 库内词数 | 4352 | **4448** |
| 群内基准覆盖率 | 55% | **97%**（60/62） |
| 输出词数 | 200~213（v1.5.0 前） | 中位 **60**，区间 40~60 |
| 门禁 | 10 项 | **11 项**（含输出质量门禁） |

仍缺 2 个：`plana (blue archive)` 与 `blue archive` —— 具名角色 + 作品（copyright），
属于另一类数据（character / series），需要单独的词表来源，不在本次范围。

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
