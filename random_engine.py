"""随机引擎 Fast / Smart (方案 V2.1 阶段 3) —— 热路径, 只读快照, 零 I/O。

Fast   : 预建池 + 加权不放回 (Efraimidis-Spirakis) + mutex 让位 + 配额 —— 对齐 v1 行为
Smart  : Fast + requires 闭包并入 + boost/条件suppress + diversity(最近组合降权/重抽)

确定性: 同 seed 同快照同 state → 同输出 (rng 为每次独立 Random(seed))。
热路径约定: 不读盘、不建大对象、字符串只在最后一次 join 前拼接。
"""

from __future__ import annotations

import random as _random

# 内置命名方案 (state.random_config_ref 引用; 不需要 lib settings 就能用)
BUILTIN_CONFIGS = {
    "default_fast": {"engine": "fast"},
    "default_smart": {"engine": "smart", "diversity": 0.7, "avoid_recent": 3},
}

DEFAULT_CONFIG = {
    "engine": "fast",              # fast | smart
    "diversity": 0.0,              # 0-1; >0 时最近出现过的标签权重 ×0.5
    "avoid_recent": 3,             # 最近组合保留数 (组合 hash 环形缓冲)
    "prefer_presets_prob": 0.0,    # v2.2 预留 (Bundle)
    "total_min": None,
    "total_max": None,
    "stage_order": None,           # None = 快照顺序
}

MAX_REROLL = 3                    # 组合撞最近缓存时的重抽上限


class AutoResult:
    __slots__ = ("fixed_ids", "rest_ids", "mutex_dropped", "mutex_dropped_ids")

    def __init__(self, fixed_ids, rest_ids, mutex_dropped, mutex_dropped_ids=None):
        self.fixed_ids = fixed_ids      # 钉选强制包含的 id
        self.rest_ids = rest_ids        # 引擎抽到的 id (按输出顺序)
        self.mutex_dropped = mutex_dropped  # 被 mutex 让位掉的 id 数 (诊断)
        self.mutex_dropped_ids = mutex_dropped_ids or []  # 让位标签 id (回显灰显, 上限24)


class _Ctx:
    """单次 build 的可变小缓冲 (ComfyUI 节点执行为单线程顺序, 复用安全)。"""

    __slots__ = ("used", "banned")

    def __init__(self):
        self.used: set[str] = set()
        self.banned: set[int] = set()


def resolve_config(state: dict, lib_settings: dict | None) -> dict:
    """state.random_config_ref → 命名配置 (内置 default_fast/default_smart +
    库 settings.random_configs 自定义方案); 缺省 Fast。"""
    cfg = {}
    ref = str(state.get("random_config_ref") or "")
    if ref:
        configs = (lib_settings or {}).get("random_configs") or {}
        cfg = configs.get(ref) or BUILTIN_CONFIGS.get(ref) or {}
    out = dict(DEFAULT_CONFIG)
    out.update(cfg or {})
    if not out.get("engine"):
        out["engine"] = "fast"
    return out


