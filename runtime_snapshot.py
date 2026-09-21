"""RuntimeSnapshot (1.3.0) —— 热路径唯一输入, 只读, 双缓冲原子替换。

编译 (冷路径, 库/档案/规则变更时一次):
    编辑树 (胖) + profiles.json + conflicts.json(跨池规则) → RuntimeSnapshot

新架构要点:
  - 互斥 = 全局组名交集 (R1) + 跨池集合规则 (R2), 不再是 81 条手写规则。
  - 档案库 (tags_ext): 武器/物体档案的姿势编译进 action 轴的挂载池,
    带资源消耗 (hands/gaze) 与状态槽 —— 抽取在 engine 里按预算算账 (R3/R4)。
  - 轴 (axis) 决定输出顺序 (Anima 拼接序)。
热路径: get_snapshot() 仅一次引用读取, 无锁无 I/O 无重编译。
"""

from __future__ import annotations

import os
import threading

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import library
    from . import schema
    from . import tagconflicts
    from . import axes
    from . import grouprules
    from . import profiles as profiles_mod
    from . import slotpolicy
except ImportError:  # pragma: no cover
    import library
    import schema
    import tagconflicts
    import axes
    import grouprules
    import profiles as profiles_mod
    import slotpolicy

ALL = object()  # banned 集合中的全禁哨兵


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
        "nsfw_flag", "enabled_flag", "gender_flag",
        "sub_of", "cat_of_sub", "sub_names", "sub_keys", "cat_names",
        "sub_ids_str",
        "tag_zh", "tag_lower", "tag_aliases",
        "pools", "pools_nonsfw",
        "pools_nofemale", "pools_nomale",
        "cat_tag_ids", "sub_tag_ids", "cat_subs", "sub_key_to_index", "sub_owner_cat",
        "en_to_id", "orig_id_to_int",
        # ---- 1.3.0
        "group_sets",        # per-tag frozenset[str] 全局互斥组名
        "axis_arr", "order_arr", "pool_axis", "pool_order",
        "cross_rules",       # [(frozenset L, tuple R)] 跨池结构性规则
        "tags_ext",          # 档案姿势编译条目 (dict, 见 _compile_ext)
        "profiles", "profile_errors",
        "cross_banned",
        "bundled_only",      # 只能经档案束出生的库内 tag id 集 (池抽取永跳过)
        "en_groups",         # en_lower → grouprules 组名 (ext 词不在库内, 按词查表)
        "minor_block_words",  # 未成年在场时全池屏蔽词 (出厂表 ∪ 扩展包 minor_block 词)
        "hands_cost",        # per-tag 双手资源占用 (lib 词级, 如乳交=2; 0 = 无)
        "explicit_flag",     # 显式档标记 (NSFW 强度旋钮的分层加权输入)
        # ---- 旧编译规则 (conflicts 页语义保留; 1.3.0 起仅作兜底黑名单)
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
        self.gender_flag = bytearray()
        self.sub_of: list[int] = []
        self.cat_of_sub: list[int] = []
        self.sub_ids_str: list[str] = []
        self.sub_names: list[str] = []
        self.sub_keys: list[str] = []
        self.tag_zh: list[str] = []
        self.tag_lower: list[str] = []
        self.tag_aliases: list = []
        self.cat_names: list[str] = []
        self.pools: dict[int, list[int]] = {}
        self.pools_nonsfw: dict[int, list[int]] = {}
        self.pools_nofemale: dict[int, list[int]] = {}
        self.pools_nomale: dict[int, list[int]] = {}
        self.cat_tag_ids: list[list[int]] = []
        self.sub_tag_ids: list[list[int]] = []
        self.cat_subs: list[dict] = []
        self.sub_key_to_index: dict[tuple, int] = {}
        self.sub_owner_cat: dict[tuple, int] = {}
        self.en_to_id: dict[str, int] = {}
        self.orig_id_to_int: dict[str, int] = {}
        self.group_sets: list[frozenset] = []
        self.axis_arr: list[str] = []
        self.order_arr: list[int] = []
        self.pool_axis: dict[int, str] = {}
        self.pool_order: dict[int, int] = {}
        self.cross_rules: list[tuple[frozenset, tuple]] = []
        self.cross_banned: dict[int, frozenset] = {}
        self.bundled_only: frozenset = frozenset()
        self.en_groups: dict[str, frozenset] = {}
        self.minor_block_words: frozenset = frozenset(slotpolicy.MINOR_BLOCK_WORDS)
        self.hands_cost: list[int] = []
        self.explicit_flag = bytearray()
        self.tags_ext: list[dict] = []
        self.profiles: list = []
        self.profile_errors: list[dict] = []
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

