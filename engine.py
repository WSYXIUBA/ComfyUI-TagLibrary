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
    from . import slotpolicy
except ImportError:  # pragma: no cover
    from profiles import BODY_RESOURCES
    import slotpolicy

MAX_REROLL = 3
DEFAULT_CONFIG = {"total_min": 40, "total_max": 60, "bundle_pose_prob": 0.85,
                  "extra_prob": 0.35}

# count 轴"混合宣言词": 出现即锁 mixed (=3), 两性都放行且不再被单词重锁。
# 这是词义 (danbooru 复合人数词固定那几个), 不是冲突规则。
MIXED_COUNT_WORDS = frozenset({"couple", "1boy and 1girl",
                               "mismatched couple", "interspecies couple",
                               "female and male", "girl and boy"})


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
    for k in ("bundle_pose_prob", "extra_prob", "total_max", "max_weapons"):
        if state.get(k) is not None:
            cfg[k] = state[k]
    return cfg


class _Ledger:
    """单次抽取的账本: 用过的词/组名/资源/状态槽 + 增量违禁集。"""

    __slots__ = ("used_lower", "used_groups", "hands", "gaze", "states",
                 "used_ids", "banned_ids", "prop_count", "gender_lock", "props_lib")

    def __init__(self):
        self.used_lower: set[str] = set()
        self.used_groups: set[str] = set()
        self.hands = 0
        self.gaze = 0
        self.states: dict[str, str] = {}   # slot -> value
        self.used_ids: set[int] = set()
        self.banned_ids: set[int] = set()  # cross_banned 增量并集
        self.prop_count = 0                # 已出生的武器档案身份词数
        self.props_lib = 0                 # prop 轴库内词总数 (max_props_total 上限用)
        self.gender_lock = 0               # 0=未锁 1=女 2=男 (count 轴推导)

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


def _lib_key(x) -> str:
    """库内查表用的键 —— 去掉 artist 的 `@` 前缀 (库内存的是裸名)。"""
    return str(x or "").strip().lower().lstrip("@")


def _artist_text(text: str, axis: str) -> str:
    """Anima 官方: artist 必须带 `@` 前缀, 否则效果很弱。库内存裸名, 输出时补前缀。"""
    t = str(text or "").strip()
    if axis == "artist" and t and not t.startswith("@"):
        return "@" + t
    return t


# S4 分类重构前的 9 个大类名 → 现在对应的轴 (md 目录名)。
# 注意"人物主体"跨 5 条轴, 整类排除只能展开成逐轴排除。
_OLD_CAT_TO_AXES_ZH: dict[str, tuple[str, ...]] = {
    "画质规格": ("画质规格",),
    "服装系统": ("服装",),
    "姿势动作": ("动作姿态",),
    "构图镜头": ("构图镜头",),
    "光影氛围": ("光影氛围",),
    "场景环境": ("场景环境",),
    "风格媒介": ("风格媒介",),
    "材质特效": ("材质特效",),
    "人物主体": ("人数", "角色身份", "外貌特征", "服装", "道具武器"),
}


def _migrate_excludes(raw, snap) -> list[str]:
    """把旧工作流里存的「大类[/子类]」排除路径迁到新的「轴/槽位」路径 (幂等)。

    S4 重构后第一级从大类换成了轴名, 旧路径在 `tag_ok` 里永远匹配不上 ——
    表现为"排除了却照样抽"。这里在读取时一次性转换, 避免用户重开工作流才发现。
    """
    if not raw:
        return []
    # 槽位名 → 轴名 (由当前快照反查, 不写死)
    slot_axis: dict[str, str] = {}
    for si, sname in enumerate(snap.sub_names):
        ci = snap.cat_of_sub[si]
        slot_axis.setdefault(sname, snap.cat_names[ci])
    out: list[str] = []
    for e in raw:
        e = str(e)
        parts = e.split("/")
        if len(parts) >= 2:
            ax = slot_axis.get(parts[1])
            out.append("/".join([ax] + parts[1:]) if ax else e)
        else:
            out.extend(_OLD_CAT_TO_AXES_ZH.get(parts[0], (parts[0],)))
    return list(dict.fromkeys(out))


