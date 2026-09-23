# ComfyUI-TagLibrary 全面审查报告

> ⚠ **历史文档** —— 1.12.0 已删除 `.md` 镜像层（`data/default/taglib/` 现在只剩规则 .json），
> 文中「镜像目录 / 标签文件同步 / 单向删除 / 文件夹式存储」相关章节不再适用。
> 当前形态以 README.md 与 CHANGELOG.md 为准。


> 日期：2026-09-20
> 范围：全仓（Python ≈6000 行 / 前端 7238 行 / 24 项门禁 / 77 个测试脚本）
> 方法：四路并行代码深潜 + 关键结论本人逐条复核（含沙箱实验）
> 前序文档：`docs/CODE-CLEANUP-AND-OPTIMIZATION-PLAN.md`（2026-09-19，覆盖后端结构；本报告不重复其已修项）

---

## 0. 审查方法与证据可信度

本报告每条结论标注来源，便于复核：

| 标记 | 含义 |
|---|---|
| **【复核】** | 我在本次审查中亲自读码/跑实验确认，附可复现命令或行号 |
| **【读码】** | 通过代码检索定位，未单独跑实验 |
| **【待核】** | 由深潜分析给出、我未逐条验证，采纳前需确认 |

关键实验（沙箱内执行，未触碰仓库 `data/`）：

- 探针 1：`ext` 词表与 git 跟踪镜像做**精确分词**交集（排除 `ass`/`oral` 类子串假阳性）
- 探针 2：直接调用 `tagmirror._desired_files()`，对比「带 skip / 不带 skip」两种期望文件集
- 探针 3：在 `tempfile.mkdtemp()` 沙箱里交替调用两条镜像路径，实测文件增删与内容哈希
- 探针 4：计算 `ext 词集 − 出厂库词集`，得出**真泄漏词**集合

---

## 1. 结论摘要

### 1.1 缺陷分布

| 层级 | P0 | P1 | P2 | 小计 |
|---|---|---|---|---|
| UI 布局与视觉 | 0 | 11 | 9 | 20 |
| 交互逻辑与操作习惯 | 3 | 8 | 8 | 19 |
| 系统架构 | 1 | 5 | 6 | 12 |
| 交付链与文档一致性 | 1 | 9 | 5 | 15 |
| **合计** | **5** | **33** | **28** | **66** |

### 1.2 最该先看的 5 件事

| # | 问题 | 性质 | 为什么排最前 |
|---|---|---|---|
| 1 | **两条镜像路径互相打架**：`mirror_folder_now` 不带 ext 过滤，`sync_to_folder_snapshot` 带 | 架构缺陷 | **【复核】** 实测交替调用会重写 33 个 git 跟踪文件、增删 7 个 ext 槽位镜像，把 **81 个出厂库不存在的词**写进跟踪区。这是 `library.py:599-600` 记的「镜像不幂等 → 指纹难以收敛 → 每次全量重跑」的**真正活根因**，前序文档只修了读路径挂载点，没修这个 |
| 2 | **🎲 填充静默清空用户手挑的标签，且失败零提示** | 交互缺陷 | **【复核】** `taglibrary.js:508-513` 只保留 📌 钉选与排除类目内词，其余全删；`:537-538`/`:549` 失败直接 `return`。用户历史上骂过的「覆盖有问题，越填越多」就是它 |
| 3 | **默认排除「画师」轴，但节点面板没有任何地方显示或可改** | 交互缺陷 | **【复核】** `taglib-common.js:212` 默认 `exclude_categories:["画师"]`，全仓仅挑选器侧栏抽屉可见。用户会判定「画师词抽不出来 = 库坏了」 |
| 4 | **`.tl-seg` 在同一个 CSS 里被定义两次，第二个覆盖第一个** | 视觉缺陷 | **【复核】** `tagpanel-css.js:216-225` 的 `.active{color:#fff;background:rgba(84,160,255,.30)}` 被 `:334-338` 的 `.active{background:var(--tl-hover)}` 覆盖 → 模式/性别/涩度三处分段按钮的**选中态与 hover 几乎同色**，等于没有选中态 |
| 5 | **README 与实现大面积不一致（版本/规模/页签数/功能引用）** | 交付缺陷 | **【复核】** 同一份 README 内：`:194` 写「当前版本 v1.7.0」、`:18` 写「v1.8.0 / 1.8.1」，`pyproject.toml` 是 1.8.0，CHANGELOG 无 1.8.1；`:6` 写「13 条轴 / 73 槽位」、`:13` 写「12 条轴」、`:48` 写「5 页签」（实际 7） |

---

## 2. UI/UX 布局与界面设计

### 2.1 布局与空间分配

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| L1 | P1 | 面板底部可能被裁：holder 用 `--comfy-widget-height` 兜底 60% + `min-height:160px`，但面板内容（头部 40 + 工具条 30 + 控件多行 + chip 区 58 + 预览 40）最小远超 160px，且 `.taglib-panel{overflow:hidden}` 无滚动 | 【读码】`tagpanel-css.js:108,130`；`taglibrary.js:1793-1794` |
| L2 | P1 | 挑选器顶栏不换行：`.tp-head` 无 `flex-wrap`，内含标题 + 7 个 `white-space:nowrap` 页签 + 最小 150px 搜索框；弹窗可窄至 `min(92vw,1440px)`，窄屏下页签被推出可视区 | 【读码】`taglib-picker.js:27-31,78-83`；`taglibrary.js:1286` |
| L3 | P1 | 管理页顶栏不换行且 `html,body{overflow:hidden}`：9 个按钮 + 240px 固定宽搜索框，iframe 变窄时右侧按钮被裁且滚不到 | 【读码】`manager.css:54-57,82-93` |
| L4 | P1 | 除面板 holder 外**全部高度硬编码视口单位**，无一处跟随宿主变量 | 【读码】`manager.css:78,290,293,453,485,502,546` |
| L5 | P2 | 控件区 `flex-wrap` 在节点最小宽 420px 下折 3~4 行，把 chip 区压到 58px 下限 | 【读码】`tagpanel-css.js:317`；`taglibrary.js:1821` |
| L6 | P2 | 嵌套滚动陷阱：`.tp-cats{overflow-y:auto}` 内再嵌 `.tp-exc-body{max-height:44vh;overflow-y:auto}`，滚轮归属不确定 | 【读码】`taglib-picker.js:39,133` |
| L7 | P2 | 节点最小尺寸全为 px（420/280/300/560），不随 ComfyUI 画布缩放 | 【读码】`taglibrary.js:1505-1506,1820-1821` |

