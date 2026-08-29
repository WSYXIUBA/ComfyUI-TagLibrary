# 🏷 ComfyUI-TagLibrary

**中文** | [English](README_EN.md)

结构化提示词标签库节点：节点内点选面板 + 独立管理页 + 双模式随机引擎 + 反冲突系统 + 文件夹式存储（热同步）。
输出纯 `STRING`，用 Convert to Input 连上任何工作流的 `CLIPTextEncode.text` 就能用。单次生成 1-4ms。

![license](https://img.shields.io/badge/license-MIT-green) ![comfyui](https://img.shields.io/badge/ComfyUI-custom--node-blue) ![tests](https://img.shields.io/badge/tests-passing-brightgreen)

## 特性

- **节点内面板**：分类分组 chips、已选区拖拽排序、📌 钉选（随机时必含）、中/英双语显示、NSFW 开关
- **两种模式**
  - `手动` —— 点选 + 🎲 按子分类范围随机填充（每个子分类可独立设抽取数量）
  - `自动` —— 每次生成按规则随机组合，结果自动回显到面板（体验同种子随机化）
- **➕ 添加标签（5 页签挑选器）**：挑标签 / 排除类目 / 标签库管理 / 防冲突关系 / 设置
- **独立管理页**：浏览器直达 `http://127.0.0.1:8188/taglib` 或顶栏 🏷 按钮
  分类/子分类/标签全级 CRUD（右键改名/删除/排序）、chip 流布局、NSFW 红框标识、批量粘贴导入
- **NSFW 分级**：裸露/露骨类标签红色显示、开关控制隐藏与输出；其余标签不受影响
- **反冲突系统**：规则文件自由导入导出，支持 标签/二级分类/一级分类 任意组合的双向互斥；
  随机抽取时抽到一侧另一侧自动让位（手动点选不受影响）
- **文件夹式存储（热同步）**：标签库即文件夹结构，管理页与磁盘双向实时同步
- **AI 协作闭环**：导出模板（基础/全量）+ 反冲突文件，直接发给 AI 补充/重构，
  回传文件导入时自动归位、去重、预览确认
- **备份机制**：💾 存为默认库 / ↺ 恢复备份库 / 🗑 清空标签库（可选先导出全量模板）
- **性能**：节点执行 1-4ms；库文件读取带缓存，热同步扫描节流
- **seed 决定论**：同 seed 输出可复现；权重语法 `(tag:1.2)`、去重保序、prefix/suffix 串接

## 界面预览

| 节点面板（点选 / 分组填充 / NSFW 开关） | 添加标签挑选器（5 页签 / 分组 chips / 总控制） |
|---|---|
| ![节点面板](docs/screenshot_node_panel.png) | ![添加标签挑选器](docs/screenshot_tag_picker.png) |

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
3. 点节点上的 **➕ 添加标签**：挑标签 / 设排除类目 / 管理库 / 配反冲突 / 调设置
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
| `positive` 输出 | 拼好的提示词 → CLIPTextEncode |
| `tags_preview` 输出 | 实际内容预览 → Preview Text |

## 数据文件

| 文件/目录 | 说明 |
|---|---|
| `data/tag_library.json` | 出厂默认库（随插件更新） |
| `data/tag_library.user.json` | 用户库快照（管理页保存，含删除墓碑；升级永不丢失） |
| `data/taglib/` | **文件夹式标签库**（双向热同步，见下）；内含 `conflicts.json` 反冲突规则 |
| `data/tagfiles/` | 旧版标签文件目录（兼容扫描导入） |
| `data/备份库/` | 「💾 存为默认库」的备份位置 |

删除用户库 = 恢复出厂默认（清空标签库按钮同效）。

## 文件夹式标签库（双向热同步）

```
data/taglib/
├── conflicts.json        ← 反冲突规则文件
├── 质量与技术/            ← 一级分类 = 文件夹
│   ├── 画质强化/          ← 二级分类 = 子文件夹
│   │   └── 画质强化.md    ← # 大类 / ## 子类 标题 + 标签行
│   └── 真实感/
└── 人物主体/ ...
```

- **管理页改动 → 文件夹**：增删/改名分类，文件夹实时同步（保存即落盘）
- **文件夹 → 管理页**：手动在文件里加标签（`english(中文){权重}[nsfw]`，逗号分隔），保存文件后刷新网页即可见；无标题的 .md 按所在文件夹名自动归分类
- `标签文件` 对话框支持：树形浏览 / 逐个导入 / ⏩ 全部导入 / 📁 同步当前库到文件夹

## 反冲突系统

```jsonc
// data/taglib/conflicts.json
{ "rules": [
  { "id": "nude-vs-clothes",
    "left":  { "kind": "tags", "value": ["nude", "topless", "..."] },
    "right": [ { "kind": "sub", "value": "服装系统/上装" } ] }
]}
```

- **规则 = 双向互斥**：随机填充/自动模式抽到 left 一侧，right 一侧自动让位；手动点选不拦
- `kind` 支持：`tag` 单标签 / `tags` 多标签 / `sub` 二级分类 / `cat` 一级分类
- **三种配置方式**：① 标签/子分类/一级分类右键 → 🧷 反冲突设置（勾选树，保存即落盘）
  ② 挑选器「防冲突关系」页签查看全部规则、增删  ③ 导出文件丢给 AI 生成后导入
- **失效自动识别**：规则指向库中不存在的目标时标红提醒
- 内置默认规则：裸露/泳装 ↔ 服装上下装（配饰如项链不冲突）；写实向 ↔ 二次元向；旧互斥组自动迁移

## AI 协作闭环

「📤 导出模板」四选一：**基础模板**（骨架+示例，让 AI 生成新标签文件）、**全量模板**（全部标签，
可继续补充或重构一二级分类、或分享整库）、**仅反冲突文件**、**反冲突+全量模板（双文件）**。
双文件一起发给 AI → 按文件内说明生成 → 「📥 导入」预览（自动归位+去重+失效标记）→ 确认入库。

## 测试

```bash
python tests/smoke_test.py            # 后端引擎断言（沙箱，不碰真实数据）
python tests/conflicts_test.py        # 反冲突引擎
python tests/folder_template_test.py  # 文件夹导出/扫描/按名称合并/热同步往返
python tests/parser_conflict_test.py  # .md 解析器
```

## License

MIT
