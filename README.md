# 🏷 ComfyUI-TagLibrary

**中文** | [English](README_EN.md)

1.3.0 底层重构：拼装轴 + 词条档案 + 资源预算引擎 + 自然语言尾段。9 大类 / 65 子分类 / 4300+ 标签 / 18 份武器·物品档案 / 34 组句式族。
输出 `STRING`（标签主体 + 可选英文自然语言尾段），连上任何工作流的 `CLIPTextEncode.text` 就能用。单次生成 1-4ms。

![license](https://img.shields.io/badge/license-MIT-green) ![comfyui](https://img.shields.io/badge/ComfyUI-custom--node-blue) ![tests](https://img.shields.io/badge/tests-passing-brightgreen)

## 1.3.0 新架构（四板斧）

- **拼装轴**：标签的真正骨架不再是二级树——4356 词按 12 条轴（画质/人数/角色/外貌/服装/道具武器/动作/场景…）聚合。树降级为浏览皮肤，挑标签面板可切换「🌲 分类树 / 🎯 拼装轴」两种视图，每个词悬停显示轴+树双出处。
- **武器·物品档案（⚔ bundle）**：武器姿势不再挂全局池。7 份武器档案（武士刀/剑/大剑/枪械/弓/法杖/长柄）+ 11 份日常物品档案（手机/书/伞/吉他/杯子/相机/麦克风/花/望远镜/点心/笔）自带姿势束：每条姿势=标签组+手数+视线+状态槽+排斥声明。**抽中武器必带持握姿势，姿势必随武器出生**——裸武器、双持单手刀、弓蹭枪姿势这类肢解在结构上不可能发生（万 seed 压测束出生率 100%）。
- **资源预算冲突模型**：旧版 81 条手写反冲突规则退役大半——同轴/同组互斥 + hands/gaze 资源账本 + 状态槽 + 50 个全局互斥域（🧬 可查可编辑）从结构上自动推导冲突；旧 `conflicts.json` 只保留跨池规则。性别锁（1boy 不出女词）、嘴部域（一口不能两衔）全链路出口复核。
- **自然语言尾段（✍ NL）**：标签主体之后追加 1-3 句英文描写，由 34 组句式族查表编译（人称回指、句式轮换、叙事顺序三律防拼接感），热路径零 LLM、seed 决定论可复现，面板 🎚 可关。

## 特性

- **节点内面板**：分类分组 chips、已选区拖拽排序、📌 钉选、中/英双语显示、NSFW 开关、🗑 一键清空；🎲 填充与预览/实出走同一引擎，所见即所得
- **两种模式**
  - `手动` —— 点选 + 🎲 按子分类范围随机填充
  - `自动` —— 每次生成按规则随机组合，结果自动回显到面板（回显只替换引擎抽取的部分，手动挑选的标签永久保留）
- **➕ 添加标签（8 页签挑选器）**：挑标签（轴/树双视图）/ ⚔ 武器档案 / 🧬 互斥域 / ✍ NL 句式 / 排除类目 / 标签库管理 / 防冲突关系 / 设置；三个新页全量中英双语渲染，「文A」一键切换纯英
- **档案可视化**：每份档案卡片=身份词、全部姿势（标签/吃几只手/状态槽/排斥词）表格、挂载诊断徽章（哪些武器词没挂上直接标红），JSON 编辑保存即生效
- **独立管理页**：浏览器直达 `http://127.0.0.1:8188/taglib` 或顶栏 🏷 按钮；分类/子分类/标签全级 CRUD、图标自定义、chip 流、批量粘贴导入
- **NSFW 分级**：裸露/露骨类标签红色显示、开关控制隐藏与输出
- **文件夹式存储（热同步）**：标签库即文件夹结构，管理页与磁盘双向实时同步
- **AI 协作闭环**：导出模板（基础/全量/反冲突）→ AI 补充/重构 → 导入自动归位、去重、预览确认
- **备份机制**：💾 存为默认库 / ↺ 恢复备份库 / 🗑 清空标签库
- **钉选语义**：📌 钉选标签随机/填充/生成回显必含且不被覆盖；钉选武器同样带束出生
- **出图元数据**：PNG 信息自动写入 `TagLibrary` 键（节点/模式/种子/实际出词），同 seed 可复现
- **翻译扩展免疫**：面板/挑选器/管理页标签英文永不被翻译插件改写
- **性能**：节点执行 1-4ms；10k 标签库 build p50 1.1ms；3300 次档案抽取 13.6s
- **seed 决定论**：同 seed 输出可复现；权重语法 `(tag:1.2)`、去重保序、prefix/suffix 串接

## 界面预览

| 1.3.0 拼装轴视图（⚔ 束词标记 / 轴树双视图） | 1.3.0 武器·物品档案（姿势表 / 挂载诊断） |
|---|---|
| ![轴视图](docs/screenshot_axis_view.png) | ![档案](docs/screenshot_profiles.png) |

| 节点面板（点选 / 分组填充 / NSFW 开关） | 标签库管理页（分类 CRUD / 导入导出 / 备份） |
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
| `data/default/taglib/` | 文件夹式标签库（双向热同步） |
| `data/default/taglib/profiles.json` | **1.3.0 武器·物品档案**（姿势束/手视资源/状态槽/NL 声明真源） |
| `data/default/taglib/grouprules.json` | **1.3.0 全局互斥域**（50 组，取代手写规则的主真源） |
| `data/default/taglib/nl_flavors.json` | **1.3.0 NL 句式素材**（34 族 + pose_map + 宾语词池） |
| `data/default/taglib/conflicts.json` | 跨池反冲突规则（兼容保留） |
| `data/default/backups/` | 备份位置 |

## 反冲突模型（1.3.0）

冲突不再靠手工规则表穷举，按来源自动推导：

| 机制 | 例子 | 真源 |
|---|---|---|
| 同轴/同组单选 | 抽了 `smile` 不再抽 `grin` | 库内 `axis`/`groups` |
| 全局互斥域 | 嘴部域：`cigarette in mouth` ↔ `food in mouth` 一口不能两衔 | `grouprules.json` |
| 资源预算 | `hands` 总数 ≤2、`gaze` ≤1 —— 双手捧杯 + 撑伞结构性不可能 | `profiles.json` |
| 状态槽 | 同一武器不能既 `drawn` 又 `sheathed` | `profiles.json` |
| 跨池规则 | 写实摄影 ↔ 二次元向 | `conflicts.json` |
| 性别锁 | `1boy` 在场，`1girl/milf/witch` 等女词池级+出口级双拦 | 库内性别标记 |

旧 81 条手写规则中同域互斥已自动迁移为组；跨池规则保留原语义。

## 测试

```bash
python tests/m1_engine_test.py        # 新引擎骨架（轴/组/跨池/确定性）
python tests/m2_weapon_slice_test.py  # 武器束 + 旧 repro 缺陷翻案
python tests/m3_nl_test.py            # NL 编译 + 反拼接断言
python tests/m4_objects_test.py       # 物品档案 + 万 seed 长跑 (--long)
python tests/quality_audit.py         # 30 条完整提示词人工级审计
python tests/smoke_test.py            # 后端全链路（沙箱）
python tests/conflicts_test.py        # 反冲突引擎
python tests/folder_template_test.py  # 文件夹热同步
python tests/parser_conflict_test.py  # .md 解析器
python tests/perf_build_test.py       # 性能门禁 (10k 库 p50<3ms)
python tests/real_http_test.py        # 真机 ComfyUI HTTP queue 验收
python tests/ui_v13_check.py          # CDP 浏览器 UI 巡检 (截图+断言)
```

## 更新记录

完整版本变更史见 [CHANGELOG.md](CHANGELOG.md)。当前版本 **v1.3.0**（拼装轴 + 武器·物品档案 + 资源预算冲突 + NL 尾段底层重构）。

## License

MIT