### 2.2 视觉层级与一致性

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| V1 | P1 | **`.tl-seg` 重复定义导致选中态失效**（摘要第 4 条） | 【复核】`tagpanel-css.js:216-225` vs `:334-338` |
| V2 | P1 | 大量硬编码色未随主题切换：`.tl-ttag`、`.tl-nsfw-btn.on`、`.tl-search`、`.tl-chipzone`、`.tl-preview` 用固定 `rgba(255,255,255,.05)` / `#99a2b3` / `rgba(0,0,0,.38)`，浅色主题下对比度极低 | 【读码】`tagpanel-css.js:175,205,231,265-276,377` |
| V3 | P1 | **两套变量集漂移**：注释声称三处共享 `.tl-scope`，但 `manager.css` 自带独立 `:root`，同名变量值不同（`--tl-danger #ff6b6b` vs `--danger #ff7675`、`--tl-ok #7dd47d` vs `--ok #2ecc71` 等）→ 同屏可见的绿/红语义不一致 | 【读码】`tagpanel-css.js:10-11`；`manager.css:6-27` |
| V4 | P2 | 圆角未 token 化：并存 6/7/8/9/10/11/12/14px | 【读码】`tagpanel-css.js:125,157,232,295`；`manager.css:108,286` |
| V5 | P2 | 面板缩放只改 `container.style.fontSize`，子元素多写死 `font-size:11px` 覆盖继承 → 缩放对一半文本无效 | 【读码】`taglibrary.js:283`；`tagpanel-css.js:158,209,302` |

### 2.3 控件语义与可发现性

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| C1 | P1 | chip 同时是读数与开关：绿=启用/灰=停用靠颜色承担语义，点击即 toggle，但**启用态不提"可点击关闭"**，也无 hover 形变 | 【读码】`taglibrary.js:345-366`；`tagpanel-css.js:251-284` |
| C2 | P1 | 双类冲突：同一元素挂 `tl-sw tl-nsfw-btn` / `tl-sw tl-scene-btn`，后者把 `flex:0 0 auto` 改成 `flex:1`、圆角从 9px 改 7px → 同为开关却宽度乱跳、形状不一致 | 【读码】`taglibrary.js:101,115-127`；`tagpanel-css.js:323-331,414-431` |
| C3 | P1 | 管理页分类重命名/删除**仅 hover 可见**，键盘与触摸设备不可达 | 【读码】`manager.css:168-169` |
| C4 | P2 | 假可点：depth>0 的 `.tp-chev` 有 `cursor:pointer` 但无点击处理 | 【读码】`taglib-picker.js:49,497,506-508` |
| C5 | P2 | 失效按钮仍可点：`.pl-badge` 恒为 pointer，数据为空时点击无反馈 | 【读码】`taglib-pipeline.js:42,154,222` |

### 2.4 信息架构

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| I1 | P1 | 高频项埋在 ⋯ 菜单：显示语言（跨会话偏好）要点 3 层才能改 | 【读码】`taglibrary.js:136-162` |
| I2 | P1 | **改完看不到变化**：应用预设后立即 `e.target.value=""`，导致 ⋯ 按钮上的 `dirty` 读数圆点不点亮；`exclude_categories` 在面板完全无展示 | 【读码】`taglibrary.js:1364-1368,1004,625-631` |
| I3 | P2 | 静默失败：`🎲` 无 picks 直接 return，无 toast | 【复核】`taglibrary.js:549` |
| I4 | P2 | 面板丧失浏览能力：`activeCat` 已成死变量，面板只能看"已添加"，浏览全库必须开弹窗 | 【读码】`taglibrary.js:81` |
| I5 | P1 | 注释与实现不符：`:993-995` 仍写"低频操作集中在 ⋯（性别/防冲突）"，这两项实际已移到面板主体 | 【读码】`taglibrary.js:993-995,109-129` |

### 2.5 可访问性

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| A1 | P1 | ⋯ 菜单开完即 `blur()`，Esc 监听挂在 `container` 上，焦点既不在按钮也不在菜单 → 键盘用户开不了也关不掉 | 【读码】`taglibrary.js:1017,1028-1033` |
| A2 | P1 | 分类操作键盘不可达（同 C3） | 【读码】`manager.css:168` |
| A3 | P2 | 开关有 `role="switch" aria-checked` 但无可访问名（标签是兄弟节点，未用 `aria-labelledby`） | 【读码】`taglibrary.js:101,115-127`；`tagpanel-css.js:321` |
| A4 | P2 | 独立管理页 `manager.html:2` 只有 `lang="zh-CN"`，**缺 `translate="no"`** → 直接访问 `/taglib` 时标签英文可被浏览器翻译改写 | 【读码】`manager.html:2` |
| A5 | P2 | 右键 chip 菜单无键盘/Esc 支持；toast 无 `aria-live` | 【读码】`tagpanel-css.js:398`；`taglib-common.js:26-31` |

### 2.6 重复实现与腐化

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| D1 | P1 | "三视图共用原语"名不副实：`bindEditable` 仅武器档案用，互斥域手写 `input[data-g]` 绑定，NL 视图全部手写 | 【读码】`taglib-picker.js:5,1361,1438-1444,1538-1608` |
| D2 | P1 | 保存逻辑两份：`editorFoot` 与 `postJson` 各实现一套 POST + 三态色 | 【读码】`taglib-picker.js:1104,1171` |
| D3 | P1 | 预设逻辑四份且漂移：两处配置键列表不一致（一处含 `max_props_total`，另一处漏） | 【读码】`taglibrary.js:608,637,628`；`taglib-picker.js:853,885,850-851` |
| D4 | P1 | 死代码：`cycleGender` 被调用但**从未定义**；`cycleLang` 访问已不存在的 `.tl-lang-val`；`manager.js:481 touched()`、`taglib-picker.js:522 findColor / 636 appendGrid`、`taglib-pipeline.js:228 host._plEsc` 均无调用方；CSS `#tagTable*`(205-217)、`.cell-input`、`.tl-stchip`(344)、`.tl-ninten-btn`(433) 无对应 DOM | 【读码】`taglibrary.js:1037,897`；`manager.css:205-219`；`tagpanel-css.js:344,433` |
| D5 | P2 | `escapeHtml` 五份实现 | 【读码】`taglib-common.js:10`；`manager.js:414`；`taglib-picker.js:1150,1239`；`taglibrary.js:847` |
| D6 | P2 | tooltip 字面量错误：`"...编辑标签\\n左键拖拽..."` 把 `\n` 当普通字符渲染 | 【读码】`manager.js:395` |

### 2.7 UI 层按性价比排序的 Top 8

1. 合并 `.tl-seg` 重复定义（改 1 处修复 3 组控件的选中态）
2. 化解 `.tl-sw` 与 `.tl-scene-btn`/`.tl-nsfw-btn` 双类冲突
3. 浅色主题硬编码色 token 化
4. 两处顶栏允许换行/滚动
5. chip 明示"可点击关闭" + hover 形变
6. 管理页分类操作改为常显或 `:focus-within` 可见
7. ⋯ 菜单焦点管理（去 blur + 焦点移入首项）
8. 清死代码 + 统一变量集（降低后续所有视觉修复的误伤面积）

---

## 3. 交互逻辑与操作习惯

