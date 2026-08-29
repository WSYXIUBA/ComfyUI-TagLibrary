# 🏷 ComfyUI-TagLibrary

结构化标签库节点：多分类提示词标签仓库 + 独立管理页 + 节点内点选面板 + 三模式随机组合。
输出纯 `STRING`，用 Convert to Input 连上任何工作流的 `CLIPTextEncode.text` 就能用。

![license](https://img.shields.io/badge/license-MIT-green) ![comfyui](https://img.shields.io/badge/ComfyUI-custom--node-blue)

## 特性

- **节点内面板**：分类 chips 点选、已选区拖拽排序、📌 钉选（随机时必含）、搜索中/英/别名
- **三种模式**
  - `manual` 手动点选 —— 选什么输出什么
  - `random_by_category` 按类随机 —— 每个分类可设 启用 / 抽取数量 / 空抽概率
  - `random_mix` 组合随机 —— 全库加权抽取 min~max 个，`search_text` 过滤
- **独立管理页**：浏览器直达 `http://127.0.0.1:8188/taglib`（或节点 ⚙ 按钮）
  分类/子分类/标签三级 CRUD、批量粘贴导入 (`english | 中文 | 权重`)、导入导出 JSON、恢复默认库
- **数据分两层**：`tag_library.json` 默认库随插件更新；你的修改全部落在 `tag_library.user.json`，升级永不丢失
- **seed 决定论**：同 seed 输出可复现，节点 seed 支持 `control_after_generate` 自动变化
- 权重语法 `(tag:1.2)` 开关、去重保序、prefix/suffix 串接上游 prompt

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/WSYXIUBA/ComfyUI-TagLibrary
```

重启 ComfyUI。无任何 pip 依赖。

## 使用

1. 双击画布搜「🏷 标签库」添加节点
2. 在 `CLIPTextEncode` 节点的 text 上右键 → **Convert to Input** → 连接 标签库的 `positive`
3. （可选）浏览器打开管理页补充自己的常用词 → 💾保存
4. Queue 即出串；`tags_preview` 可接 Preview Text 查看实际内容

```
[🏷 标签库] ──positive──▶ [CLIPTextEncode.text (converted)] ──▶ ...
     └─ tags_preview ──▶ [Preview Text]
```

## 数据文件

| 文件/目录 | 说明 |
|---|---|
| `data/tag_library.json` | 默认库（随插件更新） |
| `data/tag_library.user.json` | 用户库（管理页保存的内容，含删除墓碑） |
| `data/taglib/` | **文件夹式标签库**：`一级分类/二级分类/xx.md`，与管理页分类一一对应；内含 `conflicts.json` 反冲突规则 |
| `data/tagfiles/` | 旧内置标签文件目录（兼容扫描） |

删除用户库即恢复出厂默认。

## 文件夹式标签库 & AI 模板

```
data/taglib/
├── conflicts.json     ← 反冲突规则 (可导出给 AI 生成后导回)
├── 质量与技术/
│   ├── 画质强化/
│   │   └── 画质强化.md     ← # 大类 / ## 子类 标题 + 标签行
│   └── 真实感/
└── 人物主体/
    └── ...
```

- 管理页「📂 标签文件」→ **📁 同步当前库到文件夹**：把库镜像导出成上面的结构，文件管理器里一眼找到标签
- 文件夹里新建/修改 .md 后回管理页可逐个导入或 **⏩ 全部导入**（自动去重、按文件夹归类）
- 无标题的 .md 按所在文件夹名自动归分类；`_` 开头文件跳过
- **🤖 AI模板**：按当前分类结构实时生成 .md 模板（内嵌使用说明 + 每类 ≤5 个示例标签），
  直接发给 AI 补充，回传的文件从「标签文件」上传即自动归位去重
- 文件格式：`# 大类` / `## 子分类` 两级标题，标签语法 `english(中文翻译){权重}[nsfw]`，逗号分隔

## 测试

```bash
python tests/smoke_test.py            # 后端引擎断言, 无需启动 ComfyUI
python tests/folder_template_test.py  # 文件夹导出/扫描/按名称合并
```

## License

MIT
