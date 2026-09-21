# 代码审查与架构优化方案

> 日期：2026-09-19
> 范围：ComfyUI-TagLibrary 全仓（Python 5360 行 / 前端 6865 行）
> 结论摘要：本次已清除调试残留与 53 处死导入、合并 1 处双路重复实现，20/20 门禁全绿。
> 结构性问题上，**1 项需要改架构（P0）**，其余为渐进拆分，不建议推倒重来。

---

## 0. 本次已执行的清理

| 项 | 位置 | 内容 |
|---|---|---|
| 全局 GC 监控 | `nodes.py` | 往 `gc.callbacks` 注册进程级回调，GC 暂停 >200ms 就打日志。属进程级探针，与插件功能无关，且对每个 ComfyUI 用户永久生效 |
| 计时插桩 | `nodes.py` `build()`、`library.py` `get_merged()` | 热路径上包一层 `perf_counter` + 超标打印，删除后语义不变 |
| 前端版本横幅 | `web/taglibrary.js` | `window.__taglibVersion` + 每次加载的 `console.log` |
| 死导入 53 处 | `api/*.py`、`nodes.py` | 见 §0.1 |
| 双路重复实现 | `nodes.py` | `_build_auto` 与 `_build_impl` 各自复制了一份「去重 + 分隔符 + 前后缀拼接」，抽为 `_join_output()` |

### 0.1 死导入的成因（值得记一笔）

四个路由模块（`conflicts_routes` / `library_routes` / `tagfiles_routes` / `v13_routes`）的导入头
是互相复制粘贴的，包含：

```python
from .. import library, tagfiles, tagconflicts, runtime_snapshot
from .. import profiles as _profiles, grouprules as _grouprules, nl as _nl
from .. import engine as _engine
from ._common import (_WEB_DIR, BACKUP_DIR, FACTORY_BACKUP_PATH, USER_BACKUP_PATH,
                      UPGRADE_PROMPT_PATH, LEGACY_BACKUP_PATH, _json_response, _mirror_folder)
```

其中 `conflicts_routes.py` 实际只用到 `json / web / library / tagconflicts / _json_response` 五个，
其余 **15 个全部未使用**；`tagfiles_routes.py` 13 个、`v13_routes.py` 10 个、`library_routes.py` 7 个。
对比之下 `v18_routes.py`（后写的）只导入自己用到的，是正确的形态 —— 说明这是**历史漂移**而非有意设计。

保留的 `api/__init__.py` 中 `_json_response` 是**有意的对外 re-export**（原文件已标 `# noqa: F401`），未动。

### 0.2 验证

```
tools/run_gates.py --with-online  →  20 通过 / 0 失败
```

含 `real_http_test`、`node_output_test`（60 次生成文本层断言）、`ui_v13_check`、
`ui_theme_check`（CDP 浏览器）、`feature_e2e_test` 全绿。`data/` 已按门禁机制还原。

---

## 1. 现状体检

### 1.1 规模

| 层 | 文件 | 行数 |
|---|---|---|
| 数据 | `library.py` / `tagfiles.py` / `schema.py` | 621 / 788 / 201 |
| 快照 | `runtime_snapshot.py` | 496 |
| 引擎 | `engine.py` / `axes.py` / `slotpolicy.py` / `tagconflicts.py` / `nl.py` / `profiles.py` / `grouprules.py` | 758 / 294 / 359 / 395 / 314 / 192 / 102 |
| 节点 | `nodes.py` | 396 |
| 路由 | `api/`（7 个模块） | 1394 |
| 前端 | `web/`（3 js + 1 css + 1 html） | 6865 |

数据规模：出厂库 13 轴 / 66 槽位 / 4458 标签；20 项门禁 + 52 个归档脚本。

### 1.2 写得好的地方（不要在重构中破坏）

- **热路径零 I/O**：`runtime_snapshot` 把冷路径编译成只读快照，`engine` 只在快照上跑。
  实测 `perf_build_test` 门禁锁住 p50 < 3ms，这是全仓最值钱的设计。
