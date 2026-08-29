"""RuntimeSnapshot (方案 V2.1 阶段 2) —— 热路径唯一输入, 只读, 双缓冲原子替换。

编译 (冷路径, 库/规则变更时后台执行一次):
    编辑树 (胖) + 规则文件 → RuntimeSnapshot (瘦)

热路径 (build 每次生成):
    snap = get_snapshot()   # 仅一次引用读取, 无锁无 I/O 无重编译

数据为紧凑并行数组 + 预建候选池; 编辑层 dict 不进入 Snapshot。
"""

from __future__ import annotations

import os
import threading

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import library
    from . import schema
    from . import tagconflicts
    from . import rules_engine
except ImportError:  # pragma: no cover
    import library
    import schema
    import tagconflicts
    import rules_engine


class _TagIndex:
    """规则引用解析器 (编译期临时结构)。"""

    __slots__ = ("_tag_id", "_cat", "_cat_subs", "cat_tag_ids", "sub_tag_ids",
                 "_sub_id", "_sub_cat")

    def __init__(self, snapshot_builder):
        b = snapshot_builder
        self._tag_id = b.en_to_id
        self._cat = b.cat_names
        self._cat_subs = b.cat_subs
        self.cat_tag_ids = b.cat_tag_ids
        self.sub_tag_ids = b.sub_tag_ids
        self._sub_id = b.sub_key_to_index
        self._sub_cat = b.sub_owner_cat

    def tag_id(self, en_lower: str):
        return self._tag_id.get(en_lower.strip().lower())

    def cat_index(self, name: str):
        name = name.strip()
        try:
            return self._cat.index(name)
        except ValueError:
            return None

    def sub_index(self, key: str):
        """key = '一级分类名/二级分类名' → 子分类序号。"""
        if "/" not in key:
            return None
        cname, sname = key.split("/", 1)
        ci = self.cat_index(cname.strip())
        if ci is None:
            return None
        si = self._cat_subs[ci].get(sname.strip())
        if si is None:
            return None
        return self._sub_id.get((cname.strip(), sname.strip()))


class RuntimeSnapshot:
    """只读快照。字段全部为一次编译后的紧凑结构, 热路径禁止修改。"""

    __slots__ = (
        "n_tags",
        "tag_ids", "tag_text", "base_weights", "spawn_rate", "priority_factor",
        "type_id", "type_names",
        "nsfw_flag", "enabled_flag",
        "sub_of", "cat_of_sub", "sub_names", "sub_keys", "cat_names",
        "sub_ids_str",
        "tag_zh", "tag_lower", "tag_aliases",
        "pools", "pools_nonsfw",
        "cat_tag_ids", "sub_tag_ids", "cat_subs", "sub_key_to_index", "sub_owner_cat",
        "en_to_id",
        "conflict_map", "require_closure", "boost_map", "cond_effects",
        "mutex_rules", "invalid_rules",
        "built_at",
    )

    def __init__(self):
        self.n_tags = 0
        self.tag_ids: list[int] = []
        self.tag_text: list[str] = []
        self.base_weights: list[float] = []
        self.spawn_rate: list[float] = []
        self.priority_factor: list[float] = []
        self.type_id: list[int] = []
        self.type_names: list[str] = []
        self.nsfw_flag = bytearray()
        self.enabled_flag = bytearray()
        self.sub_of: list[int] = []           # tag → 子分类序号
        self.cat_of_sub: list[int] = []       # 子分类序号 → 大类序号
        self.sub_ids_str: list[str] = []      # 子分类原始 id 字符串 (selection_state 引用)
        self.sub_names: list[str] = []
        self.sub_keys: list[str] = []
        self.tag_zh: list[str] = []           # 回显/搜索用
        self.tag_lower: list[str] = []        # 预降序小写 (热路径免重复 lower)
        self.tag_aliases: list = []           # tuple|None
        self.cat_names: list[str] = []
        self.pools: dict[int, list[int]] = {}         # 子分类序号 → 全部启用 tag ids
        self.pools_nonsfw: dict[int, list[int]] = {}  # 子分类序号 → 非NSFW启用 tag ids
        self.cat_tag_ids: list[list[int]] = []        # 大类序号 → tag ids (规则解析用)
        self.sub_tag_ids: list[list[int]] = []        # 子分类序号 → tag ids
        self.cat_subs: list[dict] = []                # 大类序号 → {子分类名: 子分类序号}
        self.sub_key_to_index: dict[tuple, int] = {}
        self.sub_owner_cat: dict[tuple, int] = {}
        self.en_to_id: dict[str, int] = {}
        self.conflict_map: dict[int, set] = {}
        self.require_closure: dict[int, tuple] = {}
        self.boost_map: dict[int, float] = {}
        self.cond_effects: list[tuple[frozenset, tuple, float]] = []
        self.mutex_rules: list[dict] = []
        self.invalid_rules: list[dict] = []
        self.built_at = 0.0

    def tag_id(self, en: str):
        return self.en_to_id.get(str(en).strip().lower())


# ---------------------------------------------------------------- 编译 (冷路径)