### 3.1 状态可见性

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| S1 | **P0** | 默认排除「画师」轴，面板无任何展示 | 【复核】`taglib-common.js:212`；`taglib-picker.js:733` |
| S2 | P1 | 挑选器改排除类目后，**节点面板预览不刷新**（只写 state 未调 `onNodeState`），面板清理时又被 `libTouched` 卡住 | 【读码】`taglib-picker.js:360-370,757-828,874,1072`；`taglibrary.js:1303-1308` |
| S3 | P1 | `preview_mode` 持久化后重载不生效：configure 之前读 state，`refresh()` 未回写 `ui.previewMode` | 【读码】`taglibrary.js:79-80,1383-1397,399,964-971` |
| S4 | P2 | 预设"已选中"圆点不亮、🗑 删除按钮总弹"请先选中" | 【读码】`taglibrary.js:1364-1368,1004,703-706` |

**持久化边界**（`selection_state` 随工作流序列化，`nodes.py:95`、`taglibrary.js:1735-1742`）：

- 能存：tags / exclude / nsfw / gender / preview_mode / solo_lock / bg_mode / focus_mode / nsfw_intensity / total_min·max
- **会丢**：面板搜索词、展开态、`_mutexDropped` 冲突标记、挑选器未确认的 `picked`、预设选中态
- 全局项（默认模式/NSFW/比例/语言）走 ComfyUI settings，**跨节点共享** —— 工作流里有多个 TagLibrary 节点时，改全局会波及所有节点，而节点面板上看不到这个层级

### 3.2 控件-语义匹配

现状**基本合规**（开关=开关、多档=分段、选择=下拉、动作=按钮），用户 2026-09-19 立的铁律已落实。残留两处：

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| M1 | P2 | 预设下拉被当"动作按钮"用（选完即回退占位符），用户直觉"选中应保持" | 【读码】`taglibrary.js:1364-1368` |
| M2 | P2 | 死代码里仍留着"点一下循环"的 `cycle*` 家族（菜单项已删），`cycleLang` 还会抛错 | 【读码】`taglibrary.js:219-227,892-900,928-935,1037-1041` |

### 3.3 操作闭环与反馈

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| F1 | **P0** | `🎲` 填充失败/无结果静默 `return`，用户无法区分"卡住"与"无结果" | 【复核】`taglibrary.js:537-538,549` |
| F2 | P1 | 互斥规则过滤掉的词**手动填充时零提示**：接口已返回 `dropped`，`rollFill` 只读 `picks` | 【读码】`api/v13_routes.py:158`；`taglibrary.js:539-548`；仅 auto 执行的 `executed` 回显才画删除线 `:1933,346` |
| F3 | P1 | 无 loading 态：`rollFill`、首次拉全量库（1.27MB）只弹 toast | 【读码】`taglibrary.js:503,1277-1279` |
| F4 | P2 | **生效时机不一致**：场景开关立即重抽，而防冲突/NSFW/性别只重渲染不重抽 → 用户以为没生效 | 【读码】`taglibrary.js:1358` vs `973-977,239-244,255-262` |

### 3.4 高频路径长度

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| P1 | P1 | **面板无"一键复制"**：预览条是纯文本 div，复制按钮只在"批量探索"弹窗卡片里。核心任务"把结果复制到别的节点"只能靠拖线连 `➡️ 正面提示词`，或手动框选 | 【读码】`taglibrary.js:132-135,1106-1116,1530` |
| P2 | P2 | 视线跨屏：模式分段在面板顶（`:88`）、`🎲` 在面板底（`:134`），节点最小高 560，一次"选模式→填充→看预览"要在首尾来回扫 | 【读码】`taglibrary.js:88,134,1820` |
| P3 | P2 | `positive` 与 `tags_preview` 两个输出内容完全相同，用户困惑差别 | 【读码】`nodes.py:170` |

### 3.5 危险操作防护

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| R1 | **P0** | `🎲` 填充**静默清空**非钉选标签，无二次确认、无撤销 | 【复核】`taglibrary.js:508-513` |
| R2 | P1 | 「清空标签」无确认（danger 菜单项） | 【读码】`taglibrary.js:204-206,161` |
| R3 | P1 | 挑选器已选 `picked` 遇点遮罩/切页即**静默丢弃** | 【读码】`taglibrary.js:1335`；`taglib-picker.js:1836-1837` |
| R4 | P2 | 标签级删除无确认；应用预设无确认（会覆盖 exclude 与配置） | 【读码】`taglibrary.js:461-466,623-631` |

**已做对的**：清空书库二次弹窗（`manager.js:1350-1368`）、恢复默认库 confirm（`:1321`）、导入 dirty 时 confirm（`:749`）、双向同步危险提示（`:1381`）、预设管理页删除 confirm（`:1193`）。

### 3.6 术语与心智模型

**【读码】P1** —— 不看代码不懂的自造词（用户原话是「按人的交互来，你这交互怎么用？」）：

`段位` / `轴` / `槽位` / `孙分类`（挑选器里"轴=大类、槽位=子分类"混用）、`档案` / `束` / `挂载槽位` / `状态槽`、`互斥域` / `跨池规则` / `池`、`吸收器`、`分轴重摇`、`自动配额`、`骨架`、`NL 句式` / `尾段`、`涩度` / `纯欲档`。

典型困惑场景：「"互斥域"跟"跨池规则"到底啥区别？我就想让两个词别同时出现。」

### 3.7 空态与边界态

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| E1 | P2 | 面板加载失败整体替换 `innerHTML`，**无重试入口**，必须刷新页面 | 【读码】`taglibrary.js:1379` |
| E2 | P2 | 空库与"搜不到"共用同一文案，无法区分 | 【读码】`taglib-picker.js:597` |

### 3.8 用户最可能先骂的 5 个点

1. **P0** 点 🎲 填充，手动挑的词被无声清空
2. **P0** 默认抽不到画师，排除项藏在挑选器里
3. **P0** 填充失败/被互斥过滤掉时毫无提示
4. **P1** 生成结果没法一键复制，只能拖线
5. **P1** 术语墙：档案束、互斥域、跨池规则、吸收器、槽位

---

## 4. 系统架构

### 4.1 前序文档已修项的复核结果

