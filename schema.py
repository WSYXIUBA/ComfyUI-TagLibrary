"""编辑层数据模型与只读迁移 (方案 V2.1 阶段 1)。

编辑层 (管理页/JSON) 允许"胖": 每个标签带 type/priority/rarity/groups/requires 等
编辑元数据; 编译层 (runtime_snapshot) 只提取热路径需要的瘦字段。

迁移原则 (已拍板):
  - **只读迁移**: get_merged 返回升级后的内存树 (version=2), 不写 user.json。
    用户在管理页保存, 或显式「升级并保存」时才随保存落盘。
  - 迁移只补默认值/推断字段, 不删除任何既有字段 → 旧库加载不丢数据。
  - `rarity` 表示生成频率: common=1.0 / uncommon=0.6 / rare=0.3 / exclusive=0.1
    (编辑层字段名保留 rarity 方便理解, 编译时转 spawn_rate 乘数)。
  - `groups` 是属性标签 (如 "hair"/"length"), 不是第三级分类。
  - `axis` 由 大类/子类 路径推断 (axes.axis_of), 与运行时快照的兜底同源。
"""

from __future__ import annotations

import re

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import axes
except ImportError:  # pragma: no cover
    import axes

# ---------------------------------------------------------------- 常量

SCHEMA_VERSION = 2

TAG_TYPES = ("quality", "descriptor", "content", "pose", "composition",
             "lighting", "scene", "style", "material", "other")

RARITY_SPAWN_RATE = {
    "common": 1.0,
    "uncommon": 0.6,
    "rare": 0.3,
    "exclusive": 0.1,
}
DEFAULT_RARITY = "common"

# 一级分类名 → 推断 type (前缀匹配; 未命中 → other)
#
# ⚠ 表里必须同时有 **轴中文名**(新结构) 与 **旧 9 大类名**(迁移工具依赖)。
#   S4 把第一级从「大类」换成「轴」之后, 这张表没跟着更新 —— 于是"新加的标签"
#   会因为 infer_type("道具武器","武器装备") 命中不到任何前缀而拿到 `other`,
#   而同类存量标签是 `content`/`pose` (它们的 type 是当年按旧大类名落的, 且
#   migrate_tag 用 setdefault 不会改写)。实测 5 条轴受影响:
#   count/character/appearance/prop → other (应为 content), action → other (应为 pose)。
#   轴名条目排在旧大类名之前: 轴名更具体, 且是当前结构的真源。
_TYPE_BY_CATEGORY = (
    # ---- 当前结构: 13 条轴 (axes.AXIS_NAME_ZH) ----
    ("画质规格", "quality"),
    ("人数", "content"),
    ("角色身份", "content"),
    ("画师", "content"),
    ("外貌特征", "content"),
    ("服装", "descriptor"),
    ("道具武器", "content"),
    ("动作姿态", "pose"),
    ("场景环境", "scene"),
    ("光影氛围", "lighting"),
    ("构图镜头", "composition"),
    ("风格媒介", "style"),
    ("材质特效", "material"),
    # ---- 旧 9 大类名 (仅迁移期数据/工具用, 保留以保证旧路径行为不变) ----
    ("质量", "quality"),
    ("画质", "quality"),
    ("人物", "content"),
    ("姿势", "pose"),
    ("构图", "composition"),
    ("镜头", "composition"),
    ("光影", "lighting"),
    ("场景", "scene"),
    ("风格", "style"),
    ("媒介", "style"),
    ("材质", "material"),
    ("特效", "material"),
)

_RE_NON_ID = re.compile(r"[^a-z0-9\-]+")


def slug(text: str, fallback: str = "x") -> str:
    s = re.sub(_RE_NON_ID, "-", (text or "").lower()).strip("-")[:40]
    return s or fallback


# ---------------------------------------------------------------- 推断

def infer_type(category_name: str, subcategory_name: str = "") -> str:
    """按 分类/子分类 名推断标签 type (冷路径, 迁移时一次)。"""
    hay = f"{category_name}{subcategory_name}"
    for prefix, t in _TYPE_BY_CATEGORY:
        if prefix in hay:
            return t
    return "other"


def normalize_rarity(value) -> str:
    v = str(value or "").strip().lower()
    return v if v in RARITY_SPAWN_RATE else DEFAULT_RARITY


def spawn_rate_of(rarity: str) -> float:
    return RARITY_SPAWN_RATE.get(normalize_rarity(rarity), 1.0)


# ---------------------------------------------------------------- 迁移

# .md 往返缺陷的产物: zh 含括号时 en 与 zh 被粘成一串, 例如
#   en="1other(单人(其他))"  (真实身份: en="1other", zh="单人(其他)")
# 2026-09-10: 解析器已允许 zh 内一层嵌套括号, 旧数据由这里就地还原。
_MALFORMED_EN_RE = re.compile(r"^(?P<base>.+?)\((?P<zh>[^()]*\([^()]*\))\)$")