def build_snapshot(lib: dict, raw_rules: list[dict] | None = None) -> RuntimeSnapshot:
    """编辑树 + 规则 → RuntimeSnapshot。冷路径: 只在库/规则变更时执行一次。"""
    snap = RuntimeSnapshot()
    import time as _t
    snap.built_at = _t.time()

    type_names: list[str] = []
    type_index: dict[str, int] = {}

    cat_names: list[str] = []
    cat_tag_ids: list[list[int]] = []
    cat_subs: list[dict] = []
    cat_of_sub: list[int] = []
    sub_ids_str: list[str] = []
    sub_names: list[str] = []
    sub_keys: list[str] = []
    sub_tag_ids: list[list[int]] = []
    sub_key_to_index: dict[tuple, int] = {}
    sub_owner_cat: dict[tuple, int] = {}
    tag_zh: list[str] = []
    tag_lower: list[str] = []
    tag_aliases: list = []

    pools: dict[int, list[int]] = {}
    pools_nonsfw: dict[int, list[int]] = {}

    tid = 0
    for cat in lib.get("categories", []) or []:
        cname = str(cat.get("name", ""))
        ci = len(cat_names)
        cat_names.append(cname)
        cat_tag_ids.append([])
        cat_subs.append({})
        subs_map = cat_subs[ci]

        for sub in cat.get("subcategories", []) or []:
            sname = str(sub.get("name", ""))
            si = len(sub_names)
            subs_map[sname] = si
            cat_of_sub.append(ci)
            sub_names.append(sname)
            key = f"{cname}/{sname}"
            sub_keys.append(key)
            sub_key_to_index[(cname, sname)] = si
            sub_owner_cat[(cname, sname)] = ci
            sub_ids_str.append(str(sub.get("id") or key))
            stags: list[int] = []
            snonsfw: list[int] = []
            sub_tag_ids.append(stags)

            quota = sub.get("random_quota")
            _ = quota  # 编辑层字段; 运行时配额仍读 selection_state (v1 兼容)
            _ = sub.get("priority_boost", 1.0)

            for t in sub.get("tags", []) or []:
                en = str(t.get("en", "")).strip()
                if not en:
                    continue
                i = tid
                tid += 1
                snap.tag_ids.append(i)
                snap.tag_text.append(en)
                snap.base_weights.append(max(0.05, float(t.get("weight", 1.0) or 1.0)))
                snap.spawn_rate.append(schema.spawn_rate_of(t.get("rarity")))
                pr = float(t.get("priority", 50) or 50)
                snap.priority_factor.append(max(0.1, min(3.0, 0.5 + pr / 100.0)))

                ttype = str(t.get("type") or "other")
                if ttype not in type_index:
                    type_index[ttype] = len(type_names)
                    type_names.append(ttype)
                snap.type_id.append(type_index[ttype])

                nsfw = bool(t.get("nsfw"))
                snap.nsfw_flag.append(1 if nsfw else 0)
                enabled = t.get("enabled", True) is not False
                snap.enabled_flag.append(1 if enabled else 0)

                snap.sub_of.append(si)
                _low = en.lower()
                tag_lower.append(_low)
                snap.en_to_id[_low] = i
                tag_zh.append(str(t.get("zh", "") or ""))
                _al = t.get("aliases") or None
                tag_aliases.append(tuple(_al) if _al else None)
                stags.append(i)
                cat_tag_ids[ci].append(i)
                if not nsfw:
                    snonsfw.append(i)

            pools[si] = list(stags)
            pools_nonsfw[si] = list(snonsfw)

    snap.n_tags = tid
    snap.sub_ids_str = sub_ids_str
    snap.tag_zh = tag_zh
    snap.tag_lower = tag_lower
    snap.tag_aliases = tag_aliases
    snap.cat_names = cat_names
    snap.cat_tag_ids = cat_tag_ids
    snap.cat_subs = cat_subs
    snap.cat_of_sub = cat_of_sub
    snap.sub_names = sub_names
    snap.sub_keys = sub_keys
    snap.sub_tag_ids = sub_tag_ids
    snap.sub_key_to_index = sub_key_to_index
    snap.sub_owner_cat = sub_owner_cat
    snap.type_names = type_names
    snap.pools = pools
    snap.pools_nonsfw = pools_nonsfw

    # 规则编译 (mutex / requires / suppress / boost)
    raw_rules = raw_rules if raw_rules is not None else tagconflicts.load_rules()
    index = _TagIndex(snap)
    cr = rules_engine.compile_rules(raw_rules, index)
    snap.conflict_map = cr.conflict_map
    snap.require_closure = cr.require_closure
    snap.boost_map = cr.boost_map
    snap.cond_effects = cr.cond_effects
    snap.mutex_rules = cr.mutex_rules
    snap.invalid_rules = cr.invalid
    return snap


# ---------------------------------------------------------------- 双缓冲

_lock = threading.Lock()
_current: RuntimeSnapshot | None = None
_current_key: tuple | None = None


def _snapshot_key(lib: dict) -> tuple:
    return (
        os.path.getmtime(library.DEFAULT_PATH) if os.path.exists(library.DEFAULT_PATH) else 0,
        os.path.getmtime(library.USER_PATH) if os.path.exists(library.USER_PATH) else 0,
        tagconflicts._mtime_c(),
    )


def get_snapshot(lib: dict | None = None) -> RuntimeSnapshot:
    """热路径入口: 返回当前快照 (key 变化时后台语义的一次重建, 原子替换引用)。"""
    global _current, _current_key
    if lib is None:
        lib = library.get_merged()
    key = _snapshot_key(lib)
    with _lock:
        if _current is not None and _current_key == key:
            return _current
    # 冷路径重建 (锁外; 并发时最多重复编译一次, 结果一致)
    raw_rules = tagconflicts.load_rules()
    new_snap = build_snapshot(lib, raw_rules)
    with _lock:
        _current_key = key
        _current = new_snap
    return new_snap


def invalidate_snapshot() -> None:
    global _current, _current_key
    with _lock:
        _current = None
        _current_key = None