| 项 | 复核结论 | 证据 |
|---|---|---|
| `get_merged()` 不再写盘 | ✅ 已修 | **【复核】** `library.py:590-627` 已无 `_folder_hot_sync` 调用，注释 `:593` 记录了劣化实测数据 |
| `.md` 畸形标签往返 | ✅ 已修 | 【读码】`tagparse.py:25-36` 允一层嵌套括号；`schema.py:112-121` 就地还原 |
| 原子写抽公共工具 | ✅ 已修 | 【读码】`jsonio.py:18 atomic_write_json` 为全仓唯一写盘真源 |
| `api/_common.py` 去业务依赖 | ✅ 已修 | **【复核】** 只 import `os/re/aiohttp` |
| lint 门禁 | ✅ 已修 | 【读码】`tests/lint_check.py:21,33-50` |
| `tagfiles.py` 四拆 | ✅ 已修 | **【复核】** `tagfiles.py` 退化为 41 行 re-export 壳；`tagparse/tagmirror/tagsync/tagmeta` 已存在 |
| `engine.py` 闭包 → `_Extraction` | ✅ 已修 | 【读码】`engine.py:229-609` |
| GC 探针 / 计时插桩删除 | ✅ 已修 | 【读码】`nodes.py` 已无 `gc.callbacks`/`perf_counter` |
| **读路径副作用"移出"** | ⚠️ **只搬了一半** | **【复核】** `GET /taglib/api/tagfiles` 仍在 handler 内调 `library.hot_sync_now()`（`tagfiles_routes.py:26`），而 CSRF 中间件只拦写方法（`_common.py:123-125`）→ **GET 仍会写盘**，跨站 `<img>` 即可触发 |

### 4.2 【P0】两条镜像路径互不一致 → 跨路径不幂等

这是本次审查最有价值的发现，**前序文档未覆盖**。

**代码事实**【复核】：

```
library.py:563 sync_to_folder_snapshot()   ← 计算 skip_ens/skip_sub_ids 后传入
library.py:639 mirror_folder_now()         ← tagfiles.sync_to_folder(get_merged())  ← 不传任何 skip
```

调用点【复核】：

| 入口 | 调用 |
|---|---|
| `library_routes.py:205`（保存库） | `mirror_folder_now()` ← **无过滤** |
| `library_routes.py:321`（重置/恢复） | `mirror_folder_now()` ← **无过滤** |
| `tagfiles_routes.py:153`（导入标签文件） | `mirror_folder_now()` ← **无过滤** |
| `tag_edit_routes.py:179`（编辑标签） | `mirror_folder_now()` ← **无过滤** |
| `library.py:530/552/555`（热同步内部） | `sync_to_folder_snapshot()` ← 有过滤 |
| `tagfiles_routes.py:26`（GET 标签文件页） | `hot_sync_now()` → 同上 |

**原语级证据**（探针 2，纯计算）：`tagmirror._desired_files` 带 skip 产出 66 个文件，不带 skip 产出 73 个。

**沙箱实验**（探针 3，交替调用，同一目录）：

```
[轮1] 带 skip  : files_written= 66  files_removed= 0   目录内 .md = 67
[轮2] 不带 skip: files_written= 33  files_removed= 0   目录内 .md = 74   ← 多出 7 个 ext 槽位镜像
[轮3] 带 skip  : files_written= 26  files_removed= 7   目录内 .md = 67
轮3 内容是否与轮1 完全一致：True        ← 单路径内幂等
轮1↔轮3 内容不同的文件数 = 0            ← 单路径内幂等
```

**泄漏量化**（探针 4，精确分词，已排除子串假阳性）：

- `ext` 词表 298 个；出厂库 4448 个；`ext − 出厂 = 298` → **ext 完全增量，无重叠，设计意图正确**
- 不带 skip 的镜像会新写出 7 个 ext 专属槽位文件，含 **213 个出厂库不存在的词**：
  `体位`(19) / `性行为`(65) / `束缚与调教`(27) / `高潮与体液`(24) / `身体细节`(28) / `服装状态`(31) / `束缚道具`(19)
- 同时把 **26 个已跟踪的既有槽位文件**重写成含 ext 专属词版本，累计多出 **81 个词**（如 `外貌特征\体型\体型.md` +6：`hanging breasts` / `huge ass` / `large pectorals` / `muscular male` …）

**当前磁盘状态**：干净。`data/default/taglib/**` 磁盘 67 个 .md，git 跟踪 74 项，**0 个未跟踪**，ext 槽位目录**一个都没落盘**。

**为什么现在干净却仍是 P0**：

1. 它**已经在持续发生**，只是被下一次 `sync_to_folder_snapshot` 清掉了 —— 每个保存/编辑动作都会短暂把 ext 词写到跟踪区。任何 `git add -A` 撞在这个窗口里，露骨词就进发布包（Registry 1.x 被 ban 的同类事故）。
2. 它是 **33 个文件反复重写**的机制源：每次 `mirror_folder_now` 后紧跟 `sync_to_folder_snapshot`，同一文件内容在两版之间摆动 → mtime 抖动 → `_sync_state.json` 指纹难以收敛 → 热同步退回"每次全量跑 66 文件写"（`library.py:599-600` 记的正是这个现象，但把根因归给了 `.md` 往返，实际**两条路径不一致才是主因**）。
3. **门禁覆盖不到**：`tests/sync_idempotent_test.py:65-72` 只测 `sync_to_folder_snapshot()`（带过滤那条）；`tests/tag_edit_test.py:81-86` 更直接把 `mirror_folder_now` monkey-patch 成空操作。**唯一会泄漏的那条路径被测试主动屏蔽了**。
4. `README.md:34` 向用户承诺「发布包内不含任何露骨词」——该承诺的技术实现依赖"所有镜像都过滤"，现在不成立。

### 4.3 其他架构问题

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| N2 | P1 | `register_routes()` 非幂等：`app.middlewares.append` 无去重，重复注册时路由 `add_get` 抛错又被根 `__init__.py` 静默吞掉 → 中间件已入栈、路由失败。ComfyUI 重载节点后每个请求（含 ComfyUI 自身路由）多穿 N 层中间件 → **全站请求线性劣化** | 【复核】`api/__init__.py:41-47`；`__init__.py:14-17` |
| N3 | P1 | 文本拼装**三处重复**：`nodes._join_output`、`nodes._build_auto` 内联的 NL 尾段、`v18_routes._assemble_text`（`draw_batch`/`draw_reroll` 全走这份）。分隔符/去重/权重语法/`@` 前缀任一改动要改三处 → 面板预览与节点实出易漂移 | 【读码】`nodes.py:220-239,159-164`；`v18_routes.py:41-71` |
| N4 | P1 | **两套闸门**：引擎侧 `engine.py:287-304` 的 `tag_ok` 覆盖 nsfw/gender/gender_lock/minor；手动侧 `nodes.py:372-378` 独立重写，**不覆盖未成年锁 / gender_lock / teen 源排除** → 手动钉选未成年年龄词 + 露骨词时引擎拦、手动不拦 | 【读码】`nodes.py:372-378`；`engine.py:287-304` |
| N5 | P2 | 快照缓存键依赖跨模块**私有**函数：`runtime_snapshot.py:464-472` 直接调 `tagconflicts._mtime_c` / `grouprules._mtime` / `profiles._mtime`；`tagconflicts.py:35,122-123` 反向 import library 私有 → 改名不报错、缓存静默退化 | 【读码】 |
| N6 | P2 | `id(idx)` 作缓存键（`tagconflicts.py:269-275`）：`idx` 被 GC 后 id 复用可能命中**上一个库**的 en 全集 → 规则误判（低概率难复现） | 【读码】 |
| N7 | P2 | 死代码 / 冗余：`derive._SUGGEST` 只声明与 clear、从不读写（`derive.py:154,188`）；`_Extraction.minor_age` 在 `__init__` 先赋值又置 None（`engine.py:258,277`）；`_common._migrate_legacy_backup_layout` import 期执行两次（`_common.py:83,158`） | 【读码】 |
| N8 | P2 | URL 命名混用：`draw_batch` / `draw_reroll` / `absorb_add`（snake）vs `preview-import` / `restore-backup` / `axes-overview`（kebab） | **【复核】** `api/__init__.py:81-90` |
| N9 | P2 | `_sync_busy` 是模块级裸 bool，非锁；ComfyUI 执行线程与 aiohttp 线程可并发 → 可能双跑一次全量镜像 | 【读码】`library.py:424,519` |
| N10 | P2 | `serve_manager_page` 错误返回缺 `ok` 字段，与全仓统一格式不符 | 【读码】`library_routes.py:23` |

