"""抽取引擎 (1.3.0) —— 原子档案束 + 资源预算 + 组互斥, 热路径零 I/O。

抽取管线 (固定次序, 让约束在出生前生效):
  0. 钉选 (面板 📌) → 占其子分类配额; 若钉的是档案身份词, 立即配束
  1. prop 域抽取 (武器/道具) → 每次抽中档案身份词即原子配一条姿势束
     (束内 tags 全有或全无: 资源/状态/组互斥任一不过 → 整条束换一条)
  2. 其余子分类池按配额抽取 (含 action 域), 每一步查三件事:
       R1 组互斥: 候选 group_sets 与已选集有交集 → 弃
       R2 跨池规则: 命中 cross_rules 两侧 → 弃
       R3 资源预算: hands/gaze 超 BODY_RESOURCES → 弃
       R4 状态槽: 同一 state 槽已占且值不同 → 弃
     注: 池顺序按轴 (clothing→prop→action→…) 固定, 束先于动作池出生,
     动作池自然让位给束的手数与姿态 (implies 并入后由组互斥接管)。

确定性: rng = Random(seed) 每次独立 → 同 seed 同快照同 state 同输出。
"""

from __future__ import annotations

import random as _random

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from .profiles import BODY_RESOURCES
except ImportError:  # pragma: no cover
    from profiles import BODY_RESOURCES

MAX_REROLL = 3
DEFAULT_CONFIG = {"total_max": None, "bundle_pose_prob": 0.85,
                  "extra_prob": 0.35}


class Pick:
    """一条输出单元。

    kind: 'tag' (库内标签) | 'ext' (档案姿势束成员, 不在库内)
    order: 全局输出次序 (轴次序; 束成员 = 挂载词次序+偏移)
    """

    __slots__ = ("id", "en", "zh", "weight", "nsfw", "gender", "cat",
                 "axis", "order", "kind", "bundle", "source", "hands", "gaze",
                 "is_extra")

    def __init__(self, tid, en, zh, weight, nsfw, gender, cat, axis, order,
                 kind="tag", bundle=None, source="random", hands=0, gaze=0,
                 is_extra=False):
        self.id = tid
        self.en = en
        self.zh = zh
        self.weight = weight
        self.nsfw = nsfw
        self.gender = gender
        self.cat = cat
        self.axis = axis
        self.order = order
        self.kind = kind
        self.bundle = bundle
        self.source = source
        self.hands = hands
        self.gaze = gaze
        self.is_extra = is_extra


class AutoResult:
    __slots__ = ("picks", "dropped_ids", "stats")

    def __init__(self, picks, dropped_ids, stats):
        self.picks = picks            # list[Pick], 已按输出次序排序
        self.dropped_ids = dropped_ids  # 被约束让位的库内标签 id (诊断回显)
        self.stats = stats