def _trim_to_budget(picks: list, tmax: int, snap, *, protect_nsfw=False) -> list:
    """按**槽位贡献数**从多到少削词, 直到落进总预算。

    不能做朴素截断 (`(keep + rest)[:tmax]`): `rest` 是按轴序排的, 靠后的
    style / material / camera 会被**系统性砍光** —— 修一个缺陷引入另一个。
    这里改为按槽位削, 并保证每个槽位不少于其配额下限; pinned/bundle/implied 永不削。
    protect_nsfw (纯欲档): nsfw 词也免削 —— 否则配额加成放出来的涩词
    会被"按槽位贡献数从多到少削"第一时间砍回去 (实测 6.4 被削回 5.5)。
    """
    fixed_sources = ("pinned", "bundle", "implied")
    fixed = [p for p in picks if p.source in fixed_sources
             or (protect_nsfw and p.nsfw)]
    free = [p for p in picks if p not in fixed]
    room = max(0, tmax - len(fixed))
    if len(free) <= room:
        return picks

    by_slot: dict[int, list] = {}
    for p in free:
        si = snap.sub_of[p.id] if p.id is not None else -1
        by_slot.setdefault(si, []).append(p)

    drop: set[int] = set()
    need = len(free) - room
    for si in sorted(by_slot, key=lambda k: -len(by_slot[k])):
        if need <= 0:
            break
        lst = by_slot[si]
        keep_min = 0 if si < 0 else slotpolicy.caps_for(snap.sub_keys[si])[0]  # min_n
        for p in lst[keep_min:]:
            if need <= 0:
                break
            drop.add(id(p))
            need -= 1
    return [p for p in picks if id(p) not in drop]