### 4.4 架构健康度评估（先说好的）

- **无循环依赖**，依赖方向基本正确（`tagparse` 是叶子，`tagfiles` 是壳）
- **热路径零 I/O** 的 `runtime_snapshot` 冷编译设计是全仓最值钱的部分
- **输出次第与抽取次序分离**（`axes.output_order` vs `pool_order`）语义正确且有防误改注释
- **落盘全部原子写**（`jsonio.atomic_write_json` 单真源）
- **规则真源外置**（`grouplib/*.json`）解决 `.md` 热同步重建 dict 抹字段的问题

### 4.5 门禁裸区

24 项门禁（离线 18 + 在线 6）覆盖引擎/抽取/NL/画质/数据/规则/HTTP/安全/性能/lint，但以下**无任何门禁**：

1. **镜像合规**：无断言"`.md`/`_tagmeta.json` 不含 ext 词" → §4.2 因此长期潜伏
2. **`mirror_folder_now` 路径**：`sync_idempotent_test` 只覆盖 snapshot 路径；`tag_edit_test` 主动屏蔽它
3. **`schema_version` ↔ `SCHEMA_VERSION` 不变量**：`schema.py:200-205` 的约束（"给出厂库补 `schema_version` 必须同步提高 `SCHEMA_VERSION`"）纯靠注释，`tests/` 非 `_scratch` 区 grep 无命中
4. **`deep_merge` 无 id 塌陷 / 三库合并语义**：`library.py:159-160` 用 `{d.get("id"): ...}`，无 id 全塌到 `None` 键互相覆盖；补 id 的 `migrate_subcategory` 在合并**之后**才跑（`get_merged`：620 merge → 623 migrate）
5. **`register_routes` 幂等 / 中间件去重**（N2）
6. **前端**：6438 行 JS 仅由 4 个**在线**门禁覆盖，离线 `run_gates.py` 对前端 **0 覆盖**；且覆盖以 DOM 计数/几何/配色为主。**`manager.js`(1674 行) 的保存/导入/备份/恢复流程无端到端门禁**
7. **API 契约兼容性**：无响应 schema/版本校验

---

## 5. 交付链与文档一致性

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| T1 | P1 | **节点分类未文档化**：`CATEGORY="纸心/prompt"`，README 全文无"纸心" → 用户 Add Node 菜单里对不上 publisher `wsyxiuba` | 【读码】`nodes.py:64` |
| T2 | P1 | **默认手动模式直接 Queue 出空串且不报错**，`mode` 无 default，ComfyUI 取首项 `manual` | 【读码】`nodes.py:100,379-384`；`taglibrary.js:1448` |
| T3 | P0 | **docs 截图全部过时**：`screenshot_axis_view/profiles/nl.png` 显示 8 页签 + 已删的"分类树/拼装轴"切换；`screenshot_manager.png` 标注"合计 1615 个标签"（v1.2.0 数据，实际 4448 词/13 轴）；`screenshot_node_panel.png` 是 pre-1.4.1 形态；`screenshot_nl.png` 无任何 md 引用（孤儿文件） | 【读码】`docs/*.png` 引用上下文 |
| T4 | P1 | README 内部数字打架（见摘要第 5 条）：版本 1.7.0 vs 1.8.0/1.8.1；轴数 13 vs 12；页签 5 vs 实际 7；互斥域 55+ vs 50；门禁 14 项 vs 实际 18/6 | **【复核】** `README.md:6,13,15,18,48,131,194`；`pyproject.toml` |
| T5 | P1 | `RELEASE_NOTES.md` 全文仅 v1.7.1 文案，与 `version=1.8.0` 不符 → Registry 发布说明会显示旧内容 | 【读码】`RELEASE_NOTES.md:1` |
| T6 | P1 | **发布链路缺版本锚点**：最新 git tag 为 `v1.7.1`，无 `v1.8.0`；且 v1.3.0 后直跳 v1.6.4，tag 断档 | 【读码】git tag |
| T7 | P1 | **升级被用户库"冻结"**：`deep_merge` 同 id 用户版整体优先，而 `tag_library.user.json` 是全量快照（实测 4448 条，与出厂同数）→ 凡在管理页保存过一次，出厂日后对既有词的任何修订**不会下发**，只追加新 id。README 里写的"升级不丢用户库"未警示此反作用 | 【读码】`library.py:157-167` |
| T8 | P1 | 「恢复备份库 → 出厂」会**永久屏蔽 102 个新词**：出厂源 `backups/factory_backup.json` 实测 4356 词且无 `axis`，经 `save_user_library` 写入后，底座差额进 `_tombstones`，升级也拉不回 | 【读码】`library_routes.py:306-320`；`library.py:407-408` |
| T9 | P1 | **开发文档随包发布**：`docs/` 三份（含内部品牌"纸心"、被 ban 相关讨论）会发给终端用户，且基线停在 v1.3.0/v1.4.0 | 【读码】`git ls-files docs/*` |
| T10 | P1 | **性能承诺无门禁背书**：README 称"p50 < 3ms"，`tests/perf_build_test.py:27-32` 的 SLA 表断言 P50≤10ms / P95≤20ms，**无 `<3ms` 断言** | 【读码】 |
| T11 | P2 | 数据组织三路打架：改 `.md` 会被热同步 pull 吸回；管理页 CRUD 写 user.json；直改 `tag_library.json`。`.md` 是有损投影 → 需 `_tagmeta.json` sidecar + 规则外置 | 【读码】`library.py:599-602` |
| T12 | P2 | `pyproject.toml` `Icon=""` 空图标；无 `requires-python` / `classifiers` | 【读码】`pyproject.toml:14` |
| T13 | P2 | 跟踪 `tests/` 78 文件含 `_scratch/` 52 个历史脚本，随包噪声 | 【读码】 |
| T14 | P2 | 出厂 `factory_backup.json` / `user_backup.json` 均 4356 词（落后 102 词、无 axis）随包发布 | 【读码】 |
| T15 | P2 | 磁盘未跟踪噪声：`data/packs/`、`profiles.json.bak`、`nl_flavors.json.pre-3c.bak` | 【读码】 |
| T16 | — | **已过期**：前序文档 §4.2 称遗留 zip 尚在 —— 实测 `node.zip` 与 `ComfyUI-TagLibrary-v1.2.0-r2.zip` **均已不在**（提交 `723f4b9` 已清） | **【复核】** |

