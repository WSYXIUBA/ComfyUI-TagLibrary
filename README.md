# 🏷 ComfyUI-TagLibrary

**中文** | [English](README_EN.md)

结构化标签库节点：拼装轴 + 武器·物品档案束 + 资源预算冲突引擎 + 自然语言尾段。
13 条轴 / 73 个槽位 / 出厂 4458 词 + NSFW 扩展包 ~300 词 / 18 份武器·物品档案 / 55+ 组互斥域 / 36+4 族 NL 句式。
输出 `STRING`（标签主体 + 可选英文自然语言尾段 + Anima 推荐负向块），连上任何工作流的 `CLIPTextEncode.text` 就能用。单次生成 1-4ms。

![license](https://img.shields.io/badge/license-MIT-green) ![comfyui](https://img.shields.io/badge/ComfyUI-custom--node-blue) ![tests](https://img.shields.io/badge/tests-passing-brightgreen)

## 核心架构（四板斧）

- **拼装轴**：标签的真正骨架不是二级树——4458 词按 12 条轴（画质/人数/角色/外貌/服装/道具武器/动作/场景…）聚合，再按 Anima 官方 tag order 分成六个输出段位。挑选器是**单一视图**：段位 → 轴 → 槽位逐级展开，每行自带启用开关（关 = 写入排除类目，抽取时整条跳过）。
- **武器·物品档案（⚔ bundle）**：18 份档案（武士刀/剑/大剑/枪械/弓/法杖/长柄 + 手机/书/伞/吉他/杯子/相机等）自带姿势束：每条姿势=标签组+手数+视线+状态槽+排斥声明。**抽中武器必带持握姿势，姿势必随武器出生**——裸武器、双持单手刀、弓蹭枪姿势这类肢解在结构上不可能发生（万 seed 压测束出生率 100%）。
- **资源预算冲突模型**：同轴/同组互斥 + hands/gaze 资源账本 + 状态槽 + 50 个全局互斥域（🧬 可查可编辑）从结构上自动推导冲突；跨池规则保留在 `conflicts.json`。性别锁（1boy 不出女词）、嘴部域（一口不能两衔）全链路出口复核。
- **自然语言尾段（✍ NL）**：标签主体之后追加 1-4 句英文描写，由句式族查表编译（人称回指、句式轮换、叙事顺序三律防拼接感），热路径零 LLM、seed 决定论可复现，面板 ⚙ 可关；NSFW 场景可加载独立句式包（`nsfw_nl.json`，用户自填内容）

## 出词效率套件（v1.8.0 / 1.8.1）

- **🎛 场景条（面板常亮三开关）**：👤 单人锁（人数轴只出单词、禁多人互动槽）/ 🖼 简洁背景（禁具象场景·天气·粒子，背景处理只出纯色·渐变·虚化·棚拍族）/ 🎯 人物特写（禁杂物道具槽，取景只出 portrait·upper body 特写族）——状态存进工作流，引擎权威生效
- **🔞 NSFW 强度**：标题栏常驻按钮（标准/强调/纯欲），不再藏在 ⋯ 菜单里
- **📦 预设管理**：⋯ 菜单打开完整界面——出厂 13 个（含背景预设族：纯白棚拍/纯黑/渐变/虚化外景/卧室/教室/自然/街头/天台/沙滩）+ 我的预设（NSFW 场景 7 个已预置：纯欲特写/浴室/温泉/卧室/束缚/女女/群像），支持详情/JSON 编辑/删除

- **📦 场景预设**：钉选词 + 排除域 + 随机配置存为命名预设（角色卡/场景包/局面三类），下拉一键载入——预设是约束不是锁死，🎲 继续在预设框内随机；出厂自带 SFW 示例，💾 存为「我的」预设、🗑 删除
- **🎲 分轴重摇**：填充分组标题上自带 🎲，只重摇该轴的词，其余轴全部保留——「重摇→钉住满意的→再摇下一轴」的高效循环
- **🔞 NSFW 强度三档**：⋯ 菜单切换 标准/强调/纯欲（涩词抽样权重 ×1/×2.5/×6 + 纯欲档 NSFW 槽位配额加成与削减豁免），实测每条 NSFW 词数 3.8 → 9.9
- **🎲 批量探索**：⋯ 菜单一次生成 8~30 条完整 prompt 网格，点卡片把节点 seed 对齐（同引擎同确定性，queue 即复现），📋 复制单条
- **📥 Prompt 吸收器**：粘贴任意来源提示词 → 库内词（en/别名/权重语法/下划线归一）直接进面板，库外新词选槽位归位入库
- **🧰 管理页批量工具**：正则重命名 / 批量移动 / NSFW 批量标记 / 跨槽位查重
- **negative 输出**：节点第三输出口内置 Anima 官方推荐负向块 + 常用缺陷词，直连负向 CLIPTextEncode

## NSFW 扩展包（不入发布包）

NSFW 词表体系以扩展包形式分发（`tag_library.ext.json` / `nsfw_grouprules.json` / `nsfw_conflicts.json` / `nsfw_nl.json`，均 gitignore）——**发布包内不含任何露骨词**，Registry 合规：

- 新增 5 个 NSFW 槽位：`服装/服装状态`（半脱机制）/ `动作姿态/体位` / `动作姿态/性行为` / `动作姿态/束缚与调教` / `动作姿态/高潮与体液` + `道具武器/束缚道具`、`外貌特征/身体细节`
- 词源经 danbooru post_count 校验（≥1500 posts 才收录），高频词自动加权
- 约束全链路：体位与站/坐/躺同组互斥、口部域一把锁、词级双手账本（乳交=2手）、动物伙伴与性行为槽结构性隔离、未成年年龄词在场时全池屏蔽成人向词
- 生成工具：`tools/build_ext_pack.py`（策展词表 + post_count 校验 → 幂等重建）
- 低频词审计：`tools/danbooru_audit.py`（--verify 25 抽样线上校准，报告出「自造词/低频词/高频覆盖率」，实测出厂词表 ~55% 不在 danbooru 高频 35k 词表内）

## 特性

- **节点内面板**：已选区拖拽排序、📌 钉选、中/英双语显示、NSFW 开关、性别过滤（⚥/♀/♂ 三态）；🎲 填充走服务端 `/taglib/api/draw`，与节点执行同一引擎——所见即所得
- **两种模式**
  - `手动` —— 点选 + 🎲 按当前设置随机填充
  - `自动` —— 每次生成按规则随机组合，结果自动回显到面板（回显只替换引擎抽取的部分，手动挑选的标签永久保留）
- **➕ 添加标签（5 页签挑选器）**：挑标签 / ⚔ 武器档案 / 🧬 互斥域（含跨池规则）/ ✍ NL 句式 / ⚙ 设置；排除类目在侧栏折叠抽屉里，轴/槽位/孙分类三级粒度
- **画师轴（🎨）**：留空 + 默认关闭——画师是"选定"而不是"随机"的维度，要就自己填名字或勾上侧栏开关；库里存裸名，输出自动补 Anima 要求的 `@` 前缀
- **档案可视化**：每份档案卡片=身份词、全部姿势（标签/吃几只手/状态槽/排斥词）表格、挂载诊断徽章（哪些武器词没挂上直接标红），全部字段行内可编辑，JSON 编辑保存即生效
- **独立管理页**：浏览器直达 `http://127.0.0.1:8188/taglib` 或顶栏 🏷 按钮；分类/子分类/标签全级 CRUD、图标自定义、chip 流、批量粘贴导入、全文搜索
- **NSFW 分级**：裸露/露骨类标签红色显示、开关控制隐藏与输出
- **库文件即数据（.json）**：整库就 `tag_library.json` + `tag_library.user.json` 两个文件（外加 `taglib/*.json` 规则文件），没有镜像目录、没有 .md 中间层；管理页「📤 导出整库 / 📤 导出我的 / 📥 导入 .json」直接进出原文件，文件里带 `_说明` 写清格式与规则（JSON 无注释，用保留键）
- **备份机制**：💾 存为默认库 / ↺ 恢复备份库 / 🗑 清空标签库（清空前可顺手导出整库 .json）
- **钉选语义**：📌 钉选标签随机/填充/生成回显必含且不被覆盖；钉选武器同样带束出生
- **出图元数据**：PNG 信息自动写入 `TagLibrary` 键（节点/模式/种子/实际出词），同 seed 可复现
- **翻译扩展免疫**：面板/挑选器/管理页标签英文永不被翻译插件改写
- **API 安全**：写接口带 CSRF 防护（跨站 Origin 拒绝），整库导出到外部目录需管理页显式确认
- **性能**：节点执行 1-4ms；10k 标签库 snapshot 构建内 p50 <3ms；手动模式 en/id 查表按库缓存
- **seed 决定论**：同 seed 输出可复现；权重语法 `(tag:1.2)`、去重保序、prefix/suffix 串接

## 界面预览

| 挑选器单一视图（段位序 → 轴 → 槽位，⚔ 束词标记） | 武器·物品档案（姿势表 / 挂载诊断 / 行内编辑） |
|---|---|
| ![轴视图](docs/screenshot_axis_view.png) | ![档案](docs/screenshot_profiles.png) |

| 节点面板（点选 / 🎲 填充 / NSFW 开关） | 标签库管理页（分类 CRUD / 导入导出 / 备份） |
|---|---|
| ![节点面板](docs/screenshot_node_panel.png) | ![标签库管理页](docs/screenshot_manager.png) |

## 安装

### 方式一：ComfyUI Manager 搜索安装（推荐）

1. 点击顶栏 Manager（管理器）图标 → **Custom Nodes Manager**（自定义节点管理）
2. 搜索 **`Tag Library`**（或 `taglibrary`）→ 找到「🏷 Tag Library 标签库」→ **Install**
3. 完成后按提示重启 ComfyUI

> 搜不到时先在 Manager 里更新一下节点数据库缓存（或重启 ComfyUI 后再搜）。

### 方式二：Git URL 安装

Manager → **Install via Git URL** → 粘贴：
```
https://github.com/WSYXIUBA/ComfyUI-TagLibrary
```

### 方式三：Git clone

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/WSYXIUBA/ComfyUI-TagLibrary
```

重启 ComfyUI。无任何 pip 依赖。

## 快速上手

1. 双击画布搜「🏷 标签库」添加节点
2. `CLIPTextEncode` 的 text 右键 → **Convert to Input** → 连接标签库的 `positive`
3. 点节点上的 **➕ 添加标签**：挑标签 / 看档案 / 配互斥 / 调设置
4. `手动` 模式点选或 🎲 填充；`自动` 模式直接 Queue，每次自动换组合
5. `tags_preview` 可接 Preview Text 查看实际输出

```
[🏷 标签库] ──positive──▶ [CLIPTextEncode.text (converted)] ──▶ ...
     └─ tags_preview ──▶ [Preview Text]
```

## 节点接口

| 输入/输出 | 说明 |
|---|---|
| `mode` | 手动 / 自动 |
| `seed` | 随机种子，同 seed 同结果 |
| `selection_state` | 面板状态（自动维护，勿手改） |
| `prefix` / `suffix`（可选输入） | 上游文本拼在标签前后 |
| `positive` 输出 | 标签 + NL 尾段 → CLIPTextEncode |
| `tags_preview` 输出 | 实际内容预览 → Preview Text |

## 数据文件

| 文件/目录 | 说明 |
|---|---|
| `data/default/tag_library.json` | 出厂默认库（随插件更新） |
| `data/default/tag_library.user.json` | 用户库快照（管理页保存；升级永不丢失） |
| `data/default/taglib/` | 规则文件目录（**只有 .json**：互斥域 / 分组域 / NL 风味 / 档案 / 出厂预设） |
| `data/default/taglib/profiles.json` | 武器·物品档案（姿势束/手视资源/状态槽/NL 声明真源） |
| `data/default/taglib/grouprules.json` | 全局互斥域（50 组） |
| `data/default/taglib/nl_flavors.json` | NL 句式素材（36 族 + pose_map + 宾语词池） |
| `data/default/taglib/conflicts.json` | 跨池反冲突规则（兼容保留） |
| `data/default/backups/` | 备份位置（`user_backup.json` 手动「存为默认库」；`user_auto.json` 每次保存自动滚动；`factory_backup.json` 出厂） |

## 反冲突模型

冲突不靠手工规则表穷举，按来源自动推导：

| 机制 | 例子 | 真源 |
|---|---|---|
| 同轴/同组单选 | 抽了 `smile` 不再抽 `grin` | 库内 `axis`/`groups` |
| 全局互斥域 | 嘴部域：`cigarette in mouth` ↔ `food in mouth` 一口不能两衔 | `grouprules.json` |
| 资源预算 | `hands` 总数 ≤2、`gaze` ≤1 —— 双手捧杯 + 撑伞结构性不可能 | `profiles.json` |
| 状态槽 | 同一武器不能既 `drawn` 又 `sheathed` | `profiles.json` |
| 跨池规则 | 写实摄影 ↔ 二次元向 | `conflicts.json` |
| 性别锁 | `1boy` 在场，`1girl/milf/witch` 等女词池级+出口级双拦 | 库内性别标记 |

## 测试

一键跑全部门禁（**推荐**，会自动快照并还原 `data/default/taglib/`，不会污染工作区）：

```bash
python tools/run_gates.py               # 14 项离线门禁
python tools/run_gates.py --with-online # 加上需要 ComfyUI 实例的在线门禁
python tools/run_gates.py --list        # 列出所有门禁
python tools/run_gates.py m1 m3         # 只跑名字匹配的
```

离线门禁（15 项）：

| 脚本 | 覆盖 |
|---|---|
| `tests/m1_engine_test.py` | 引擎骨架（轴/组/跨池/确定性） |
| `tests/m2_weapon_slice_test.py` | 武器束 + 旧 repro 缺陷翻案 |
| `tests/m3_nl_test.py` | NL 编译 + 反拼接断言 |
| `tests/m4_objects_test.py` | 物品档案（`--long` 万 seed 长跑） |
| `tests/quality_audit.py` | 30 条完整提示词人工级审计 |
| `tests/smoke_test.py` | 后端全链路（沙箱） |
| `tests/conflicts_test.py` | 反冲突引擎 |
| `tests/perf_build_test.py` | 性能门禁 |
| `tests/quality_gate_test.py` | 输出质量门禁（词数/配额/互斥/人数/畸形词/段位/NSFW 往返） |
| `tests/prompt_quality_test.py` | 完整提示词重度测试（文本层语义/段位/性别/负向词） |
| `tests/api_security_test.py` | API 安全门禁（CSRF 中间件 / 导入 .json 载荷防呆） |
| `tests/lint_check.py` | 死代码门禁（ruff F401/F811/F841） |
| `tests/nsfw_pack_test.py` | NSFW 扩展包门禁 |
| `tests/heavy_prompt_test.py` | 重度提示词矩阵（708 条 × 模式/NSFW档/性别/场景/排除 + 3000 次压力） |

需先启动 ComfyUI（在线组 6 项，`ui_*` 走 huashu-chrome 桥）：

| 脚本 | 覆盖 |
|---|---|
| `tests/real_http_test.py` | 真机 HTTP queue 验收（接口/端口/性别锁 + CSRF 防护） |
| `tests/node_output_test.py` | 真机节点输出测试（60 次生成 × 文本层断言） |
| `tests/ui_v13_check.py` | 浏览器 UI 巡检（逐 tab 截图 + 断言 + 默认模式设置生效） |
| `tests/ui_theme_check.py` | 主题一致性巡检（深色 / 浅色 / 管理页） |
| `tests/ui_dialog_close_test.py` | 弹层开关巡检（⋯菜单/挑选器/面板弹层/管理页弹窗） |
| `tests/feature_e2e_test.py` | 全功能真机端到端（预设/场景条/强度/重摇/批量/吸收/未成年锁/negative） |

> CI 见 `.github/workflows/gates.yml`（只跑离线门禁）。

## 更新记录

完整版本变更史见 [CHANGELOG.md](CHANGELOG.md)。当前版本 **v1.12.3**。

## License

MIT
