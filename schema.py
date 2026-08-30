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
"""

from __future__ import annotations

import re

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
_TYPE_BY_CATEGORY = (
    ("质量", "quality"),
    ("画质", "quality"),
    ("人物", "content"),
    ("服装", "descriptor"),
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

def migrate_tag(tag: dict, cat_name: str, sub_name: str) -> dict:
    """编辑层标签升级 v1→v2 (就地补默认, 不删字段)。"""
    tag.setdefault("type", infer_type(cat_name, sub_name))
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
    for t in sub.get("tags", []) or []:
        migrate_tag(t, cat_name, sub.get("name", ""))
    return sub


def migrate_category(cat: dict) -> dict:
    for s in cat.get("subcategories", []) or []:
        migrate_subcategory(s, cat.get("name", ""))
    return cat


def migrate_library(lib: dict) -> dict:
    """整库只读迁移 (内存中): version→2, 逐级补默认。不碰磁盘。"""
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