- **输出次第与抽取次序分离**（`axes.output_order` vs `pool_order`），语义正确且有注释说明为什么不能动。
- **落盘已是原子写**：`tmp + os.replace` 在 9 处写入点统一使用，没有"写一半损坏库"的风险。
- **规则真源外置**（`taglib/grouprules.json` 等）解决了 `.md` 热同步重建 dict 会抹掉标签附加字段的问题。

---

## 2. P0 — 需要改架构

### 2.1 读路径会写盘

**这是本次审查发现的唯一一处架构级缺陷，且有现场证据。**

链路：

```
GET /taglib/api/panel-index          ← 纯查询
GET /taglib/api/library              ← 纯查询
        └─ library.get_merged()
              └─ _folder_hot_sync()          ← 读接口里
                    ├─ sync_to_folder_snapshot()   → 写 data/taglib/**/*.md + _sync_state.json
                    └─ save_user_library()          → 写 tag_library.user.json
```

**证据**：工作区里 `data/default/taglib/_sync_state.json` 长期处于"已修改"状态。
diff 显示 `fingerprint`（全部 66 个 .md 的 mtime+size）**完全没变**，
唯一变化是 `lib_key` 里的用户库 mtime（`1789324769.89` → `1789325086.37`）。
即：**没人编辑任何标签，只是一次读接口调用，就把这个文件重写了。**

**后果**（按严重度排序）：

1. **只读语义被破坏**：`panel-index` / `library` 是 GET，却产生副作用。任何带鉴权/缓存的中间层、
   或把库目录放在备份快照/网络盘上的部署都会出问题。
2. **并发写**：aiohttp 多请求并发时，两个热同步可能交错 —— `_sync_busy` 标志是模块级单例，
   只防同一进程重入，且 `_last_hot_sync` 在 `finally` 里更新时间戳，会让后续请求"以为刚同步过"。
3. **git 噪声**：每次打开面板都让仓库变脏，掩盖真实改动。
4. **性能耦合**：`get_merged()` 的耗时 = 读库耗时 + 热同步耗时，两者被混在一起。

**建议方案（分两步走，第一步就能拿到大部分收益）**

- **第一步（低风险，建议先做）**：把热同步从 `get_merged()` 移到**显式触发点**。
  保留 `_folder_hot_sync()` 函数本身，但调用点改为：
  - 管理页的显式入口（用户主动改文件夹后的"同步"按钮 / 页面进入时）；
  - `save_*` 系列写接口之后（写完之后再镜像，顺序天然正确）；
  - 节点执行前的 `build()` 冷路径（已有节流，且本来就是写权限上下文）。

  `get_merged()` 退化为**纯读**：只做 `deep_merge` + `migrate_library` + 缓存
  （即 §2.1 里 `with _lock:` 之后那段，本来就是对的）。这一步改动量小，
  已存在的 `folder_template_test` / `smoke_test` 足以验证。

- **第二步（可选）**：把热同步改成 **mtime 指纹驱动的惰性检查**——
  只有在 `/taglib/api/tagfiles` 被访问、或文件夹指纹确实变化时才真正落盘，
  并给 `_sync_busy` 加一个真正的互斥（`threading.Lock` 或 aiohttp 层的任务去重），
  而不是靠时间戳节流近似。

**不建议**：直接把热同步整个删掉。它是"文件夹词库"这个核心卖点，只是不该挂在读路径上。

### 2.2 `.md` 镜像往返产生畸形标签（已知缺陷，未修）

`tagfiles._clean()` 用 NFKC 归一会把全角括号变成 ASCII 括号，而 `_TAG_RE` 的 zh 分组
只允许**一层**括号，于是中文名含括号的标签在"库 → .md → 库"往返后变成畸形词。
合并库当前有 6 个（如 `1other(单人(其他))`、`oil painting (medium)(油画(媒介))`）。

**为什么归到 P0**：它是**数据损坏**，不是显示问题。畸形词已经写进 `tag_library.json`，
会跟着发布包分发。修法有两条路，需要先定标：

- **A（推荐）**：zh 侧改用「最后一段括号对」而非「首个括号」做解析，并让 `_clean()`
  保留全角括号不归一（只在 en 侧归一）。需评估对现有 66 个 .md 的兼容性。
- **B（保守）**：解析失败时**拒绝写入镜像**并记日志，宁可不同步也不污染库。

