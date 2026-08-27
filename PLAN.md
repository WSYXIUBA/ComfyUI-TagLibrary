# ComfyUI 标签库节点 完整方案 v2

> v2 变更：① 所有组成部分讲清楚"是什么、住在哪、指向哪里"；② 标签库管理改成**独立 Web 页面**（http://127.0.0.1:8188/taglib 直达），ComfyUI 界面加按钮弹出全屏窗口（嵌同一页面）；③ 补数据流：谁读谁写哪个文件。

---

## 一、项目做完后，你会看到哪几个"东西"

| # | 东西 | 它是什么 | 住在哪 / 怎么见到它 |
|---|------|---------|-------------------|
| 1 | 「🏷 标签库」节点 | 一个普通的 ComfyUI 节点方块，跟 CLIPTextEncode 同类，有输入口输出口能连线 | 画布空白处双击搜"标签库"，或右键→添加节点→纸心/prompt→标签库 |
| 2 | 节点小面板 | 长在该节点方块内部的选标签控制区（分类条/chips/已选区/模式/seed）。"面板"是节点身上的皮肤，不是独立程序 | 把节点拖出来就能看到；改动只影响当前工作流这一个节点 |
| 3 | 标签库管理页 | **独立的完整网页**，库的全部增删改查都在这做 | 浏览器直达 `http://127.0.0.1:8188/taglib`；或 ComfyUI 顶栏"标签库→打开管理页"按钮弹出全屏窗口（嵌入同一个页面）；或节点面板上的 ⚙ 小按钮 |
| 4 | 库数据文件 | 标签库的真实本体，就是个 JSON 文件，任何编辑器可直接改 | `D:\aiv4\ComfyUI\custom_nodes\ComfyUI-TagLibrary\data\tag_library.user.json`（用户库）+ `tag_library.json`（默认库，随插件发） |

## 二、整体架构（谁能看见什么）

```
你的浏览器 (127.0.0.1:8188)
 ├── ComfyUI 主界面（原有画布）
 │     └─ 🏷 标签库节点 ← 上面挂着小面板(web/taglibrary.js 渲染)
 │     └─ 顶栏「标签库」按钮 / 节点⚙按钮 ──┐
 │                                       │点击
 ├── 新标签页: http://127.0.0.1:8188/taglib ◄─┘ （全屏弹窗版=iframe 嵌同页）
 │     └─ 标签库管理页 (web/manager.html)
 │            │ 改库 POST
 │            ▼
 └── 同一台 ComfyUI 服务进程里的插件后端 (Python)
       ├─ api.py:  GET/POST /taglib/api/library …
       │     写 → data/tag_library.user.json（用户库，永不被更新覆盖）
       ├─ nodes.py: TagLibraryNode 执行时
       │     读 → default + user 深合并 → 按模式算出 STRING 输出
       └─ 工作流 JSON: 节点的 selection_state（点了哪些标签等）
             存在你保存的工作流文件里，跟工作流一起备份/分享
```

分工原则：**管理页管"库"（全局共享，一次编辑处处生效）；节点小面板管"这次用哪些"（每个工作流各自独立）。**

## 三、标签库管理页（独立页面）详细设计

### 3.1 页面布局

```
┌─ 🏷 标签库管理 ──────────────────────────────────────────────┐
│ [➕新建分类] [📥导入] [📤导出] [↺恢复默认库]   🔍搜中文/英文/别名│
├───────────┬────────────────────────────────┬───────────────┤
│ 分类树     │ 子分类页签: [体型][发型][表情][姿势]…│ 统计           │
│ 👤人物     │ ┌────────────────────────────┐ │ 👤人物 214     │
│  ·体型     │ │ 英文        中文  权重 别名 启用│ │ 🖼背景 96      │
│  ·发型     │ │ slim       纤细  1.0 slender☑│ │ 💡光影 88      │
│  ·表情 ●  │ │ curvy      丰满  1.0       ☑│ │ …             │
│ 🖼背景     │ └────────────────────────────┘ │ 合计 812       │
│ 💡光影     │ [➕添加标签] [📋批量粘贴添加]      │               │
│ 🎨画风 ... │                                │               │
│ (拖拽排序) │                                │               │
├───────────┴────────────────────────────────┴───────────────┤
│ ● 有未保存修改                [取消]  [💾保存更改]             │
└──────────────────────────────────────────────────────────────┘
```

- **左栏分类树**：所有一级分类，右侧显示该分类下已选数量徽标（联动节点）。支持拖拽调整顺序、新增（填名称+挑 emoji 图标+挑分类颜色）、重命名、删除（删除需二次确认）。
- **中栏**：先切子分类页签，下面是标签表格，行内直接编辑英文/中文/权重/别名/启用勾选；"批量粘贴添加"支持一行一条 `english | 中文 | 权重` 粘贴导入几十条。
- **右栏统计**：各分类标签数、总修改时间、空分类提示。
- **底部显式保存按钮**：改动先攒在内存标脏，点保存才写盘（符合你要的"明确保存"，不要自动静默写）。
- 导入/导出：JSON 全量互传（把库分享给别人），另支持导出 wildcard 兼容 txt（每分类一个段落）。

### 3.2 技术实现（就一个静态 HTML 文件）

- `web/manager.html` + `manager.css` + `manager.js`，纯原生无框架（和路线 A 一致，防前端版本漂移）。
- 插件后端注册两个路由：
  - `GET /taglib` → 直接返回 manager.html（这样浏览器地址栏就能打开，不需要 ComfyUI 前端在场）
  - `/taglib/api/*` → 数据接口