**合规声明的诚实结论**【复核】：README「发布包内不含任何露骨词」**字面不成立**。实测 `data/default/tag_library.json`（git 跟踪、随包发布）含 `completely nude` / `ahegao` / `pubic hair` / `nude` / `nipples` / `topless`。但设计意图的核心部分**成立**：真正意义上的性行为露骨词（`sex` / `penis` / `vaginal` 等）**确实只在 ext 包里**，ext 与出厂库 0 重叠。结论：**表述过度承诺，机制基本正确**（§4.2 的路径漏洞是唯一真实缺口）。

---

## 6. 逐项优化方案与方案对比

> 每项给 2~3 条候选方案，标出优劣与推荐。所有方案均须满足：不破坏"热路径零 I/O"、可回滚、有门禁背书。

### 6.1 镜像双路不一致（P0）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 把 skip 计算上移为 `library._ext_skip_sets()`，两个入口共用 | 改动最小（约 15 行）；一处真源；立刻消除泄漏与抖动 | 不解决"读路径仍能写盘"（`tagfiles_routes.py:26`） | ✅ **先做这一半** |
| **B** | 删除 `mirror_folder_now`，所有写后镜像统一走 `sync_to_folder_snapshot` | 路径唯一，彻底消除分叉 | 丢"实时镜像"语义（分类改名要等下次热同步才落盘），改动面大 | ⚠️ 可作后续收敛目标 |
| **C** | 保留双路，但给 `sync_to_folder` 加"无 skip 时拒绝写出被 git 跟踪的路径"的硬保护 | 最安全，防未来新入口犯错 | 属防御性兜底，不解决内容摆动 | ✅ **与 A 叠加做** |

**推荐：A + C**。并把 `GET /taglib/api/tagfiles` 的热同步改成显式 `POST`（或前端加个"同步"按钮触发），彻底兑现读路径零副作用。

**必须补的门禁**：① 断言 `data/default/taglib/**/*.md` 与 `_tagmeta.json` 不含 ext 专属词；② 让 `sync_idempotent_test` 覆盖 `mirror_folder_now` 而非在 `tag_edit_test` 里屏蔽它；③ 交替调用两路径后断言文件集与内容哈希稳定。

### 6.2 填充静默清空（P0）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 改为"合并"语义：填充结果追加而非清空，钉选与手挑词都保留 | 最符合直觉（用户从未要求清空） | 与"排除类目控制覆盖范围"的既有设计冲突，会"越填越多" | ⚠️ 需配合去重 |
| **B** | 保留清空语义，但**改为可撤销**：弹一个"已替换 N 个标签（保留 M 个钉选）· 撤销"的 toast | 保留现有语义，风险最低，符合人机习惯（破坏性操作给退路） | 仍会打断心流一次 | ✅ **推荐** |
| **C** | 首次使用时弹一次确认，之后记住选择 | 不打断熟手 | 状态又要持久化，复杂度上升 | ⚠️ 不推荐 |

**推荐：B**，并同时把"被排除类目内的旧词会累积"这一分支显式化（现状是保留它们 → 越填越多）。

### 6.3 排除类目不可见（P0）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 面板 ⋯ 菜单加一行「排除类目 · N 项」，点开复用挑选器的抽屉 | 与现有结构一致，改动小 | 仍要点 2 层 | ⚠️ 可接受 |
| **B** | 面板控件区加一个常显 chip：「排除类目 1」，点击弹出多选 | 状态可见、一步可改，符合"常用项摆在面板上"原则 | 占 1 行宽度 | ✅ **推荐** |
| **C** | 取消默认排除「画师」 | 消除困惑 | 画师词是 tag 污染重灾区，默认不排会更吵 | ❌ 不推荐 |

### 6.4 填充失败/过滤零反馈（P0）

统一走一个轻量 toast 组件（已有 `taglib-common.js:26-31`，补 `aria-live`）：无结果 → "本次无可用标签（已排除 N 类目）"；被互斥过滤 → "N 个词与已选冲突已跳过"（接口已返回 `dropped`，只需读取）。

### 6.5 选中态失效 `.tl-seg`（P1）

一次替换：删掉 `tagpanel-css.js:216-225` 旧定义，只保留 `:334-338` 并把 `.active` 改为 `background:color-mix(in srgb, var(--tl-accent) 26%, transparent); color:var(--tl-accent-text)`。**同一文件内同名选择器定义两次是纯腐化**，建议同时加 lint 规则（CSS 重复选择器检测）。

### 6.6 主题与 token 漂移（P1）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 让 `manager.css` 直接复用 `.tl-scope` 变量集，删掉自己的 `:root` | 一套真源，同屏语义一致 | 管理页是独立页面，需确认 `.tl-scope` 能挂到 `html` 上 | ✅ **推荐** |
| **B** | 保留两套，但用脚本校验同名变量值一致 | 改动小 | 校验脚本本身要维护 | ⚠️ 退路 |
| **C** | 引入 CSS 变量生成层（构建期产出） | 最规范 | 插件无构建步骤，收益不抵复杂度 | ❌ |

同时把浅色主题下不可读的硬编码色（V2 的 5 处）全部换成 token。

### 6.7 布局硬编码高度（P1）

顶栏统一 `flex-wrap:wrap`（L2/L3）；页面高度改 `100dvh` 并让内层 `flex:1; min-height:0` 而非固定 px（L4）。**注意**：面板 holder 已经用 `--comfy-widget-height` 兜底，方向是对的，只需把 `min-height:160px` 抬到真实内容高度（约 300px）并允许内部 chip 区滚动，而不是让整块 `overflow:hidden` 裁掉。

### 6.8 术语墙（P1）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 每个自造词首次出现处加一句人话副标（"互斥域 · 不让这两个词同时出现"） | 成本低，不改结构 | 文字碎片化 | ✅ **推荐** |
| **B** | 在挑选器加一页"名词解释" | 集中 | 用户不会主动翻 | ❌ |
| **C** | 全面改名为通用词 | 最彻底 | 破坏用户已形成的肌肉记忆与工作流兼容 | ❌ |

### 6.9 高频路径：一键复制（P1）

预览条加一个 copy 按钮（复用已有 `taglib-common.js` toast）。这是核心任务的最后一厘米，成本极低。

### 6.10 文本拼装三路合一 / 闸门两套合一（P1）

抽 `format.py`（或并入 `engine`）暴露 `join_output()` 与 `tag_ok` 的纯函数谓词，`nodes.py` / `v18_routes.py` 三处调用同一实现，手动路径改调引擎闸门。**风险中**：必须由 `prompt_quality_test` + `node_output_test`（60 次生成文本层断言）守住。