def build_snapshot(lib: dict, raw_rules: list[dict] | None = None,
                   prof_data: dict | None = None) -> RuntimeSnapshot:
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
    pools_nofemale: dict[int, list[int]] = {}
    pools_nomale: dict[int, list[int]] = {}
    _minor_extra: set[str] = set()

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
            axis, order = axes.axis_of(cname, sname)
            snap.pool_axis[si] = axis
            snap.pool_order[si] = order
            stags: list[int] = []
            snonsfw: list[int] = []
            sub_tag_ids.append(stags)

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
                g = str(t.get("gender") or "").strip().lower()
                snap.gender_flag.append(1 if g == "female" else (2 if g == "male" else 0))
                # 1.8.0: 词级双手占用 (paizuri=2, handjob=1 …)
                try:
                    snap.hands_cost.append(max(0, int(t.get("hands_cost") or 0)))
                except (TypeError, ValueError):
                    snap.hands_cost.append(0)
                snap.explicit_flag.append(1 if t.get("explicit") else 0)

                snap.sub_of.append(si)
                _low = en.lower()
                # 未成年屏蔽词扩展 (1.8.0): 扩展包 nsfw 词带 minor_block: true
                if t.get("minor_block"):
                    _minor_extra.add(_low)
                tag_lower.append(_low)
                snap.en_to_id[_low] = i
                _oid = str(t.get("id") or "")
                if _oid:
                    snap.orig_id_to_int[_oid] = i
                tag_zh.append(str(t.get("zh", "") or ""))
                _al = t.get("aliases") or None
                tag_aliases.append(tuple(_al) if _al else None)
                # 1.3.0: 轴 + 全局互斥组名
                snap.axis_arr.append(str(t.get("axis") or axis))
                # 输出次序 = Anima 段位优先 (style 回到第 1 段); 抽取次序用上面的
                # pool_order(=轴次序) 保持不变, 否则人数词会晚于外貌词出生、
                # 性别锁失效。
                snap.order_arr.append(axes.output_order(axis, order))
                gs = t.get("groups") or []
                snap.group_sets.append(frozenset(str(x) for x in gs if x))
                stags.append(i)
                cat_tag_ids[ci].append(i)
                if not nsfw:
                    snonsfw.append(i)

            pools[si] = list(stags)
            pools_nonsfw[si] = list(snonsfw)
            pools_nofemale[si] = [i for i in stags if snap.gender_flag[i] != 1]
            pools_nomale[si] = [i for i in stags if snap.gender_flag[i] != 2]

    snap.n_tags = tid
    snap.sub_ids_str = sub_ids_str
    snap.tag_zh = tag_zh
    snap.tag_lower = tag_lower
    snap.tag_aliases = tag_aliases
    snap.minor_block_words = frozenset(slotpolicy.MINOR_BLOCK_WORDS | _minor_extra)
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
    snap.pools_nofemale = pools_nofemale
    snap.pools_nomale = pools_nomale

    # ---- 规则编译: 跨池结构性规则 (conflicts.json 迁移后剩余部分)
    raw_rules = raw_rules if raw_rules is not None else tagconflicts.load_rules()
    tag_conflicts_lib_index = tagconflicts._lib_index(lib)
    for r in raw_rules:
        lset, ok_l = tagconflicts.resolve_ref(r["left"], tag_conflicts_lib_index)
        rset: set = set()
        for ref in r.get("right") or []:
            s, _ = tagconflicts.resolve_ref(ref, tag_conflicts_lib_index)
            rset |= s
        if not ok_l or not lset or not rset:
            continue
        lids = {snap.tag_id(x) for x in lset} - {None}
        rids = {snap.tag_id(x) for x in rset} - {None}
        if not lids or not rids:
            continue
        snap.cross_rules.append((frozenset(lids), tuple(sorted(rids))))

    # 全局互斥域 (grouprules.json + nsfw 扩展) 在此并集进 group_sets —— 标签身上的
    # groups 字段会被热同步重导入抹掉, 独立文件按 en 查表才免疫。
    # 1.8.0: 同名 en 的多个副本 (跨槽位重复) 全部并组 —— en_to_id 只指向最后一个,
    # 只给最后一个并组会让其余副本绕过互斥 (实测 egg vibrator 双副本漏拦)。
    gr_membership = grouprules.en_membership()
    snap.en_groups = gr_membership  # 档案 ext 词 (不在库内) 出生时按词查这张表
    if gr_membership:
        en_tids: dict[str, list[int]] = {}
        for _i, _l in enumerate(tag_lower):
            if _l in gr_membership:
                en_tids.setdefault(_l, []).append(_i)
        for en_l, gs in gr_membership.items():
            for _tid in en_tids.get(en_l, ()):
                snap.group_sets[_tid] = snap.group_sets[_tid] | gs

    # ---------- 档案编译 (tags_ext): 姿势挂载到武器身份词的池
    if prof_data is None:
        prof_data = profiles_mod.load_profiles()
    profs, perrs = profiles_mod.compile_profiles(prof_data)
    snap.profiles = profs
    snap.profile_errors = perrs
    _compile_ext(snap, profs)

    # cross_banned 须在 grouprules/档案派生组并集之后构建 (保持简单: 此处重算一次)
    cross_banned = {}
    for lset, rids in snap.cross_rules:
        rs = set(rids)
        ls = set(lset)
        for l in ls:
            cross_banned.setdefault(l, set()).update(rs - {l})
        for r in rs:
            cross_banned.setdefault(r, set()).update(ls - {r})
    snap.cross_banned = {k: frozenset(v) for k, v in cross_banned.items()}

    # 旧规则类型 (requires/suppress/boost) 1.3.0 起停用 (任务书 §2.3)
    return snap