def run_auto(snap, state: dict, seed: int, *, nsfw_on: bool,
             avoid_conflicts: bool = True, search_text: str = "",
             cat_weights: dict | None = None, config: dict | None = None,
             recent_sets=None) -> AutoResult:
    """自动模式出词。返回 (fixed_ids, rest_ids); 文本格式化由调用方完成。"""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    smart = cfg.get("engine") == "smart"
    diversity = float(cfg.get("diversity") or 0.0) if smart else 0.0
    total_max = cfg.get("total_max")

    rng = _random.Random(seed)
    ctx = _Ctx()

    # ---------- 排除类目: 大类名集合 / "大类/子类" key 集合 ----------
    excl_cats: set[str] = set()
    excl_keys: set[str] = set()
    for e in state.get("exclude_categories") or []:
        e = str(e)
        if "/" in e:
            excl_keys.add(e)
        else:
            excl_cats.add(e)

    conflict_map = snap.conflict_map if avoid_conflicts else None
    cond_effects = snap.cond_effects if smart else []
    require_closure = snap.require_closure if smart else {}

    search_l = search_text.strip().lower()

    mutex_dropped_ids: list[int] = []

    def grow(ids) -> None:
        if conflict_map:
            for i in ids:
                banned = ctx.banned
                banned.update(conflict_map.get(i, ()))

    # ---------- 钉选 (含于排除类目时按 v1 语义丢弃) ----------
    fixed_ids: list[int] = []
    rest_ids: list[int] = []
    state_tags = state.get("tags") or []

    # v1 兼容: state["pinned"] 为标签原始 id 字符串列表 (旧工作流格式)
    legacy_pinned = state.get("pinned") or []
    cat_of_sub, sub_of, names = snap.cat_of_sub, snap.sub_of, snap.cat_names
    for t in state_tags:
        if not isinstance(t, dict):
            continue
        lo = str(t.get("en", "")).strip().lower()
        tid = snap.en_to_id.get(lo)
        if tid is None:
            continue
        ci = cat_of_sub[sub_of[tid]]
        if names[ci] in excl_cats:
            continue
        if t.get("pinned"):
            if lo in ctx.used:
                continue
            fixed_ids.append(tid)
            ctx.used.add(lo)
    grow(fixed_ids)

    # ---------- recent 计数 (Smart diversity) ----------
    recent_tag_count: dict[int, int] = {}
    if diversity > 0 and recent_sets:
        for rs in recent_sets[:avoid_recent_n(cfg)]:
            for i in rs:
                recent_tag_count[i] = recent_tag_count.get(i, 0) + 1

    cond_list = cond_effects

    def cond_factor(tid: int, used_set: set) -> float:
        f = 1.0
        for lset, rids, fac in cond_list:
            if lset & used_set and tid in rids:
                f *= fac
        return f

    # ---------- 逐子分类池抽取 ----------
    master = state.get("fill_master")
    master = True if master is None else bool(master)

    def _int_or(val, default):
        # 注意: 0 是合法配额, 不能用 `or` 兜底 (falsy-zero 坑)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    mlo = _int_or(state.get("fill_master_min"), 1)
    mhi = _int_or(state.get("fill_master_max"), 1)
    sub_ranges = state.get("fill_sub_ranges") or {}
    sub_ids_str = snap.sub_ids_str

    pools = snap.pools if nsfw_on else snap.pools_nonsfw

    def tag_match(lo: str, tid: int) -> bool:
        if not search_l:
            return True
        if search_l in lo or search_l in snap.tag_zh[tid].lower():
            return True
        aliases = snap.tag_aliases[tid]
        if aliases:
            for a in aliases:
                if search_l in a.lower():
                    return True
        return False

    def cat_weight(cat_name: str) -> float:
        if not cat_weights:
            return 1.0
        return max(float(cat_weights.get(cat_name, 1.0) or 0.001), 0.001)

    for pid in legacy_pinned:
        tid = snap.orig_id_to_int.get(str(pid))
        if tid is None:
            continue  # 不在库中 → v1 pool_dict 语义: 跳过
        ci = snap.cat_of_sub[snap.sub_of[tid]]
        if snap.cat_names[ci] in excl_cats:
            continue
        if snap.sub_keys[snap.sub_of[tid]] in excl_keys:
            continue
        lo = snap.tag_lower[tid]
        if lo in ctx.used:
            continue
        fixed_ids.append(tid)
        ctx.used.add(lo)
    grow(fixed_ids)

    pool_order = list(range(len(snap.sub_names))) if not cfg.get("stage_order") else _stage_order(
        cfg.get("stage_order"), snap)
    # 随机打乱子分类顺序: 防互斥域结构性偏向 (如 上装先抽 → 套装75词永远让位)。
    # 同 seed 确定性不受影响 — rng 是本调用的独立 Random(seed)。质量类子分类仍保持在前
    # (质量词只与内容词互补, 顺序无冲突), 只打乱非质量域。
    if cfg.get("shuffle_pools", True):
        rng.shuffle(pool_order)

    for si in pool_order:
        cname = names[cat_of_sub[si]]
        if cname in excl_cats:
            continue
        skey = snap.sub_keys[si]
        if skey in excl_keys:
            continue
        if master:
            mn, mx = min(mlo, mhi), max(mlo, mhi)
        else:
            r = (sub_ranges.get(sub_ids_str[si]) or {})
            a = _int_or(r.get("min"), 1)
            b = _int_or(r.get("max"), 1)
            mn, mx = min(a, b), max(a, b)
        if mx <= 0:
            continue
        want = rng.randint(mn, mx)
        cw = cat_weight(cname)

        cands = []
        for tid in pools[si]:
            lo = snap.tag_lower[tid]
            if lo in ctx.used:
                continue
            if tid in ctx.banned:
                if len(mutex_dropped_ids) < 24:
                    mutex_dropped_ids.append(tid)
                continue
            if not tag_match(lo, tid):
                continue
            w = (snap.base_weights[tid] * snap.spawn_rate[tid]
                 * snap.priority_factor[tid] * cw)
            if smart:
                w *= snap.boost_map.get(tid, 1.0)
                f = cond_factor(tid, ctx.used)
                if f != 1.0:
                    w *= f
                if diversity and recent_tag_count.get(tid):
                    w *= 0.5
            if w <= 0.0001:
                continue
            cands.append((rng.random() ** (1.0 / max(w, 1e-6)), tid))

        if not cands:
            continue
        cands.sort(reverse=True)
        # 顺序吸收: 已抽中的会让位同池后续候选 (mutex/gc 复用 ctx 缓冲)
        picked_here = 0
        for _key, tid in cands:
            if picked_here >= want:
                break
            lo = snap.tag_lower[tid]
            if lo in ctx.used or tid in ctx.banned:
                continue
            rest_ids.append(tid)
            ctx.used.add(lo)
            grow([tid])
            picked_here += 1

    # ---------- Smart: requires 闭包并入 (受 mutex/NSFW/排除约束) ----------
    if smart and require_closure:
        for tid in list(rest_ids) + list(fixed_ids):
            for req in require_closure.get(tid, ()):
                lo = snap.tag_lower[req]
                if lo in ctx.used:
                    continue
                ci = cat_of_sub[sub_of[req]]
                if names[ci] in excl_cats:
                    continue
                if not nsfw_on and snap.nsfw_flag[req]:
                    continue
                if conflict_map and req in ctx.banned:
                    continue
                rest_ids.append(req)
                ctx.used.add(lo)
                grow([req])

    # ---------- total_max 裁剪 (保钉选/require, 去低权重) ----------
    if total_max:
        try:
            tmax = int(total_max)
        except (TypeError, ValueError):
            tmax = None
        if tmax and len(rest_ids) > tmax:
            weighted = sorted(rest_ids, key=lambda i: snap.base_weights[i])
            drop = set(weighted[: len(rest_ids) - tmax])
            rest_ids = [i for i in rest_ids if i not in drop]
            ctx.used.difference_update(drop)

    return AutoResult(fixed_ids, rest_ids, len(ctx.banned), mutex_dropped_ids)