### 6.11 `register_routes` 幂等（P1）

加模块级 `_registered` 哨兵 + 中间件按函数身份去重 + 捕获重复路由 `RuntimeError`。低风险，且消除"请求随重载线性变慢"的全站隐患。

### 6.12 文档与发布链（P0/P1）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | 重跑截图 + 人工核对数字 + 补 `v1.8.0` tag | 见效快 | 下次必然再漂 | ⚠️ 治标 |
| **B** | **A + 加"文档断言门禁"**：从 `axes.py`/`pyproject.toml`/`run_gates.py`/`taglib-picker.js` 读出真实值，断言 README 中的轴数/槽位数/词数/页签数/版本号一致 | 治本，数字类漂移永久消失 | 需写一个解析脚本 | ✅ **推荐** |
| **C** | 用脚本从代码生成 README 数字段落 | 最彻底 | README 是手工排版，生成段易与叙述脱节 | ⚠️ 部分采用 |

另外：`docs/` 三份开发文档移出发布包（加进 `.gitignore` 或移到 `docs/dev/` 并排除）；`RELEASE_NOTES.md` 更新到 1.8.x；`pyproject.toml` 补图标与 `requires-python`。

### 6.13 升级被用户库冻结（P1）

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A** | README 明确警示"在管理页保存过即冻结既有词的出厂更新" | 零代码风险 | 用户仍被冻 | ⚠️ 必做但不够 |
| **B** | 用户库存**差分**而非全量快照：只记与出厂库不同的 id | 从根上处理，出厂更新可下发 | 改数据格式，需迁移 | ✅ **中期推荐** |
| **C** | 加"出厂库有新版本"提示 + 一键对比合并（已有 `dismiss_upgrade_prompt` 雏形） | 用户可控 | 需 UI | ✅ 与 B 配合 |

### 6.14 巨型文件（P2）

`taglibrary.js` 1951 / `taglib-picker.js` 1868 / `manager.js` 1674。**按页签切分挑选器**（5 个页签天然独立）是最优边界；`manager.js` 可按"词库表格 / 批量工具 / 备份恢复"三块拆。注意 ComfyUI 只自动加载 `web/` 下 `.js`，拆出的文件须改 ES module 显式 import（现有 `/taglib/static/` 已覆盖整个 `_WEB_DIR`，无需改路由）。

---

## 7. 最优整体改进方案

### 7.1 三条整体路线的对比

| 路线 | 内容 | 优点 | 缺点 | 适用判断 |
|---|---|---|---|---|
| **① 点状修补** | 只修 66 条缺陷中最高优先的十几条，不动结构 | 2 天内可见效；风险最低 | 镜像双路、文本三路、巨型文件等根因留存 → 同类缺陷会再生；门禁裸区不补，下次还得人工审 | 只适合当过渡 |
| **② 契约优先的收敛式整改**（推荐） | 先把"单一真源 + 门禁"立起来（镜像过滤唯一化、文本拼装唯一化、闸门唯一化、文档数字断言化），再修用户可感知的交互断层 | 一次处理**复发类**缺陷；每条改动有门禁背书；改动集中在 5 处，回归面积可控；与既有架构（冷快照/原子写/真源外置）同向 | 前期需投入写 4~6 条门禁；部分修复要真机验证 | ✅ **本仓最优** |
| **③ 前端分层重写** | 7200 行前端重做成模块化 + 设计系统 | 是唯一能解决"1951 行单文件"这个缺陷密度成因的手段 | 不能独立先行：无安全网（离线门禁对前端 0 覆盖）+ `selection_state` 已进用户工作流（改结构会静默丢标签）+ 宿主耦合不可解 | ⚠️ **要做，但必须排在 ② 之后，且只能渐进**（见 §7.1b / ADR-001） |

**选 ② 的核心理由**：前序文档（9-19）已经证明这个仓库的架构底色是好的（无循环依赖、冷快照、原子写、真源外置），**问题不是架构烂，而是"同一个语义有两份实现"**。这一模式的复发（§4.2 的镜像双路、§4.3 的文本三路与闸门两套、§2.6 的预设四份、`escapeHtml` 五份）才是本项目缺陷的主要来源。收敛实现比推倒重写更对症。

### 7.1b ② 与 ③ 的组合结论（2026-09-20 增补）

> 用户提出「不考虑性价比，②与③哪个更好 / 可否都选」。完整决策见
> **`docs/decisions/ADR-001-frontend-strategy.md`**。要点：

**两者不是竞品，解决的是不同类问题**：②针对"同一语义多份实现"导致的行为漂移；
③针对"1951 行单文件"导致的缺陷密度。**可以都选，但必须串行，顺序不可颠倒**。

**③ 不能单独先行 —— 三条硬约束（与成本无关）**：

1. **没有安全网**：前端 6438 行 JS 仅由 4 个在线门禁覆盖，离线 `run_gates.py` 对前端 **0 覆盖**；
   `manager.js` 的保存/导入/备份/恢复**无任何端到端门禁**。无回归保护下重写等于蒙眼拆房。
2. **序列化契约已进入用户工作流文件**：【复核】`nodes.py:95-99` —— `selection_state` 是
   **required STRING 输入**、tooltip 写"自动维护，勿手改"。用户已保存的工作流里**已存了完整面板状态**；
   重写若改 state 结构，老工作流打开会**静默丢失全部已选标签且无报错**。
3. **宿主耦合是硬约束**：节点 DOM 挂载（同一 holder 有 3 份渲染克隆）、`--comfy-widget-height`、
   executed 回显、`translate="no"`、`serialize:false` 兜底 —— 重写后依然存在，
   只能做到"内部模块化"，做不到"解耦宿主"。

**③ 的正确形态是"分层渐进重写"**：保留状态层与序列化契约、宿主适配层、CSS 变量真源、接口契约；
只重做三视图的组件结构 + 控件原语（各一套）+ 设计系统 token。按 `manager.js` → 挑选器 5 页签 →
节点面板（风险递增）渐进，每步要求「全门禁绿 + 真机几何断言 + 打开重写前的旧工作流确认标签不丢」。
**禁止一次性大爆炸重写。**

**§7.2 的批次 2 整体并入阶段 C**：那 20 项视觉缺陷几乎全落在被重写的文件里，单独修等于白做；
仅保留 2~3 条「用户可感知且改动小于 5 行」的过渡补丁（首选删除 `tagpanel-css.js:216-225`
重复 `.tl-seg` 定义 —— 改 1 处修复 3 组控件选中态）。

### 7.2 分四批执行

#### 批次 0 · 合规与止血（当天可完成，风险极低）