无论选哪条，都需要先写一个"往返幂等"门禁：对全部 66 个槽位做 `lib → md → lib` 双向往返，
断言标签集合与 en 键完全不变。**这个门禁比修法本身更重要**。

---

## 3. P1 — 渐进拆分（不改行为）

### 3.1 原子写抽公共工具

`tmp + json.dump(ensure_ascii=False, indent=1) + os.replace` 这段在 9 处重复：
`library.py`、`api/library_routes.py`（×3）、`api/v13_routes.py`、`profiles.py`、
`grouprules.py`、`tagconflicts.py`、`tagfiles.py`（×3）。

**做法**：新建 `jsonio.py`，导出 `atomic_write_json(path, data, *, indent=1)`，
九处全部替换。收益不是省行数，而是：
① 缩进/编码策略只有一个真源（现在改格式要改 9 处）；
② 未来加 fsync、加写前备份、加 schema 校验只改一个地方。

**风险**：低。`tagmeta_roundtrip_test` / `folder_template_test` / `conflicts_test` 直接覆盖。

### 3.2 `api/_common.py` 去掉业务依赖

`_common.py` 原本 import 了 8 个业务模块（`tagconflicts`/`runtime_snapshot`/`profiles`/…），
但它们**一个都没用到** —— 这是"路由公共层"在演化中变成了隐性 re-export 中心。
本次已删除。建议同时确立约束：

> `_common.py` 只允许放**常量**与**无业务依赖的工具**（路径、响应封装、中间件），
> 不再 import 任何业务模块。

否则一旦有人从这里删东西，会在完全无关的路由模块里炸出 `ImportError`，
且报错位置与真实原因不符。可以加一条门禁断言 `_common` 的导入白名单。

### 3.3 加 lint 门禁，固化"导入不漂移"

本次 53 个死导入全是"复制粘贴后忘了删"造成的，靠人眼审查成本高。
建议在 `tools/run_gates.py` 里加一条 `lint` 门禁，跑 `pyflakes`（或 ruff 的 F401/F811/F841）。
注意：需在门禁里显式放行 `api/__init__.py` 的对外 re-export（加 `# noqa: F401` 即可）。

**这是投入产出比最高的一条**：一旦上闸，§0.1 这类问题不会再出现。

### 3.4 两个超大模块

- **`tagfiles.py`（788 行，25 个函数）**：混了四件事 ——
  ① `.md` **解析**（`parse_tagfile` / `_clean` / `apply_implied_headings`）
  ② **镜像写出**（`_desired_files` / `sync_to_folder` / `export_to_folder`）
  ③ **清单与同步状态**（`_scan_fingerprint` / `_load_sync_state` / `folder_sync_plan` / `mark_synced`）
  ④ **编辑层 sidecar**（`_tag_meta_of` / `_write_tag_meta` / `load_tag_meta` / `apply_tag_meta`）

  拆分建议：`tagparse.py` + `tagmirror.py` + `tagsync.py` + `tagmeta.py`，
  `tagfiles.py` 退化为兼容 re-export 壳（外部导入路径不变）。**纯搬移，零逻辑改动。**

- **`engine.py`（758 行）**：`run_auto()` 一个函数内嵌了 16 个闭包
  （`tag_ok` / `make_pick` / `commit_tag` / `attach_bundle` / `_commit_ext` / `_pin_collect` /
  `_slot_available` / `_pool_fill` / …）。这些闭包通过捕获 `led`（`_Ledger`）与局部集合
  互相影响，**逻辑本身是内聚的**（一次抽取就是一次事务）。

  拆分建议：**只做机械提取，不要改结构** —— 把闭包群提取成一个 `_Extraction` 类，
  `led` 与 `picks` 变成实例字段。这样 `run_auto` 变成 40 行的主流程，
  每个步骤可单独测试；同时保持"一次抽取一个账本"的语义不变。

  ⚠ **不要**试图把它拆成多个模块或引入插件式规则引擎 —— 会破坏快照零 I/O 与确定性，
  且 `quality_gate_test` 的确定性断言会立刻暴露问题。

---

## 4. P2 — 打磨项

### 4.1 前端三个巨型文件

