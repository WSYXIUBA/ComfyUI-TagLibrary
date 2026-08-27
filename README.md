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

| 文件 | 说明 |
|---|---|
| `data/tag_library.json` | 默认库（随插件更新） |
| `data/tag_library.user.json` | 用户库（管理页保存的内容，含删除墓碑） |

删除用户库即恢复出厂默认。

## 测试

```bash
python tests/smoke_test.py   # 后端引擎 28 项断言, 无需启动 ComfyUI
```

## License

MIT