| 序 | 事项 | 验收门禁 |
|---|---|---|
| 1 | `_ext_skip_sets()` 上移，`mirror_folder_now` 与 `sync_to_folder_snapshot` 共用 | 新增：`data/default/taglib/**` 不含 ext 专属词（精确分词，非子串） |
| 2 | `sync_idempotent_test` 覆盖 `mirror_folder_now`（删掉 `tag_edit_test` 里的 monkey-patch 屏蔽） | 交替两路径后文件集与内容哈希稳定 |
| 3 | `GET /taglib/api/tagfiles` 的热同步改显式 `POST` | 新增：断言 GET 路由不产生任何文件写入（比对 mtime 全集） |
| 4 | README「发布包内不含任何露骨词」改为准确表述 | — |
| 5 | `register_routes` 幂等化 | 新增：连续调用 2 次后中间件层数不变 |

**批次 0 做完，收益已到手七成**：合规缺口关闭、33 文件反复重写的机制源切断、读路径副作用归零、全站请求不再随重载劣化。

#### 批次 1 · 用户可感知的交互断层（最能改口碑）

🎲 填充改为可撤销 + 失败/过滤给反馈（§6.2/6.4）→ 排除类目在面板常显（§6.3）→ 预览条一键复制（§6.9）→ 危险操作补二次确认或撤销（R2/R3）→ 术语加人话副标（§6.8）→ ⋯ 菜单焦点管理（A1）。

#### 批次 2 · 视觉与布局（一轮真机截图验收）

`.tl-seg` 去重（§6.5）→ 开关双类冲突（C2）→ 浅色主题 token 化（V2/V3）→ 顶栏换行 + 高度去硬编码（§6.7）→ 单一主题变量集（§6.6）→ 清死代码（D4）→ chip 可点性明示（C1）。

> ⚠️ 本批必须**真机截图 + 几何断言**双验（`ui_v13_check` 已有零重叠/宽度统一/无溢出/无越界 4 条几何断言，继续复用），并按项目铁律用 huashu-chrome 接管用户浏览器，**不得另起调试实例**。

#### 批次 3 · 结构收敛与文档/发布链

文本拼装三路合一 + 闸门两套合一（§6.10）→ 文档数字断言门禁 + 截图重制 + 版本锚点（§6.12）→ `docs/` 移出发布包 → 用户库差分快照（§6.13）→ 前端按页签拆分（§6.14）。

### 7.3 需要新增的门禁（4~6 条，是方案②的骨架）

| 门禁 | 断言 | 挡住什么 |
|---|---|---|
| `mirror_compliance` | `data/default/taglib/**/*.md` + `_tagmeta.json` 不含 ext 专属词（精确分词） | §4.2 泄漏复发、发布被 ban |
| `mirror_path_parity` | 交替调用 `mirror_folder_now` / `sync_to_folder_snapshot` 后，文件集与内容哈希稳定 | 双路分叉复发 |
| `read_path_pure` | 全部 GET 路由执行前后，`data/` 下 mtime 全集不变 | 读路径副作用复发 |
| `schema_invariant` | 出厂库 `schema_version` 存在时必等于 `SCHEMA_VERSION` | §4.5-3 的隐式契约 |
| `doc_numbers` | README 的轴数/槽位数/词数/页签数/版本号 == 代码实际值 | 文档数字漂移复发 |
| `route_idempotent` | `register_routes()` 调用 2 次后中间件数不变 | N2 复发 |

### 7.4 明确不建议动的地方

| 项 | 理由 |
|---|---|
| 三级合并 `deep_merge`（default ← ext ← user） | 用户库整体优先是"保留用户编辑"的基石；改字段级合并会让用户改动被静默覆盖（但**要补无 id 塌陷门禁**，见 §4.5-4） |
| `_trim_to_budget()` 按槽位削减 | 曾被改回朴素截断，导致靠后的 style/material/camera 被系统性砍光 |
| `runtime_snapshot` 冷编译 + 只读快照 | 全仓性能基石 |
| `axes.output_order` 与 `pool_order` 分离 | 语义正确（人数词须先抽才能锁性别），已有防误改注释 |
| 规则真源外置（`grouprules.json` / `conflicts.json`） | 直接原因是 `.md` 热同步会重建标签 dict |
| `.md` 镜像机制本身 | 是"文件夹式词库"核心卖点，只是不该双路、不该挂读路径 |

### 7.5 执行顺序总表

| 批次 | 事项数 | 风险 | 前置 | 验收方式 |
|---|---|---|---|---|
| 0 合规止血 | 5 | 极低 | 无 | 4 条新门禁 + 沙箱复现脚本转正 |
| 1 交互断层 | 6 | 低 | 批次 0 | 真机点击验证（huashu-chrome） |
| 2 视觉布局 | 7 | 中 | 批次 0 | 真机截图 + 几何断言 |
| 3 结构收敛 | 5 | 中 | 批次 1/2 | `prompt_quality_test` + `node_output_test` 全程守护 |

---

## 8. 附：本次复核纠正的三处判断

审查过程中，深潜分析给出了若干偏重的结论，我复核后予以修正，记录在此便于复核：

| 深潜结论 | 复核结果 | 修正依据 |
|---|---|---|
| 「`mirror_folder_now` 导致露骨词已落 git 跟踪的 `.md`」**P0 现行泄漏** | ❌ 不成立 —— 现磁盘干净，67 个 .md / 0 未跟踪 / ext 槽位镜像未落盘 | 探针 1（精确分词，初版子串匹配的 46 个命中里绝大多数是 `ass`/`oral` 撞 `grass`/`class` 的假阳性）；探针 4 |
| 同上问题的真实性质 | ✅ 修正为：**潜在泄漏 + 活着的跨路径不幂等**（每轮重写 33 文件、增删 7 文件、81 个 ext 专属词短暂进入跟踪区） | 探针 2/3/4；`sync_idempotent_test.py:65-72` 与 `tag_edit_test.py:81-86` 证明该路径被测试屏蔽 |
| 「README 合规声明为假 → 出厂库含露骨词 = 发布违规」 | ⚠️ 部分成立 —— 字面承诺不成立（`completely nude`/`ahegao`/`pubic hair` 确在跟踪的出厂库中），但**设计意图成立**：`sex`/`penis`/`vaginal` 等性行为词确实只在 ext 包，ext 与出厂库 **0 重叠** | 探针 4：`ext − 出厂库 = 298`（完全增量） |
| 「前序文档称遗留 zip 尚在」 | ❌ 过期 | **【复核】** `node.zip` / `ComfyUI-TagLibrary-v1.2.0-r2.zip` 均已不存在（提交 `723f4b9`） |

---

## 9. 一句话总结

这个仓库的**架构底色是好的**（无循环依赖、冷快照、原子写、真源外置），**问题不是架构烂，而是"同一个语义有两份实现"**：镜像有两条路径、文本拼装有三个实现、闸门有两套、预设逻辑有四份、`escapeHtml` 有五份。因此最优解不是推倒重写，而是**先把"单一真源 + 门禁"立起来（批次 0，当天可完成，收益七成），再修用户真正会骂的交互断层（批次 1），视觉与结构随后**。