`manager.js` 1670 / `taglib-picker.js` 1834 / `taglibrary.js` 1897 行。
三者已通过 `taglib-common.js` 共享状态与工具，边界基本清楚，**但单文件仍偏大**。
建议按"页签"切分挑选器（`tp-picker / tp-profiles / tp-groups / tp-nl / tp-conflicts`），
因为那 5 个页签本来就互不依赖，是天然边界。改前需注意：
ComfyUI 只自动加载 `web/` 下的 `.js`，所以拆出的文件必须改成 ES module 显式 import，
且新增路由要能被 `add_static` 覆盖（现有 `/taglib/static/` 已覆盖整个 `_WEB_DIR`，无需改）。

### 4.2 工作区遗留物

- `node.zip`（1.8 MB）、`ComfyUI-TagLibrary-v1.2.0-r2.zip`（990 KB）——
  v1.2.0 时代的旧发布包，与当前 1.8.x 无关。建议移出仓库或加进 `.gitignore`。
- `tests/_scratch/` 52 个历史脚本不属门禁，建议保留但明确标注为归档（现状已有目录名区隔）。

### 4.3 前端残留的测试钩子

`web/manager.js` 的 `window.__taglib = {openImportPreview, openConflictsImport, getLib}`
被 `tests/_scratch/` 里两个归档脚本使用，属**有意的测试钩子**，本次保留。
若日后清理 `_scratch`，应同步删除。

---

## 5. 明确不建议动的地方

| 项 | 理由 |
|---|---|
| 三级合并 `deep_merge`（default ← ext ← user） | 用户库整体优先的语义是"保留用户编辑"的基石，改成字段级合并会让用户改动被静默覆盖 |
| `_trim_to_budget()` 按槽位削减 | 曾被改回朴素截断，导致靠后的 style/material/camera 被系统性砍光。这是修复，不是过度设计 |
| `caps_for()` 返回 `(min_n, max_n)` 与表里 `(max, min)` 顺序相反 | 反直觉，但历史回归已证明"统一为 (min,max)"是对的。**要改的是表本身**，不是这个函数 |
| 规则真源外置（`grouprules.json` / `conflicts.json`） | 直接原因是 `.md` 热同步会重建标签 dict。除非 §2.2 的镜像机制被重写，否则不能内联 |
| `runtime_snapshot` 的"冷编译 + 只读快照" | 全仓性能基石 |

---

## 6. 执行顺序建议

| 序号 | 事项 | 前置依赖 | 风险 |
|---|---|---|---|
| 1 | §3.3 加 lint 门禁 | 无 | 极低 |
| 2 | §3.1 抽 `jsonio.atomic_write_json` | 无 | 低 |
| 3 | §2.1 热同步移出读路径（第一步） | 无 | 中 —— 需真机验"文件夹改动能被吸回" |
| 4 | §2.2 畸形标签：先写往返幂等门禁，再定 A/B 修法 | 无 | 中 —— 涉及数据，改前先备份 |
| 5 | §3.2 `_common` 约束门禁 | 1 | 低 |
| 6 | §3.4 `tagfiles.py` 四拆 | 1 | 低（纯搬移） |
| 7 | §3.4 `engine.py` 闭包 → 类 | 1 | 中 —— 改动核心逻辑，必须全程跑 `quality_gate_test` |
| 8 | §4.1 挑选器按页签拆分 | 1 | 低 |
| 9 | §4.2 清理遗留 zip | 无 | 极低 |

**第 1、2、3 项做完，收益已经拿到七成以上**：仓库不再每次读库就变脏、写入策略只有一个真源、
新增代码不会再漂移出死导入。第 6~8 项是纯收益但可以慢慢来。

---

## 7. 附：本次清理的净效果

```
api/__init__.py         -2
api/_common.py         -14  (+9)
api/conflicts_routes.py -13  (+1)
api/library_routes.py   -7
api/tagfiles_routes.py -12  (+1)
api/v13_routes.py       -8  (+2)
nodes.py               -80  (+50)
library.py              -5
web/taglibrary.js       -4
─────────────────────────────
净减少约 63 行，删除 53 处死导入、1 处进程级 GC 探针、3 处计时插桩、1 处重复实现
```