def migrate_tag(tag: dict, cat_name: str, sub_name: str) -> dict:
    """编辑层标签升级 v1→v2 (就地补默认, 不删字段)。"""
    m = _MALFORMED_EN_RE.match(str(tag.get("en") or ""))
    if m:
        tag["en"] = m.group("base")
        if not (tag.get("zh") or "").strip():
            tag["zh"] = m.group("zh")
    tag.setdefault("type", infer_type(cat_name, sub_name))
    # axis 兜底注入 —— 与 runtime_snapshot 的取法同源 (t.get("axis") or axis_of(...)[0])。
    # 出厂库 tag_library.json 不带 axis; 若只靠用户库携带, 一旦用户库被清空后
    # 由 md 模板重建, 挑选器「🎯 拼装轴」视图会把全部词塌进「📦 未归类」。
    # 已有 axis 的词 (migrate_axes.py 迁移结果) 由 setdefault 原样保留。
    # 陈旧 axis 自愈: axis 是从"大类/子类路径"推导的, 词一旦换槽位 (如
    # tools/add_base_vocab.py 的 MOVES) 旧值就会变成错的, 而 runtime_snapshot
    # 优先用存储值 -> 会被当成原槽位的词写进输出 (实测 "out of frame" 搬到构图槽后
    # axis 仍是 count, 于是成了第二个人数词, 段位序也回退)。
    _want_axis = axes.axis_of(cat_name, sub_name)[0]
    if tag.get("axis") and tag["axis"] != _want_axis:
        tag["axis"] = _want_axis
        tag.pop("type", None)      # type 同样由路径推导, 一并重算
    tag.setdefault("axis", _want_axis)
    tag.setdefault("priority", 50)
    tag.setdefault("rarity", DEFAULT_RARITY)
    tag.setdefault("groups", [])
    tag.setdefault("requires", [])
    tag.setdefault("mutex_with", [])
    tag.setdefault("aliases", [])
    if not isinstance(tag.get("aliases"), list):
        tag["aliases"] = []
    tag.setdefault("desc", "")
    tag.setdefault("meta", {})
    if not isinstance(tag.get("meta"), dict):
        tag["meta"] = {}
    tag.setdefault("weight", 1.0)
    tag.setdefault("enabled", True)
    # 性别专属: ""=双性可用 / "female"=女性专属 / "male"=男性专属
    # 只标绝对性别词 (1boy/milf/pregnant...), 比基尼/女仆装等双性可穿不打
    g = str(tag.get("gender") or "").strip().lower()
    tag["gender"] = g if g in ("female", "male") else ""
    return tag


def migrate_subcategory(sub: dict, cat_name: str) -> dict:
    """子分类升级: 标签迁移 + 可选随机配额字段。"""
    sub.setdefault("random_quota", None)      # None=沿用 master/独立范围
    sub.setdefault("min_count", 1)
    sub.setdefault("max_count", 1)
    sub.setdefault("priority_boost", 1.0)
    seen: set[str] = set()
    kept: list[dict] = []
    taken_ids: set[str] = set()
    sub_id = str(sub.get("id") or "")
    for t in sub.get("tags", []) or []:
        migrate_tag(t, cat_name, sub.get("name", ""))
        key = str(t.get("en") or "").strip().lower()
        if key and key in seen:
            continue          # 修复后与既有词重名的副本: 丢弃
        seen.add(key)
        # id 兜底: `library.deep_merge` 是按 id 归并的, 没有 id 的标签会全部
        # 塌成同一个 None 键而互相覆盖 (实测新增 81 词只生效 16 个)。
        if not t.get("id") and sub_id:
            base = f"{sub_id}.{re.sub(r'\s+', '-', key)}"
            tid, n = base, 2
            while tid in taken_ids:
                tid, n = f"{base}-{n}", n + 1
            t["id"] = tid
        if t.get("id"):
            taken_ids.add(t["id"])
        kept.append(t)
    if len(kept) != len(sub.get("tags") or []):
        sub["tags"] = kept
    return sub


def migrate_category(cat: dict) -> dict:
    for s in cat.get("subcategories", []) or []:
        migrate_subcategory(s, cat.get("name", ""))
    return cat


def migrate_library(lib: dict) -> dict:
    """整库只读迁移 (内存中): version→2, 逐级补默认。不碰磁盘。

    ⚠ 前提: 只对 `library.get_merged()` 新建的合并库调用。该 dict 由
    `deep_merge` 的 `{**default, ...}` 构建, 而出厂库 tag_library.json 顶层
    不含 schema_version —— 因此这里每次都会完整跑一遍 (axis/type/groups 等
    兜底注入不会被下面的提前返回跳过)。若日后给出厂库补上 schema_version,
    必须同步提高 SCHEMA_VERSION, 否则新字段兜底会静默失效。
    """
    if lib.get("schema_version") == SCHEMA_VERSION:
        return lib
    for c in lib.get("categories", []) or []:
        migrate_category(c)
    lib["schema_version"] = SCHEMA_VERSION
    return lib


def migrate_rules(rules: list[dict]) -> list[dict]:
    """规则升级 v1(无 type)→v2: 补 type=mutex / enabled / priority / scope。"""
    out = []
    for r in rules or []:
        r = dict(r)
        r.setdefault("type", "mutex")
        r.setdefault("enabled", True)
        r.setdefault("priority", 100)
        r.setdefault("scope", ["auto", "manual_fill"])
        r.setdefault("params", {})
        out.append(r)
    return out