def resolve_config(state: dict, lib_settings: dict | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    ref = str(state.get("random_config_ref") or "")
    if ref:
        configs = (lib_settings or {}).get("random_configs") or {}
        cfg.update(configs.get(ref) or {})
    # 面板 ⚙ 直写键优先
    for k in ("bundle_pose_prob", "extra_prob", "total_max"):
        if state.get(k) is not None:
            cfg[k] = state[k]
    return cfg


class _Ledger:
    """单次抽取的账本: 用过的词/组名/资源/状态槽 + 增量违禁集。"""

    __slots__ = ("used_lower", "used_groups", "hands", "gaze", "states",
                 "used_ids", "banned_ids", "prop_count")

    def __init__(self):
        self.used_lower: set[str] = set()
        self.used_groups: set[str] = set()
        self.hands = 0
        self.gaze = 0
        self.states: dict[str, str] = {}   # slot -> value
        self.used_ids: set[int] = set()
        self.banned_ids: set[int] = set()  # cross_banned 增量并集
        self.prop_count = 0                # 已出生的武器档案身份词数

    def budget_ok(self, hands: int, gaze: int, state: frozenset,
                  groups: frozenset) -> bool:
        if self.hands + hands > BODY_RESOURCES["hands"]:
            return False
        if self.gaze + gaze > BODY_RESOURCES["gaze"]:
            return False
        if self.used_groups & groups:
            return False
        for sv in state:
            k, _, v = sv.partition("=")
            cur = self.states.get(k)
            if cur is not None and cur != v:
                return False
        return True

    def cross_ok(self, tid: int) -> bool:
        return tid not in self.banned_ids

    def ban_grow(self, tid: int, cross_banned: dict) -> None:
        b = cross_banned.get(tid)
        if b:
            self.banned_ids |= b


def _norm(x) -> str:
    return str(x or "").strip().lower()


def run_auto(snap, state: dict, seed: int, *, nsfw_on: bool,
             avoid_conflicts: bool = True, search_text: str = "",
             cat_weights: dict | None = None, config: dict | None = None,
             recent_sets=None) -> AutoResult:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    rng = _random.Random(seed)
    led = _Ledger()
    picks: list[Pick] = []
    dropped: list[int] = []
    cross_banned = snap.cross_banned if avoid_conflicts else {}

    # ---------- 排除域 ----------
    excl_cats: set[str] = set()
    excl_keys: set[str] = set()
    for e in state.get("exclude_categories") or []:
        e = str(e)
        (excl_keys if "/" in e else excl_cats).add(e)

    gmode = str(state.get("gender") or "off").strip().lower()

    def tag_ok(tid: int) -> bool:
        """排除/NSFW/性别 三闸门 (候选级)。"""
        if not nsfw_on and snap.nsfw_flag[tid]:
            return False
        g = snap.gender_flag[tid]
        if gmode == "female" and g == 2:
            return False
        if gmode == "male" and g == 1:
            return False
        si = snap.sub_of[tid]
        cname = snap.cat_names[snap.cat_of_sub[si]]
        if cname in excl_cats or snap.sub_keys[si] in excl_keys:
            return False
        return True

    def make_pick(tid: int, source: str = "random") -> Pick:
        si = snap.sub_of[tid]
        ci = snap.cat_of_sub[si]
        return Pick(tid, snap.tag_text[tid], snap.tag_zh[tid],
                    snap.base_weights[tid], bool(snap.nsfw_flag[tid]),
                    ("female" if snap.gender_flag[tid] == 1 else
                     "male" if snap.gender_flag[tid] == 2 else ""),
                    snap.cat_names[ci], snap.axis_arr[tid], snap.order_arr[tid],
                    "tag", None, source)

    def commit_tag(tid: int, source: str = "random") -> Pick:
        p = make_pick(tid, source)
        # order = 池基数 + 提交序号: 同池按出生序, 束成员紧贴宿主 (基数差≥1 ≫ 序号增量)
        p.order = snap.order_arr[tid] + len(picks) * 1e-5
        picks.append(p)
        led.used_ids.add(tid)
        led.used_lower.add(snap.tag_lower[tid])
        led.used_groups |= snap.group_sets[tid]
        if cross_banned:
            b = cross_banned.get(tid)
            if b:
                led.banned_ids |= b
        return p

    # ---------- 档案索引 ----------
    mount_of_tag: dict[int, list] = {}
    pose_group_of: dict[str, frozenset] = {}
    for prof in snap.profiles:
        pose_group_of[prof.id] = frozenset({f"prof:{prof.id}"})
        for w in prof.tags:
            tid = snap.tag_id(w)
            if tid is not None:
                mount_of_tag.setdefault(tid, []).append(prof)
    max_prop = int(cfg.get("max_weapons", 2) or 2)

    def attach_bundle(host_tid: int, host_order: int, host_cat: str,
                      host_axis: str) -> int:
        """给身份词配一条姿势束 + 按概率配件。返回束内 tag 数。"""
        profs = mount_of_tag.get(host_tid)
        if not profs:
            return 0
        if led.prop_count >= max_prop:
            return 0
        led.prop_count += 1
        prof = profs[0]
        my_g = pose_group_of[prof.id]
        n = 0
        if rng.random() < float(cfg.get("bundle_pose_prob", 0.85)) and prof.poses:
            # 两阶段分配: 先收集全部可行姿势, 按 hands 升序 (同手数随机) ——
            # 多武器同抽时保证每把先拿"最低手"姿势, 剩余资源才轮到双手姿,
            # 杜绝"第一把双手占满、第二把裸奔"(repro① 病根)。
            fitted = [p for p in prof.poses if p.weight > 0
                      and _pose_fits(p, led)]
            if fitted:
                fitted.sort(key=lambda p: (p.hands, rng.random()))
                pose = fitted[0]
                _commit_ext(pose, host_order, host_cat, picks, led)
                n = len(pose.tags)
        for ex in prof.extras:
            if rng.random() >= float(cfg.get("extra_prob", 0.35)):
                continue
            if not _pose_fits(ex, led):
                continue
            _commit_ext(ex, host_order + 0.5, host_cat, picks, led)
            n += len(ex.tags)
        return n

    def _pose_fits(pose, led: _Ledger) -> bool:
        if not led.budget_ok(pose.hands, pose.gaze, pose.state_slot_keys,
                             pose.comp_groups):
            return False
        for t in pose.tags:
            if _norm(t) in led.used_lower:
                return False
        # 束内自带 implies (库内词, 如 standing): 任一不可用 → 整条束弃
        for imp in pose.implies:
            tid = snap.tag_id(imp)
            if tid is None:
                continue
            if _norm(imp) in led.used_lower:
                continue
            if not tag_ok(tid):
                return False
            if not led.cross_ok(tid):
                return False
            if led.used_groups & snap.group_sets[tid]:
                return False
        return True

    def _commit_ext(pose, host_base_order, host_cat, picks, led: _Ledger) -> None:
        for j, t in enumerate(pose.tags):
            led.used_lower.add(_norm(t))
            led.used_groups |= pose.comp_groups
            picks.append(Pick(None, t, pose.zh or "", 1.0, False, "",
                              host_cat, pose.axis,
                              host_base_order + j * 1e-7,
                              "ext", f"{pose.pid}:{pose.pose_id}", "bundle",
                              hands=pose.hands if j == 0 else 0,
                              gaze=pose.gaze if j == 0 else 0,
                              is_extra=pose.is_extra))
        led.hands += pose.hands
        led.gaze += pose.gaze
        for sv in pose.state_slot_keys:
            k, _, v = sv.partition("=")
            led.states[k] = v
        for imp in pose.implies:
            tid = snap.tag_id(imp)
            if tid is None or _norm(imp) in led.used_lower:
                continue
            if not tag_ok(tid) or led.used_groups & snap.group_sets[tid]:
                continue
            commit_tag(tid, "implied")

    # ---------- 0. 钉选 ----------
    state_tags = state.get("tags") or []
    pinned_sub_count: dict[int, int] = {}
    for t in state_tags:
        if not isinstance(t, dict) or not t.get("pinned"):
            continue
        lo = _norm(t.get("en"))
        tid = snap.en_to_id.get(lo)
        if tid is None or lo in led.used_lower:
            continue
        if not tag_ok(tid):
            continue
        g = str(t.get("gender") or "").strip().lower()
        if gmode == "female" and g == "male":
            continue
        if gmode == "male" and g == "female":
            continue
        commit_tag(tid, "pinned")
        pinned_sub_count[snap.sub_of[tid]] = pinned_sub_count.get(snap.sub_of[tid], 0) + 1
        _host = picks[-1]
        if mount_of_tag.get(tid):
            attach_bundle(tid, _host.order, _host.cat, snap.axis_arr[tid])

    # 旧工作流格式: state["pinned"] = 标签原始 id 字符串列表
    for pid in (state.get("pinned") or []):
        tid = snap.orig_id_to_int.get(str(pid))
        if tid is None:
            continue
        lo = snap.tag_lower[tid]
        if lo in led.used_lower:
            continue
        if not tag_ok(tid):
            continue
        g = ("female" if snap.gender_flag[tid] == 1
             else "male" if snap.gender_flag[tid] == 2 else "")
        if gmode == "female" and g == "male":
            continue
        if gmode == "male" and g == "female":
            continue
        commit_tag(tid, "pinned")
        pinned_sub_count[snap.sub_of[tid]] = pinned_sub_count.get(snap.sub_of[tid], 0) + 1
        if mount_of_tag.get(tid):
            attach_bundle(tid, picks[-1].order,
                          snap.cat_names[snap.cat_of_sub[snap.sub_of[tid]]],
                          snap.axis_arr[tid])

    # ---------- 池顺序: 轴次序固定 (prop 在 action 前) ----------
    pool_ids = sorted(range(len(snap.sub_names)),
                      key=lambda si: (snap.pool_order[si], si))

    master = state.get("fill_master")
    master = True if master is None else bool(master)

    def _int_or(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    mlo = _int_or(state.get("fill_master_min"), 1)
    mhi = _int_or(state.get("fill_master_max"), 1)
    sub_ranges = state.get("fill_sub_ranges") or {}
    sub_ids_str = snap.sub_ids_str

    pools = snap.pools if nsfw_on else snap.pools_nonsfw
    if gmode == "female":
        base = snap.pools_nomale
        pools = base if nsfw_on else {si: [i for i in lst if not snap.nsfw_flag[i]]
                                      for si, lst in base.items()}
    elif gmode == "male":
        base = snap.pools_nofemale
        pools = base if nsfw_on else {si: [i for i in lst if not snap.nsfw_flag[i]]
                                      for si, lst in base.items()}

    search_l = search_text.strip().lower()
    bundled_only = snap.bundled_only

    def tag_match(lo: str, tid: int) -> bool:
        if not search_l:
            return True
        if search_l in lo or search_l in snap.tag_zh[tid].lower():
            return True
        for a in (snap.tag_aliases[tid] or ()):
            if search_l in a.lower():
                return True
        return False

    def cat_weight(cname: str) -> float:
        if not cat_weights:
            return 1.0
        return max(float(cat_weights.get(cname, 1.0) or 0.001), 0.001)

    # ---------- 1+2. 逐池抽取 (prop 池抽完立即配束) ----------
    stats = {"bundle_attached": 0, "dropped_mutex": 0, "dropped_resource": 0}
    for si in pool_ids:
        cname = snap.cat_names[snap.cat_of_sub[si]]
        if cname in excl_cats or snap.sub_keys[si] in excl_keys:
            continue
        if master:
            mn, mx = min(mlo, mhi), max(mlo, mhi)
        else:
            r = (sub_ranges.get(sub_ids_str[si]) or {})
            a = _int_or(r.get("min"), 1)
            b = _int_or(r.get("max"), 1)
            mn, mx = min(a, b), max(a, b)
        if si in pinned_sub_count:
            used_n = pinned_sub_count[si]
            mn, mx = max(0, mn - used_n), max(0, mx - used_n)
        if mx <= 0:
            continue
        want = rng.randint(mn, mx)

        cands = []
        for tid in pools.get(si, ()):
            lo = snap.tag_lower[tid]
            if lo in led.used_lower or tid in led.used_ids:
                continue
            if bundled_only and tid in bundled_only:
                continue  # 束专属词: 只能经武器档案出生, 池中永不自抽
            if not tag_match(lo, tid):
                continue
            w = (snap.base_weights[tid] * snap.spawn_rate[tid]
                 * snap.priority_factor[tid] * cat_weight(cname))
            if w <= 0.0001:
                continue
            cands.append((rng.random() ** (1.0 / max(w, 1e-6)), tid))
        cands.sort(reverse=True)

        got = 0
        for _key, tid in cands:
            if got >= want:
                break
            if led.used_ids.__contains__(tid):
                continue
            lo = snap.tag_lower[tid]
            if lo in led.used_lower:
                continue
            if avoid_conflicts:
                if led.used_groups & snap.group_sets[tid]:
                    stats["dropped_mutex"] += 1
                    if len(dropped) < 24:
                        dropped.append(tid)
                    continue
                if not led.cross_ok(tid):
                    stats["dropped_mutex"] += 1
                    if len(dropped) < 24:
                        dropped.append(tid)
                    continue
            commit_tag(tid)
            got += 1
            if mount_of_tag.get(tid):
                n = attach_bundle(tid, picks[-1].order, cname,
                                  snap.axis_arr[tid])
                if n:
                    stats["bundle_attached"] += 1
        # 池内无候选可满足配额时静默少出 (不硬凑)

    # ---------- 3. 输出排序: 轴次序, 束成员紧贴挂载词 ----------
    picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    total_max = cfg.get("total_max")
    if total_max:
        try:
            tmax = int(total_max)
        except (TypeError, ValueError):
            tmax = 0
        if tmax and len(picks) > tmax:
            keep = [p for p in picks if p.source in ("pinned", "bundle", "implied")]
            rest = [p for p in picks if p.source not in ("pinned", "bundle", "implied")]
            picks = (keep + rest)[:tmax]
            picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    return AutoResult(picks, dropped, stats)