- ComfyUI 内的两个入口：
  1. 顶栏菜单：`registerExtension({ commands:[{id:'zhixin.openTagLib', function(){window.open('/taglib')}}], menuCommands:[{path:['标签库'],commands:['zhixin.openTagLib']}] })` → 顶部出现"标签库→打开管理页"
  2. 节点面板头部 ⚙ 按钮 → 弹出 `<dialog>` 全屏遮罩，里面 `<iframe src="/taglib?embed=1">` 加载同一页面（embed 参数隐藏外框样式，看起来就是展开的大窗口）
- 同源部署（页面和 ComfyUI 都是 8188 这一个服务），iframe/fetch 无跨域问题。

## 四、数据流（谁读谁写什么）

1. **你在管理页点保存** → 浏览器 POST `/taglib/api/library` → api.py 校验 schema（分类 id 唯一、字段齐全、id 无非法字符）→ 原子写入 `.user.json`（临时文件+rename，断电不写坏）→ 管理页显示"✓ 已保存 HH:MM"。
2. **节点每次执行（Queue）**：nodes.py 读 default + user 两份文件深合并成完整库 → 按 mode 计算 → 输出 STRING。所以管理页改完，不用重启，下一次 Queue 就生效。
3. **节点小面板的点选状态**：序列化进 workflow JSON 里该节点的 widgets_values（selection_state 字段）→ 保存工作流即保存状态；发给朋友工作流，只要他装了本插件就能直接看效果（他的库内容不同的标签会优雅降级为文本原样输出，不报错）。
4. 默认库与用户库合并规则：按 category/subcategory/tag 的 `id` 匹配，同名取用户值；插件更新带来新分类/新标签会追加进来，你在用户库里删过的不会被复活（记 tombstone）。

## 五、用户视角使用故事（全流程）

1. 装好插件重启 ComfyUI。
2. 双击画布搜"标签库"拖出节点；CLIPTextEncode 的 text 右键 Convert to Input；连上线。
3. 点节点 ⚙ → 展开"标签库管理"大窗口（或浏览器输 /taglib）→ 挑几个分类补自己的常用词 → 💾保存 → 关窗口。
4. 回到节点小面板：展开"人物/表情"，点 smile、blush 两颗 chip → 已选区出现并可拖顺序。
5. 模式切"分类随机"，给光影类设 开/数量2/空抽20%，画风类设必含 masterpiece。
6. Queue！seed 自动换 → 每次输出不同组合的 tag 串，直接吃进 KSampler 出图。
7. 想锁定某次的结果：把 seed 抄下来即可复现（随机引擎 seed 决定论）。

## 六、其余部分（v1 已定，摘要保留）

- **节点签名**：required = selection_state(hidden)/mode/manual·random_by_category·random_mix/seed(randomize)；optional = prefix/suffix(forceInput 串接上游)、min_tags/max_tags、category_weights(hidden)、separator、use_weights_syntax((tag:1.2))、dedupe；返回 positive + tags_preview 两个 STRING。
- **随机引擎**：每分类 开关/数量N/空抽概率 三参数；组合随机支持关键词/中文/别名过滤 + category_weights 加权；pinned 钉选标签必含；同 seed 可复现。
- **目录结构**：__init__.py / nodes.py / library.py / api.py / data/(default+.user) / web/(taglibrary.js · tagpanel.css · manager.html · manager.css · manager.js) / pyproject.toml。
- **默认库**：六大分类起步——👤人物(体型/发型/表情/动作姿势/服装/配饰)、🖼背景场景(室内/室外/幻想)、💡光影效果(光源类型/氛围)、🎨画风质量(质量词/漫画特效线)、📷镜头、🔲构图。每类 20~60 条中英对照，预置你三条 LoRA 触发词组（masterpiece/best quality/very aesthetic；dispersion/subsurface scattering/dappled moonlight）。
- **前端选型**：原生 DOM widget，只用最稳定 API 面（registerExtension/beforeRegisterNodeDef/addDOMWidget/menuCommands），不碰废弃 scripts/ui。

## 七、里程碑（v2 调整 M4）

| 阶段 | 内容 | 验收 |
|---|---|---|
| M1 | Python 节点 + 默认库 + 三模式随机引擎 + API(/taglib/api/*) | 连 CLIPTextEncode 跑通出图 |
| M2 | 节点 domWidget 小面板（chips/已选/序列化） | 工作流保存重开状态恢复 |
| M3 | 每分类随机参数 + pinned + 权重语法 | 同 seed 复现 |
| M4 | **独立管理页 manager.html + /taglib 路由 + 双入口（顶栏按钮/⚙iframe）+ CRUD + 导入导出 + 显式保存** | 管理页改库 → 下次 Queue 生效 |
| M5 | 打磨：中文搜索、别名命中去重、玻璃拟态样式对齐审美 | 目测过审 |
| M6 | pyproject + Registry/Manager 收录 | Manager 可安装 |

## 八、坑位提醒

1. ComfyUI 前端升级频繁破坏扩展：锁稳定 API 面 + README 注明测试过的前端版本号。
2. domWidget 高度自适应：computeSize + setSize 要跟上，否则面板被裁。
3. selection_state 只存点选集与随机配置，绝不塞整库（库走 API 拉，防止老工作流携带过期库快照）。
4. manager.html 在 embed 模式要识别 ?embed=1 去掉外边距，融入弹窗。
5. 删除分类对旧工作流的兼容：state 里残留的已删 id → 输出时跳过并 console.warn，不炸图。