def _compile_ext(snap: RuntimeSnapshot, profs) -> None:
    """档案姿势 → tags_ext 条目。

    条目字段:
      pid, pose_id, mount (挂载武器 id 集合 = 身份词 tag id ∪ 档案级),
      hands, gaze, weight, state (f"{slot}={value}" 集合),
      axis='action', order (+1 使其紧跟身份词),
      ext_tags (输出标签序列), en_key (占用判定), zh
    """
    ext: list[dict] = []
    derived: dict[int, set] = {}   # 库内 tag → 束级派生组名 (implies/黑名单)
    bundled: set[int] = set()      # 束专属词: 池中永不自抽 (姿势只能跟武器出生)
    for prof in snap.profiles:
        for pose in list(prof.poses) + list(prof.extras):
            for t, gs in pose.group_membership().items():
                tid = snap.tag_id(t)
                if tid is not None:
                    derived.setdefault(tid, set()).update(gs)
            # 束专属 = 姿势/配件自己的 tags 词 (implies 是借用的通用词, 不专属)
            for t in pose.tags:
                tid = snap.tag_id(t)
                if tid is not None:
                    bundled.add(tid)
    for tid, gs in derived.items():
        snap.group_sets[tid] = frozenset(snap.group_sets[tid] | gs)
    snap.bundled_only = frozenset(bundled)
    # 束完整组集 = 自己的组名 ∪ 全部成员词(含 implies)的组集 ——
    # 检查/登记都必须用这个全集, 只查自己那条组名会漏拦跨档案共享词
    # (如 "weapon on back" 同时属于 4 个档案的收纳组)。
    # 成员词不在库内时 (ext 词, 如 sword out of mouth) group_sets 查不到,
    # 按 en_groups 补查 grouprules 域 —— 否则衔物姿出生不拦 eating/smirk 等嘴部词。
    for prof in snap.profiles:
        for pose in list(prof.poses) + list(prof.extras):
            g = set(pose.extra_groups)
            for t in list(pose.tags) + list(pose.implies):
                tl = str(t).strip().lower()
                tid = snap.tag_id(t)
                if tid is not None:
                    g |= snap.group_sets[tid]
                else:
                    eg = snap.en_groups.get(tl)
                    if eg:
                        g |= eg
            pose.comp_groups = frozenset(g)
    for prof in snap.profiles:
        mount_ids = set()
        for w in prof.tags:
            tid = snap.tag_id(w)
            if tid is not None:
                mount_ids.add(tid)
        for pose in prof.poses:
            if not pose.tags:
                continue
            state = {f"{k}={v}" for k, v in pose.state_slot.items()}
            ext.append({
                "pid": prof.id,
                "pose_id": pose.pose_id,
                "kind": "pose",
                "mount_ids": frozenset(mount_ids),
                "hands": pose.hands,
                "gaze": pose.gaze,
                "weight": max(pose.weight, 0.0),
                "state": frozenset(state),
                "axis": "action",
                "ext_tags": tuple(pose.tags),
                "en_key": tuple(t.lower() for t in pose.tags),
                "zh": pose.zh,
            })
        for ex in prof.extras:
            if not ex.tags:
                continue
            state = {f"{k}={v}" for k, v in ex.state_slot.items()}
            ext.append({
                "pid": prof.id,
                "pose_id": ex.pose_id,
                "kind": "extra",
                "mount_ids": frozenset(mount_ids),
                "hands": ex.hands,
                "gaze": ex.gaze,
                "weight": max(ex.weight, 0.0),
                "state": frozenset(state),
                "axis": "appearance",
                "order": 2,
                "ext_tags": tuple(ex.tags),
                "en_key": tuple(t.lower() for t in ex.tags),
                "zh": ex.zh,
            })
    snap.tags_ext = ext