def _si_of(snap, tid: int) -> int:
    return snap.sub_of[tid]


def _stage_order(order: list, snap) -> list[int]:
    """stage_order (类型名列表) → 子分类序号顺序 (匹配类型优先, 其余按原序追加)。"""
    name_to_type = {n: i for i, n in enumerate(snap.type_names)}
    type_of_sub = []
    for si in range(len(snap.sub_names)):
        tids = snap.sub_tag_ids[si]
        t = snap.type_id[tids[0]] if tids else -1
        type_of_sub.append(t)
    order_idx = [name_to_type[o] for o in order if o in name_to_type]
    seen, seq = set(), []
    for want_t in order_idx:
        for si in range(len(snap.sub_names)):
            if type_of_sub[si] == want_t and si not in seen:
                seq.append(si)
                seen.add(si)
    for si in range(len(snap.sub_names)):
        if si not in seen:
            seq.append(si)
            seen.add(si)
    return seq


def avoid_recent_n(cfg: dict) -> int:
    try:
        return max(0, min(5, int(cfg.get("avoid_recent", 3) or 0)))
    except (TypeError, ValueError):
        return 3


def note_combination(recent: list, chosen_ids: list, cfg: dict) -> None:
    """组合短 hash 环形缓冲 (Smart diversity 用)。recent 由调用方持有。"""
    n = avoid_recent_n(cfg)
    if n <= 0:
        return
    recent.append(frozenset(chosen_ids))
    while len(recent) > n:
        recent.pop(0)


def combo_is_recent(recent: list, chosen_ids: list) -> bool:
    fs = frozenset(chosen_ids)
    return any(fs == x for x in recent)