class _Extraction:
    """一次抽取的全部状态与步骤 (从 run_auto 的闭包群提取, 行为不变)。

    为什么提取: 12 个闭包挤在一个 527 行的函数里, 读的人要同时在脑子里
    维护 30 多个自由变量; 提取后它们成了实例字段, 状态边界一眼可见。
    早期状态走构造函数, 后算出来的 (池顺序/配额/统计) 由 run_auto 在算出来的
    位置交回 —— 方法里读的是 self.*, 所以别在 run_auto 里改这些局部变量。
    """

    def __init__(
        self, avoid_conflicts, bg_simple, cat_weights, cfg, cross_banned, dropped, excl_cats,
        excl_keys, explicit_extra, focus_portrait, gmode, led, max_prop, max_props_total,
        minor_age, minor_block_words, mount_of_tag, nsfw_factor, nsfw_intensity, nsfw_on,
        picks, pin_force, pinned_tids, rng, snap, solo_lock,
    ) -> None:
        self.avoid_conflicts = avoid_conflicts
        self.bg_simple = bg_simple
        self.cat_weights = cat_weights
        self.cfg = cfg
        self.cross_banned = cross_banned
        self.dropped = dropped
        self.excl_cats = excl_cats
        self.excl_keys = excl_keys
        self.explicit_extra = explicit_extra
        self.focus_portrait = focus_portrait
        self.gmode = gmode
        self.led = led
        self.max_prop = max_prop
        self.max_props_total = max_props_total
        self.minor_age = minor_age
        self.minor_block_words = minor_block_words
        self.mount_of_tag = mount_of_tag
        self.nsfw_factor = nsfw_factor
        self.nsfw_intensity = nsfw_intensity
        self.nsfw_on = nsfw_on
        self.picks = picks
        self.pin_force = pin_force
        self.pinned_tids = pinned_tids
        self.rng = rng
        self.snap = snap
        self.solo_lock = solo_lock

        # 后算出来的状态 (run_auto 在算出来之后赋值)
        self.bundled_only = None
        self.count_no_human = None
        self.count_single = None
        self.excl_used = None
        self.master = None
        self.minor_age = None
        self.pools = None
        self.search_l = None
        self.slot_filled = None
        self.stats = None
        self.sub_ids_str = None
        self.sub_ranges = None

    def tag_ok(self, tid: int) -> bool:
        """排除/NSFW/性别三态/性别锁/未成年锁 五闸门 (候选级)。"""
        if not self.nsfw_on and self.snap.nsfw_flag[tid]:
            return False
        # 纯欲档: 未成年年龄词源头排除 (否则未成年锁触发后整场显式词全灭)
        if self.nsfw_intensity >= 2 and self.snap.tag_lower[tid] in slotpolicy.MINOR_AGE_WORDS:
            return False
        # NSFW 开启时 teen 系模糊年龄词源头排除 (年龄歧义, 成人场景不碰)
        if self.nsfw_on and self.snap.tag_lower[tid] in slotpolicy.TEEN_AGE_WORDS:
            return False
        if self.minor_age and (self.snap.tag_lower[tid] in self.minor_block_words):
            return False
        g = self.snap.gender_flag[tid]
        if self.gmode == "female" and g == 2:
            return False
        if self.gmode == "male" and g == 1:
            return False
        if self.led.gender_lock == 1 and g == 2:
            return False
        if self.led.gender_lock == 2 and g == 1:
            return False
        si = self.snap.sub_of[tid]
        cname = self.snap.cat_names[self.snap.cat_of_sub[si]]
        if cname in self.excl_cats or self.snap.sub_keys[si] in self.excl_keys:
            return False
        # ---- 场景条闸门 (1.8.1) ----
        _sk = self.snap.sub_keys[si]
        if self.solo_lock:
            if self.snap.axis_arr[tid] == "count"                     and self.snap.tag_lower[tid] not in slotpolicy.SINGLE_COUNT_WORDS:
                return False
            if _sk == "动作姿态/互动与双人":
                return False
            _lo = self.snap.tag_lower[tid]
            # 隐含多人的行为词一并封禁 (1other + gangbang 实测漏网)
            if _lo in slotpolicy.SOLO_BAN_WORDS:
                return False
            # 需要搭档的词 —— 原来只封了 互动与双人 槽, 体位/性行为/体液槽里的双人词
            # 全漏: solo + reverse cowgirl position + grabbing another's ass 真机出 1boy+1girl。
            if _lo in slotpolicy.SOLO_PARTNER_WORDS:
                return False
            if any(h in _lo for h in slotpolicy.SOLO_PARTNER_SUBSTR):
                return False
        if self.bg_simple:
            if _sk in slotpolicy.SIMPLE_BG_BAN_SLOTS:
                return False
            lo_bg = self.snap.tag_lower[tid]
            # 背景处理槽按**词**白名单判, 不按槽判 —— 同名 en 可能挂在别的槽下
            # (库里 4700+ 重复; "detailed background" 同时属于 画质规格/细节强化),
            # 按槽判时那一份副本能绕过闸门, 于是同框出现 simple + detailed background。
            if lo_bg in self.snap.bg_slot_words and lo_bg not in slotpolicy.SIMPLE_BG_WORDS:
                return False
            # 别的槽里会摆出一个具体环境的词 (candlelit room / looking out window ...)
            if lo_bg in slotpolicy.SIMPLE_BG_ENV_BAN_WORDS:
                return False
        # 人数轴锚点: 非 booru 自造词模型读不懂, 单人锁下它会顶掉 1girl/solo
        # (原成员 "0others" 已在 1.13.2 词库对齐中改名为 solo; 表留空兜底)
        if (self.snap.axis_arr[tid] == "count"
                and self.snap.tag_lower[tid] in slotpolicy.COUNT_NO_ANCHOR_WORDS):
            return False
        if self.focus_portrait:
            if _sk in slotpolicy.PORTRAIT_BAN_SLOTS:
                return False
            if _sk == "构图镜头/取景范围"                     and self.snap.tag_lower[tid] not in slotpolicy.PORTRAIT_FRAMING_WORDS:
                return False
        return True

    def make_pick(self, tid: int, source: str = "random") -> Pick:
        si = self.snap.sub_of[tid]
        ci = self.snap.cat_of_sub[si]
        return Pick(tid, _artist_text(self.snap.tag_text[tid], self.snap.axis_arr[tid]),
                    self.snap.tag_zh[tid],
                    self.snap.base_weights[tid], bool(self.snap.nsfw_flag[tid]),
                    ("female" if self.snap.gender_flag[tid] == 1 else
                     "male" if self.snap.gender_flag[tid] == 2 else ""),
                    self.snap.cat_names[ci], self.snap.axis_arr[tid], self.snap.order_arr[tid],
                    "tag", None, source)

    def commit_tag(self, tid: int, source: str = "random") -> Pick:
        p = self.make_pick(tid, source)
        # order = 池基数 + 提交序号: 同池按出生序, 束成员紧贴宿主 (基数差≥1 ≫ 序号增量)
        p.order = self.snap.order_arr[tid] + len(self.picks) * 1e-5
        self.picks.append(p)
        self.led.used_ids.add(tid)
        self.led.used_lower.add(self.snap.tag_lower[tid])
        self.led.used_groups |= self.snap.group_sets[tid]
        if self.cross_banned:
            b = self.cross_banned.get(tid)
            if b:
                self.led.banned_ids |= b
        # 性别宣言: 带性别标记的词立锁; 混合人数词 (couple 等) = 锁成 mixed(3),
        # 两性放行。count 池先抽天然优先, character 轴词同样锁场。
        gf = self.snap.gender_flag[tid]
        if self.snap.axis_arr[tid] == "count" and self.snap.tag_lower[tid] in MIXED_COUNT_WORDS:
            gf = 3
        if gf and self.led.gender_lock == 0 and self.snap.axis_arr[tid] in ("count", "character", "appearance"):
            self.led.gender_lock = gf
        return p

    def attach_bundle(self, host_tid: int, host_order: int, host_cat: str,
                      host_axis: str) -> int:
        """给身份词配一条姿势束 + 按概率配件。返回束内 tag 数。"""
        profs = self.mount_of_tag.get(host_tid)
        if not profs:
            return 0
        if self.led.prop_count >= self.max_prop:
            return 0
        self.led.prop_count += 1
        prof = profs[0]
        n = 0
        if self.rng.random() < float(self.cfg.get("bundle_pose_prob", 0.85)) and prof.poses:
            # 两阶段分配: 先收集全部可行姿势, 按 hands 升序 (同手数随机) ——
            # 多武器同抽时保证每把先拿"最低手"姿势, 剩余资源才轮到双手姿,
            # 杜绝"第一把双手占满、第二把裸奔"(repro① 病根)。
            fitted = [p for p in prof.poses if p.weight > 0
                      and self._pose_fits(p, self.led)]
            if fitted:
                fitted.sort(key=lambda p: (p.hands, self.rng.random()))
                pose = fitted[0]
                self._commit_ext(pose, host_order, host_cat, self.picks, self.led)
                n = len(pose.tags)
        for ex in prof.extras:
            if self.rng.random() >= float(self.cfg.get("extra_prob", 0.35)):
                continue
            if not self._pose_fits(ex, self.led):
                continue
            self._commit_ext(ex, host_order + 0.5, host_cat, self.picks, self.led)
            n += len(ex.tags)
        return n

    def _pose_fits(self, pose, led: _Ledger) -> bool:
        if not self.led.budget_ok(pose.hands, pose.gaze, pose.state_slot_keys,
                             pose.comp_groups):
            return False
        for t in pose.tags:
            if _norm(t) in self.led.used_lower:
                return False
        # 束内自带 implies (库内词, 如 standing): 任一不可用 → 整条束弃
        for imp in pose.implies:
            tid = self.snap.tag_id(imp)
            if tid is None:
                continue
            if _norm(imp) in self.led.used_lower:
                continue
            if not self.tag_ok(tid):
                return False
            if not self.led.cross_ok(tid):
                return False
            if self.led.used_groups & self.snap.group_sets[tid]:
                return False
        return True

    def _commit_ext(self, pose, host_base_order, host_cat, picks, led: _Ledger) -> None:
        for j, t in enumerate(pose.tags):
            self.led.used_lower.add(_norm(t))
            self.led.used_groups |= pose.comp_groups
            # 词不在库内时 (ext 词) comp_groups 里没有 grouprules 域 — 按词补查
            eg = self.snap.en_groups.get(_norm(t))
            if eg:
                self.led.used_groups |= eg
            self.picks.append(Pick(None, t, pose.zh or "", 1.0, False, "",
                              host_cat, pose.axis,
                              host_base_order + j * 1e-7,
                              "ext", f"{pose.pid}:{pose.pose_id}", "bundle",
                              hands=pose.hands if j == 0 else 0,
                              gaze=pose.gaze if j == 0 else 0,
                              is_extra=pose.is_extra))
        self.led.hands += pose.hands
        self.led.gaze += pose.gaze
        for sv in pose.state_slot_keys:
            k, _, v = sv.partition("=")
            self.led.states[k] = v
        for imp in pose.implies:
            tid = self.snap.tag_id(imp)
            if tid is None or _norm(imp) in self.led.used_lower:
                continue
            if not self.tag_ok(tid) or self.led.used_groups & self.snap.group_sets[tid]:
                continue
            self.commit_tag(tid, "implied")

    def _pin_collect(self, tid: int) -> None:
        if tid is None:
            return
        lo = self.snap.tag_lower[tid]
        if lo in self.led.used_lower or tid in self.led.used_ids:
            return
        if self.pin_force:
            # 重摇钉入: 过 NSFW/未成年/性别闸门, 豁免排除类目
            if not self.nsfw_on and self.snap.nsfw_flag[tid]:
                return
            if self.nsfw_intensity >= 2 and lo in slotpolicy.MINOR_AGE_WORDS:
                return
            if self.minor_age and lo in self.minor_block_words:
                return
            g = self.snap.gender_flag[tid]
            if self.gmode == "female" and g == 2:
                return
            if self.gmode == "male" and g == 1:
                return
            if self.led.gender_lock == 1 and g == 2:
                return
            if self.led.gender_lock == 2 and g == 1:
                return
        elif not self.tag_ok(tid):
            return
        if tid not in self.pinned_tids:
            self.pinned_tids.append(tid)

    def _int_or(self, val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def tag_match(self, lo: str, tid: int) -> bool:
        if not self.search_l:
            return True
        if self.search_l in lo or self.search_l in self.snap.tag_zh[tid].lower():
            return True
        for a in (self.snap.tag_aliases[tid] or ()):
            if self.search_l in a.lower():
                return True
        return False

    def cat_weight(self, cname: str) -> float:
        if not self.cat_weights:
            return 1.0
        return max(float(self.cat_weights.get(cname, 1.0) or 0.001), 0.001)

    def _slot_available(self, si: int) -> tuple:
        """该槽位此刻能否抽 + 剩余容量 (已考虑 排除/互斥槽位组/人数语义/配额)。"""
        sub_key = self.snap.sub_keys[si]
        cname = self.snap.cat_names[self.snap.cat_of_sub[si]]
        if cname in self.excl_cats or sub_key in self.excl_keys:
            return False, 0
        if slotpolicy.exclusive_group(sub_key) in self.excl_used:
            return False, 0          # 互斥槽位组: 同组已有槽位出过词
        if self.count_single is True and sub_key in slotpolicy.MULTI_ONLY_SLOTS:
            return False, 0          # 单人场景不抽"仅多人成立"的槽位
        if self.count_no_human and self.snap.pool_axis.get(si) in slotpolicy.NO_HUMAN_SKIP_AXES:
            return False, 0          # "画面里没有人" -> 不抽身份/外貌/服装
        # 词 -> 槽位屏蔽: 已抽到 "bare feet" 就不再抽鞋子槽 (跨槽位的矛盾, 配额拦不住)
        for w, bad_slots in slotpolicy.BLOCK_SLOTS_BY_WORD.items():
            if sub_key in bad_slots and w in self.led.used_lower:
                return False, 0
        if self.master:
            cap = slotpolicy.caps_for(sub_key)[1]      # max_n
            if self.nsfw_intensity >= 2:
                cap += slotpolicy.nsfw_boost(sub_key)  # 纯欲档: NSFW 槽位配额加成
        else:
            r = (self.sub_ranges.get(self.sub_ids_str[si]) or {})
            cap = max(self._int_or(r.get("min"), 1), self._int_or(r.get("max"), 1))
        return (cap - self.slot_filled.get(si, 0)) > 0, max(cap - self.slot_filled.get(si, 0), 0)

    def _pool_fill(self, si: int, want: int) -> int:
        """从槽位 si 抽至多 want 个词, 返回实际抽出数。两遍共用。"""

        sub_key = self.snap.sub_keys[si]
        cname = self.snap.cat_names[self.snap.cat_of_sub[si]]
        excl_gid = slotpolicy.exclusive_group(sub_key)
        cands = []
        for tid in self.pools.get(si, ()):
            lo = self.snap.tag_lower[tid]
            if lo in self.led.used_lower or tid in self.led.used_ids:
                continue
            if self.bundled_only and tid in self.bundled_only:
                continue  # 束专属词: 只能经武器档案出生, 池中永不自抽
            # 槽位 -> 词 屏蔽 (反向): 鞋子槽已出词就不再抽 "bare feet" / "barefoot"
            _bw = slotpolicy.BLOCK_WORDS_BY_SLOT.get(sub_key)
            if _bw and lo in _bw:
                continue
            if not self.tag_ok(tid):
                continue  # 动态闸门: 性别锁 (count 词入账后生效)
            if not self.tag_match(lo, tid):
                continue
            # 词级双手预算 (1.8.0): 乳交=2 / 手交·指交=1 —— 手已被武器/姿势占满时
            # 这类词不再出生, 与档案束共用同一本手账
            _hcost = self.snap.hands_cost[tid] if tid < len(self.snap.hands_cost) else 0
            if _hcost and self.led.hands + _hcost > BODY_RESOURCES["hands"]:
                continue
            if self.max_props_total > 0 and self.snap.axis_arr[tid] == "prop"                     and self.led.props_lib >= self.max_props_total:
                continue   # 道具总上限: 封闭场景不再堆杂物 (排除武器的束不在此列)
            w = (self.snap.base_weights[tid] * self.snap.spawn_rate[tid]
                 * self.snap.priority_factor[tid] * self.cat_weight(cname))
            if self.nsfw_factor > 1.0 and self.snap.nsfw_flag[tid]:
                w *= self.nsfw_factor   # NSFW 强度: 涩词在加权抽样里赢面放大
                if self.explicit_extra > 1.0 and self.snap.explicit_flag[tid]:
                    w *= self.explicit_extra   # 行为/解剖级词再乘一层 (防 mild 词稀释)
            if w <= 0.0001:
                continue
            cands.append((self.rng.random() ** (1.0 / max(w, 1e-6)), tid))
        cands.sort(reverse=True)

        got = 0
        for _key, tid in cands:
            if got >= want:
                break
            if tid in self.led.used_ids:
                continue
            lo = self.snap.tag_lower[tid]
            if lo in self.led.used_lower:
                continue
            # 词级双手预算 (1.8.0) —— 必须在提交时复查: 候选收集阶段的账本值
            # 是池启动前的快照, 同池先提交的词会改变剩余手数
            _hcost = self.snap.hands_cost[tid] if tid < len(self.snap.hands_cost) else 0
            if _hcost and self.led.hands + _hcost > BODY_RESOURCES["hands"]:
                continue
            # 道具总上限: 提交时复查 (同手账本, 候选期值过期)
            if self.max_props_total > 0 and self.snap.axis_arr[tid] == "prop"                     and self.led.props_lib >= self.max_props_total:
                continue
            if self.avoid_conflicts:
                if self.led.used_groups & self.snap.group_sets[tid]:
                    self.stats["dropped_mutex"] += 1
                    if len(self.dropped) < 24:
                        self.dropped.append(tid)
                    continue
                if not self.led.cross_ok(tid):
                    self.stats["dropped_mutex"] += 1
                    if len(self.dropped) < 24:
                        self.dropped.append(tid)
                    continue
            self.commit_tag(tid)
            got += 1
            if self.snap.axis_arr[tid] == "prop":
                self.led.props_lib += 1
            if _hcost:
                self.led.hands += _hcost
            if excl_gid:
                self.excl_used.add(excl_gid)
            if self.snap.axis_arr[tid] == "count":
                _low = self.snap.tag_lower[tid]
                if _low in slotpolicy.SINGLE_COUNT_WORDS:
                    self.count_single = True
                elif _low in slotpolicy.MULTI_COUNT_WORDS:
                    self.count_single = False
                if _low in slotpolicy.NO_HUMAN_COUNT_WORDS:
                    self.count_no_human = True
            if self.snap.tag_lower[tid] in slotpolicy.MINOR_AGE_WORDS:
                self.minor_age = True
            if self.mount_of_tag.get(tid):
                n = self.attach_bundle(tid, self.picks[-1].order, cname, self.snap.axis_arr[tid])
                if n:
                    self.stats["bundle_attached"] += 1
            self.slot_filled[si] = self.slot_filled.get(si, 0) + 1
        return got

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
    for e in _migrate_excludes(state.get("exclude_categories"), snap):
        (excl_keys if "/" in e else excl_cats).add(e)

    gmode = str(state.get("gender") or "off").strip().lower()

    # 1.8.0 纯欲档: 排除动物伙伴槽 —— 动物↔性行为跨池规则是双向的, 抽到猫狗
    # 会把全部行为词封锁掉 (实测 ~25% 条目显式词归零); 纯欲场景不要宠物。
    if int(state.get("nsfw_intensity") or 0) >= 2             and "道具武器/动物伙伴" not in {str(e) for e in (state.get("exclude_categories") or [])}:
        state = {**state, "exclude_categories":
                 list(state.get("exclude_categories") or []) + ["道具武器/动物伙伴"]}

    # NSFW 强度 (1.8.0): 0=标准 1=强调 2=纯欲 —— nsfw 词的抽样权重乘数。
    # 实测标准档 NSFW 词仅 ~5% 池占比, 显式内容出词率 ~15%; 纯欲档拉到主导。
    _NSFW_INTENSITY_FACTOR = {0: 1.0, 1: 2.5, 2: 6.0}
    _NSFW_EXPLICIT_EXTRA = {0: 1.0, 1: 2.0, 2: 2.5}   # 显式档 (explicit 字段) 再乘
    try:
        nsfw_intensity = int(state.get("nsfw_intensity") or 0)
    except (TypeError, ValueError):
        nsfw_intensity = 0
    nsfw_factor = _NSFW_INTENSITY_FACTOR.get(nsfw_intensity, 1.0)
    explicit_extra = _NSFW_EXPLICIT_EXTRA.get(nsfw_intensity, 1.0)

    # 1.8.0: 未成年屏蔽词 = 出厂人工表 ∪ 扩展包 minor_block 词 (快照编译期并集)
    minor_block_words = getattr(snap, "minor_block_words", None) or slotpolicy.MINOR_BLOCK_WORDS
    # 1.8.0 分轴重摇: pin_ignore_exclude=true 时钉选词只过 NSFW/性别/未成年闸门,
    # 不受排除类目约束 (重摇轴 X 时, 其余轴的保留词经"排除其余轴"钉入)
    pin_force = bool(state.get("pin_ignore_exclude"))
    # 1.8.1 道具总上限 (场景类预设用): prop 轴库内词最多出 N 个, 0 = 不限。
    # 浴室/卧室这类封闭场景抽 8 个道具是杂物灾难 (真机审看实测), 预设携带此键。
    try:
        max_props_total = int(state.get("max_props_total") or 0)
    except (TypeError, ValueError):
        max_props_total = 0
    # 1.8.1 场景条三开关 (面板常亮按钮, 状态存 selection_state, 引擎权威生效):
    #   solo_lock  👤单人锁: 人数轴只许单词, 互动与双人槽封禁
    #   bg_mode=simple  🖼简洁背景: 具象场景槽封禁, 背景处理槽白名单过滤
    #   focus_mode=portrait  🎯人物特写: 杂物道具槽封禁, 取景范围白名单过滤
    solo_lock = bool(state.get("solo_lock"))
    bg_simple = str(state.get("bg_mode") or "normal") == "simple"
    focus_portrait = str(state.get("focus_mode") or "normal") == "portrait"

    # 未成年锁定: 任一年龄词出生后, 成人向词在候选级全池屏蔽 (词级黑名单,
    # 覆盖裸露/内衣/泳装/体型/表情等 9 个槽位, 见 slotpolicy.MINOR_*)。
    # 必须在 tag_ok 定义前赋值 —— 钉选阶段就会调 tag_ok。
    minor_age = False




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




    # ---------- 0. 钉选 ----------
    # 两代格式汇成一表, count 轴钉选先入账 (性别宣言先锁场再抽其余)
    pinned_tids: list[int] = []
    # 闭包群已提取成 _Extraction: 早期状态走构造函数, 后算出来的状态在下面交回
    ex = _Extraction(avoid_conflicts, bg_simple, cat_weights, cfg, cross_banned, dropped, excl_cats, excl_keys, explicit_extra, focus_portrait, gmode, led, max_prop, max_props_total, minor_age, minor_block_words, mount_of_tag, nsfw_factor, nsfw_intensity, nsfw_on, picks, pin_force, pinned_tids, rng, snap, solo_lock)

    pinned_sub_count: dict[int, int] = {}


    for t in (state.get("tags") or []):
        if not isinstance(t, dict) or not t.get("pinned"):
            continue
        ex._pin_collect(snap.en_to_id.get(_lib_key(t.get("en"))))
    for pid in (state.get("pinned") or []):
        ex._pin_collect(snap.orig_id_to_int.get(str(pid)))
    pinned_tids.sort(key=lambda tid: 0 if snap.axis_arr[tid] == "count" else 1)
    for tid in pinned_tids:
        ex.commit_tag(tid, "pinned")
        pinned_sub_count[snap.sub_of[tid]] = pinned_sub_count.get(snap.sub_of[tid], 0) + 1
        if mount_of_tag.get(tid):
            ex.attach_bundle(tid, picks[-1].order,
                          snap.cat_names[snap.cat_of_sub[snap.sub_of[tid]]],
                          snap.axis_arr[tid])

    # ---------- 池顺序: 轴次序固定 (prop 在 action 前) ----------
    pool_ids = sorted(range(len(snap.sub_names)),
                      key=lambda si: (snap.pool_order[si], si))

    master = state.get("fill_master")
    master = True if master is None else bool(master)


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



    # ---------- 1+2. 逐池抽取 (prop 池抽完立即配束) ----------
    stats = {"bundle_attached": 0, "dropped_mutex": 0, "dropped_resource": 0}

    # 槽位配额 / 互斥槽位组 / 人数语义 —— 见 slotpolicy.py 模块头部的实测说明。
    # 钉选词已入账, 先据此判定人数语义 (单人场景不该抽"互动与双人")。
    excl_used: set[str] = set()
    count_single: bool | None = None
    count_no_human = False
    for _p in picks:
        _low = _norm(_p.en)
        if _low in slotpolicy.SINGLE_COUNT_WORDS:
            count_single = True
        elif _low in slotpolicy.MULTI_COUNT_WORDS:
            count_single = False
        if _low in slotpolicy.NO_HUMAN_COUNT_WORDS:
            count_no_human = True
        if _low in slotpolicy.MINOR_AGE_WORDS:
            minor_age = True

    slot_filled: dict[int, int] = {si: pinned_sub_count.get(si, 0) for si in pool_ids}

    # 后算出来的状态交回实例 (方法里读 self.*)
    ex.bundled_only = bundled_only
    ex.count_no_human = count_no_human
    ex.count_single = count_single
    ex.excl_used = excl_used
    ex.master = master
    ex.minor_age = minor_age
    ex.pools = pools
    ex.search_l = search_l
    ex.slot_filled = slot_filled
    ex.stats = stats
    ex.sub_ids_str = sub_ids_str
    ex.sub_ranges = sub_ranges



    # ---- 第 1 遍: 按逐槽位配额抽 (取代原先"每槽位都抽 mlo~mhi 个") ----
    for si in pool_ids:
        ok, room = ex._slot_available(si)
        if not ok:
            continue
        sub_key = snap.sub_keys[si]
        if master:
            mn, mx = slotpolicy.caps_for(sub_key)      # (min_n, max_n)
            if nsfw_intensity >= 2:
                mx += slotpolicy.nsfw_boost(sub_key)
                mn += slotpolicy.nsfw_min_boost(sub_key)   # 保底: 性行为/服装状态至少 1
        else:
            r = (sub_ranges.get(sub_ids_str[si]) or {})
            a = ex._int_or(r.get("min"), 1)
            b = ex._int_or(r.get("max"), 1)
            mn, mx = min(a, b), max(a, b)
        used_n = pinned_sub_count.get(si, 0)
        mn, mx = max(0, mn - used_n), max(0, mx - used_n)
        mx = min(mx, room)
        if mx <= 0:
            continue
        lo_, hi_ = min(mn, mx), max(mn, mx)
        # 偏向配额上限: 逐槽位全取 randint 会让总量偏低 (实测均值 36 词),
        # 多数情况直接取满, 落进目标带。
        want = hi_ if (hi_ > lo_ and rng.random() < 0.65) else rng.randint(lo_, hi_)
        ex._pool_fill(si, want)

    # ---- 第 2 遍 (补底): 总量不足 total_min 时, 从仍有余量的槽位各补 1 个 ----
    # 只补到下限为止, 不改变"哪些槽位能出"的判定 (排除/互斥组/人数语义照旧生效)。
    tmin = ex._int_or(state.get("total_min") or cfg.get("total_min"), 0)
    if tmin and len(picks) < tmin:
        # 多轮补: 单轮每槽只补 1 个, 而部分槽位首轮候选全被互斥/性别闸门挡掉;
        # 再跑一轮时 rng 已推进、已选集合也变了, 能拿到别的候选。
        # 上限 3 轮且"无进展即停" —— 有界, 不会为了凑数硬塞。
        for _round in range(3):
            if len(picks) >= tmin:
                break
            progressed = False
            for si in pool_ids:
                if len(picks) >= tmin:
                    break
                ok, _room = ex._slot_available(si)
                if not ok:
                    continue
                if ex._pool_fill(si, 1):
                    progressed = True
            if not progressed:
                break

    # 池内无候选可满足配额时静默少出 (不硬凑)

    # ---------- 3. 输出排序: 轴次序, 束成员紧贴挂载词 ----------
    picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    total_max = state.get("total_max") or cfg.get("total_max")
    if total_max:
        try:
            tmax = int(total_max)
        except (TypeError, ValueError):
            tmax = 0
        if tmax and len(picks) > tmax:
            picks = _trim_to_budget(picks, tmax, snap,
                                    protect_nsfw=(nsfw_intensity >= 2))
            picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    # ---------- 4.5 单人锁 · 人数锚点补强 ----------
    # 87 张真机出图 (全部单人锁开) 实测: 提示词里是 solo 的 37 张 **3%** 出多人,
    # 是 1girl 的 39 张 **21%** —— 1girl 只声明"一个女孩", 不排除画面里还有别人;
    # 只有 solo 才是"画面里只有一人"。冲突表里本来就写着 "1girl+solo 黄金组合保留",
    # 但引擎每次只抽一个人数词, 从来没同时出过。单人锁下补这一发。
    if solo_lock:
        _words = {p.en.lower() for p in picks}
        if "solo" not in _words and (_words & {"1girl", "1boy"}):
            _solo_tid = snap.en_to_id.get("solo")
            if _solo_tid is not None:
                picks.append(ex.make_pick(_solo_tid, "solo_anchor"))
                picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    # ---------- 4. 未成年锁终检 (词级, 与抽取顺序无关) ----------
    # 闸门本身是"年龄词落位后才封成人词", 顺序反了就漏 —— 实测 nsfw=on / 档位 1
    # 1500 seed 里 12 条年龄词与成人词同框 (child/loli/preteen + bra)。这里按**最终
    # 结果**兜底: 只要年龄词在, 成人向子集一律剔掉, 不看谁先落位。
    if any(p.id is not None and snap.tag_lower[p.id] in slotpolicy.MINOR_AGE_WORDS
           for p in picks):
        picks = [p for p in picks
                 if p.id is None or snap.tag_lower[p.id] not in minor_block_words]

    # ---------- 4.6 人数轴兜底 ----------
    # 上面那道终检是按**词**剔的, 人数词本身也可能被剔掉 —— 只要库里有被标
    # minor_block 的 NSFW 人数词就中招 (实测: "一女一男" 映射成 danbooru 的 hetero 后,
    # 抽到 child 的人数轴被剃光, 提示词里一个"几个人"都没有, 模型就自己编人数)。
    # 只在归零时补一个锚点 (单人锁下补 1girl+solo 黄金组合), 不覆盖正常抽取。
    if picks and not any(p.id is not None and snap.axis_arr[p.id] == "count" for p in picks):
        _fb = ("1girl", "solo") if solo_lock else (
            ("1boy",) if led.gender_lock == 2 else ("1girl",))
        for _w in _fb:
            _tid = snap.en_to_id.get(_w)
            if _tid is not None and _w not in ex.led.used_lower and ex.tag_ok(_tid):
                picks.append(ex.make_pick(_tid, "count_fallback"))
        picks.sort(key=lambda p: (p.order, 0 if p.source == "pinned" else 1))

    # ---------- 4.7 "no humans" 终检 ----------
    # 画面里没有人 -> 不该有身份/外貌/服装词。引擎在抽槽阶段就按槽轴挡, 但**束成员**
    # 的轴走 pose.axis (profiles.py: extras -> "appearance"、姿势 -> "action"),
    # 挡不住: 武器束挂在武器道具上出生 (钉选的 katana 也挂), 与人数词无关, 于是
    # "no humans + sniper scope" 真机出得来。按**最终结果**判, 与抽取顺序无关。
    #
    # 只剔轴落在 NO_HUMAN_SKIP_AXES 的 (即束里的"配件" extras), 保留 "action" 姿势 ——
    # 武器必带姿势束是既有契约 (m1/m2/m4 门禁钉着), 不能为了这条把束整体删掉。
    if any(p.id is not None and snap.tag_lower[p.id] in slotpolicy.NO_HUMAN_COUNT_WORDS
           for p in picks):
        picks = [p for p in picks if p.axis not in slotpolicy.NO_HUMAN_SKIP_AXES]

    return AutoResult(picks, dropped, stats)