# ---------------------------------------------------------------- 双缓冲

_lock = threading.Lock()
_current: RuntimeSnapshot | None = None
_current_key: tuple | None = None


def _snapshot_key(lib: dict) -> tuple:
    return (
        os.path.getmtime(library.DEFAULT_PATH) if os.path.exists(library.DEFAULT_PATH) else 0,
        os.path.getmtime(library.EXT_PATH) if os.path.exists(library.EXT_PATH) else 0,
        os.path.getmtime(library.USER_PATH) if os.path.exists(library.USER_PATH) else 0,
        tagconflicts._mtime_c(),
        grouprules._mtime(),
        profiles_mod._mtime(),
    )


def get_snapshot(lib: dict | None = None) -> RuntimeSnapshot:
    global _current, _current_key
    if lib is None:
        lib = library.get_merged()
    key = _snapshot_key(lib)
    with _lock:
        if _current is not None and _current_key == key:
            return _current
    raw_rules = tagconflicts.load_rules()
    prof_data = profiles_mod.load_profiles()
    new_snap = build_snapshot(lib, raw_rules, prof_data)
    with _lock:
        _current_key = key
        _current = new_snap
    return new_snap


def invalidate_snapshot() -> None:
    global _current, _current_key
    with _lock:
        _current = None
        _current_key = None
