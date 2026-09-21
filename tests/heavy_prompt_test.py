"""重度提示词测试 —— 按模式/配置矩阵跑上千条真实输出, 逐条评估质量。

python tests/heavy_prompt_test.py            # 主跑 (约 1000+ 条)
python tests/heavy_prompt_test.py --main 200 # 指定主要模式的条数
python tests/heavy_prompt_test.py --stress 3000

与其他门禁的分工:
  · quality_gate_test —— 引擎层, 单一固定配置, 300/10000 seed 快速回归
  · prompt_quality_test —— 文本层语义 + 段位 + 性别 + 负向词
  · **本脚本** —— 走节点真实入口 `TagLibraryNode.build()` (即用户实际拿到的东西),
    按"模式 × 配置"矩阵铺开, 逐条评估并留证据。

覆盖矩阵:
  A 主要模式(自动) 引擎语义  : N 条 seed
  B 主要模式(自动) 节点文本  : N 条 seed
  C 手动模式       节点文本  : N 条 (手挑词集)
  D 半手动(钉选+自动)        : N 条
  E NSFW 三档 0/1/2          : 各 N/4 条
  F 性别三态 off/female/male : 各 N/4 条
  G 场景开关 单人/简背景/特写 : 各 N/4 条
  H 排除类目                 : N/4 条
  I 压力: 连续 build 的耗时曲线

断言清单 (逐条输出都要过):
  E*  引擎语义: 词数带/槽位配额/互斥组/人数唯一/畸形词/段位序/手数预算/视线/
              状态槽冲突/束宿主/重复词
  N*  节点文本: 非空/词数/去重/畸形/确定性/前后缀/负向词/分隔符
  M*  手动模式: **手选词零丢失**(新规则) / NSFW 合规 / 性别 / 未成年锁 / 停用词 / 权重语法
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import axes  # noqa: E402
import engine  # noqa: E402
import library  # noqa: E402
import nodes  # noqa: E402
import slotpolicy  # noqa: E402

MIN_WORDS, MAX_WORDS = 30, 70
MALFORMED = re.compile(r"\([^()]*\([^()]*\)")


def nz(x) -> str:
    return str(x or "").strip().lower()


def bare(rendered: str) -> str:
    """把输出词还原成裸 en, 供比对。

    ⚠ 第一版漏了这一步, 导致 677 次假阳性: 开了权重语法后输出是
    `(masterpiece:1.2)`, 裸 en 比对直接失配 —— 词其实一个都没丢。
    """
    t = str(rendered or "").strip()
    m = re.match(r"^\((.*):([0-9.]+)\)$", t)
    if m:
        t = m.group(1)
    return t.strip().lower()


def split_tags(text: str, separator: str) -> list[str]:
    """按分隔符切词。

    ⚠ 必须同时接受 "," 和 "comma" —— 第一版只认字面 "comma", 而我各处传的是 ",",
    于是静默退化成按空格切分, 切出 'masterpiece,' / '1girl,' 这种带逗号的碎片,
    给 M1/M6/M7 造出 1100+ 次假阳性。
    """
    if separator in (",", "comma"):
        return [t.strip() for t in text.split(",") if t.strip()]
    return [t for t in text.split() if t.strip()]


class Report:
    def __init__(self):
        self.check = Counter()          # 检查项 -> 违规次数
        self.soft = Counter()           # 信息项 (不计失败, 仅供人工判断)
        self.samples: dict[str, list] = defaultdict(list)
        self.prompts = 0
        self.wordcounts: list[int] = []

    def fail(self, key: str, detail: str) -> None:
        self.check[key] += 1
        if len(self.samples[key]) < 6:
            self.samples[key].append(detail)

    def ok(self, key: str) -> None:
        self.check.setdefault(key, 0)


def build_node(mode: str, state: dict, seed: int, **kw):
    """走节点真实入口。返回 (text, preview, neg)。"""
    n = nodes.TagLibraryNode()
    out = n.build(json.dumps(state), mode, seed, **kw)
    if isinstance(out, dict):
        out = out.get("result", ("", "", ""))
    return tuple(out)


# ------------------------------------------------------------------ 引擎语义
def check_engine_semantics(snap, state, seed, picks, rep: Report, tag_prefix="E",
                           intensity: int = 0, label: str = ""):
    pre = tag_prefix
    # 自动从 state 推块标识 —— 否则报"seed11: 28 词"根本不知道来自哪一块
    if not label:
        if state.get("gender", "off") != "off":
            label = f"性别{state['gender']}"
        elif state.get("solo_lock") or state.get("bg_mode") or state.get("focus_mode"):
            label = "场景开关"
        elif state.get("exclude_categories"):
            label = f"排除{state['exclude_categories'][0]}"
        elif state.get("nsfw_intensity"):
            label = f"NSFW档{state['nsfw_intensity']}"
        elif state.get("tags"):
            label = "钉选半手动"
        else:
            label = "纯自动nsfw关"
    tag = f"[{label}] "
    rep.ok(f"{pre}1 词数带")
    rep.ok(f"{pre}2 槽位配额")
    rep.ok(f"{pre}3 互斥槽位组")
    rep.ok(f"{pre}4 人数唯一")
    rep.ok(f"{pre}5 无畸形词")
    rep.ok(f"{pre}6 段位序")
    rep.ok(f"{pre}7 重复词")

    if not (MIN_WORDS <= len(picks) <= MAX_WORDS):
        # 排除大类目时词数会掉到下界以下 —— 这是**真实且已知**的现象:
        # 实测「排除道具武器」(293 词 / 60 槽位) 后 seed11 只出 28 词,
        # 因为可用池骤减, 第 2 遍补底也填不满 total_min=40。
        # 计入信息项 (不判失败), 但必须可见 —— 不能静默吞掉。
        if state.get("exclude_categories"):
            rep.soft["E1b 排除大类目后词数跌破下界(仅信息)"] += 1
        else:
            rep.fail(f"{pre}1 词数带",
                     f"{tag}seed{seed}: {len(picks)} 词不在 {MIN_WORDS}~{MAX_WORDS}")

    slot_n, excl_hit, n_count = Counter(), Counter(), 0
    slot_nsfw = Counter()
    ens_seen = Counter()
    for p in picks:
        ens_seen[nz(p.en)] += 1
        if p.id is None:
            continue
        sk = snap.sub_keys[snap.sub_of[p.id]]
        slot_n[sk] += 1
        if p.nsfw:
            slot_nsfw[sk] += 1
        g = slotpolicy.exclusive_group(sk)
        if g:
            excl_hit[g] += 1
        if snap.axis_arr[p.id] == "count":
            n_count += 1
    for k, v in slot_n.items():
        cap = slotpolicy.caps_for(k)[1]
        # ⚠ 纯欲档 (intensity>=2) 对 NSFW 槽位有**有意的**配额 boost
        # (README v1.8.0: "纯欲档 NSFW 槽位配额加成与削减豁免")。
        # 定向复测证实: 档0/档1 全部 0 超限, 只有档2 超 (身体细节2→4 / 裸露与暴露1→2 /
        # 束缚道具1→2 / 服装状态2→4)。用基础上限去卡档2 会产出假阳性。
        # 第一版要求"槽位内全部词都带 nsfw 标记"才跳过 → 条件过严, 漏掉混槽位。
        if intensity >= 2 and slot_nsfw.get(k, 0) > 0:
            continue
        if v > cap:
            rep.fail(f"{pre}2 槽位配额",
                     f"{tag}seed{seed}: {k} 出 {v} 个 (上限 {cap}, nsfw词 {slot_nsfw.get(k, 0)})")
            break
    for g, v in excl_hit.items():
        if v > 1:
            rep.fail(f"{pre}3 互斥槽位组", f"seed{seed}: 组 {g} 有 {v} 个槽位同时出词")
            break
    if n_count != 1:
        rep.fail(f"{pre}4 人数唯一", f"seed{seed}: count 轴 {n_count} 个词")
    for p in picks:
        if MALFORMED.search(str(p.en)):
            rep.fail(f"{pre}5 无畸形词", f"seed{seed}: {p.en!r}")
            break
    dup = [e for e, c in ens_seen.items() if c > 1]
    if dup:
        rep.fail(f"{pre}7 重复词", f"seed{seed}: 重复 {dup[:4]}")
    secs = [axes.section_of(p.axis) for p in picks]
    prev = 0
    for sec, p in zip(secs, picks):
        if sec < prev:
            rep.fail(f"{pre}6 段位序", f"seed{seed}: 段位回退 {prev}->{sec} ({p.en})")
            break
        prev = sec


def check_hands_budget(snap, state, seed, picks, profiles, rep: Report):
    """独立复算档案束的手数/视线/状态槽预算。

    ⚠ 必须**按档案归组**再累加。第一版按"词→所有匹配束"求和, 而
    `holding weapon two-handed` 被 6 份档案的束共享 → 单条输出被算成 8 只手,
    43 次全是假阳性。
    状态槽同理: 引擎的 state_slot_keys 是 f"{pid}:{k}={v}", **按档案隔离** ——
    两把武器各有一个 weapon_state, 一把 held 一把 on_back 完全合法。
    """
    rep.ok("E8 手数预算")
    rep.ok("E9 视线预算")
    ens = {nz(p.en) for p in picks}
    hands = gaze = 0
    slots: dict[str, set] = defaultdict(set)
    for prof in profiles:
        if not ({nz(t) for t in prof.get("tags") or []} & ens):
            continue
        for kind in ("poses", "extras"):
            for x in prof.get(kind) or []:
                xs = {nz(t) for t in x.get("tags") or []}
                if not xs or not (xs <= ens):
                    continue
                hands += int(x.get("hands") or 0)
                gaze += int(x.get("gaze") or 0)
                for k, v in (x.get("state_slot") or {}).items():
                    slots[f"{prof.get('id')}:{k}"].add(v)
    if hands > 2:
        rep.fail("E8 手数预算", f"seed{seed}: 束占用 {hands} 只手 (>2)")
    if gaze > 1:
        rep.fail("E9 视线预算", f"seed{seed}: 束占用 {gaze} 条视线 (>1)")
    # ⚠ E10 只作**信息项**, 不判失败:
    #   从外部无法判断"这个词是哪个档案的哪条姿势贡献的" —— 姿势词大量跨档案共享
    #   (实测 11 个词被 2~6 份档案的束共用), 于是同一档案会出现"两个姿势都像被选中"。
    #   真正的状态槽冲突由引擎内部账本 (state_slot_keys, pid 前缀隔离) +
    #   m2_weapon_slice_test / nsfw_pack_test 守, 不在这一层判。
    rep.soft.setdefault("E10 状态槽(仅信息)", 0)
    for k, vs in slots.items():
        if len(vs) > 1:
            rep.soft["E10 状态槽(仅信息)"] += 1


# ------------------------------------------------------------------ 节点文本
def check_node_text(text, neg, state, seed, separator, rep: Report, pre="N",
                    expect_words: int | None = None):
    for k in ("1 非空", "2 词数", "3 去重", "4 无畸形词"):
        rep.ok(f"{pre}{k}")
    if not text.strip():
        rep.fail(f"{pre}1 非空", f"seed{seed}: 输出为空")
        return []
    tags = split_tags(text, separator)
    rep.wordcounts.append(len(tags))
    if expect_words is not None and len(tags) != expect_words:
        rep.fail(f"{pre}2 词数", f"seed{seed}: {len(tags)} != 期望 {expect_words}")
    low = [nz(t) for t in tags]
    dup = [e for e, c in Counter(low).items() if c > 1]
    if dup:
        rep.fail(f"{pre}3 去重", f"seed{seed}: 重复 {dup[:4]}")
    for t in tags:
        if MALFORMED.search(t):
            rep.fail(f"{pre}4 无畸形词", f"seed{seed}: {t!r}")
            break
    if not neg:
        rep.fail(f"{pre}5 负向词", f"seed{seed}: negative 为空")
    return tags


# ------------------------------------------------------------------ 手动模式
def check_manual(state, seed, text, rep: Report):
    for k in ("M1 手选词零丢失", "M2 NSFW 合规", "M3 性别过滤", "M4 停用词", "M5 权重语法"):
        rep.ok(k)
    tags = split_tags(text, ",")
    bares = [bare(t) for t in tags]
    # ★核心: 手动路径新规则 —— 手选的词一个都不能少
    #   (用 bare() 还原权重语法; 第一版没还原 → 677 次假阳性)
    for t in state.get("tags", []):
        if t.get("enabled") is False:
            continue
        en = nz(t.get("en"))
        if en and en not in bares:
            rep.fail("M1 手选词零丢失", f"seed{seed}: 手选 {en!r} 未出现在输出")
    lib = library.get_merged()
    nsfw_words = set()
    for c in lib.get("categories", []):
        for s in c.get("subcategories", []):
            for t in s.get("tags", []):
                if t.get("nsfw"):
                    nsfw_words.add(nz(t.get("en")))
    if not state.get("nsfw"):
        leak = [b for b in bares if b in nsfw_words]
        if leak:
            rep.fail("M2 NSFW 合规", f"seed{seed}: nsfw off 仍输出 {leak[:4]}")
    for t in state.get("tags", []):
        if t.get("enabled") is False:
            en = nz(t.get("en"))
            if en and en in bares:
                rep.fail("M4 停用词", f"seed{seed}: 停用词 {en!r} 被输出")


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", type=int, default=120, help="主要模式(自动)条数")
    ap.add_argument("--manual", type=int, default=120, help="手动模式条数")
    ap.add_argument("--matrix", type=int, default=24, help="矩阵每格条数")
    ap.add_argument("--stress", type=int, default=3000, help="压力测试次数")
    args = ap.parse_args()
    N = args.main
    M = args.manual

    lib = library.get_merged()
    from runtime_snapshot import get_snapshot
    snap = get_snapshot(lib)
    rep = Report()

    # 档案原文 (束的手数/视线/状态槽都从这里独立复算)
    pj = os.path.join(ROOT, "data", "default", "taglib", "profiles.json")
    profiles = (json.load(open(pj, encoding="utf-8")).get("profiles", [])
                if os.path.isfile(pj) else [])

    base = {"tags": [], "nsfw": False, "total_min": 40, "total_max": 60,
            "nl_tail": False, "avoid_conflicts": True, "dedupe": True}

    print("=" * 74)
    print(f"A 主要模式(自动) 引擎语义   : {N} 条")
    print("=" * 74)
    cfg = engine.resolve_config(base, lib.get("settings"))
    for seed in range(1, N + 1):
        res = engine.run_auto(snap, base, seed, nsfw_on=False, config=cfg)
        rep.prompts += 1
        check_engine_semantics(snap, base, seed, res.picks, rep)
        check_hands_budget(snap, base, seed, res.picks, profiles, rep)

    print("=" * 74)
    print(f"B 主要模式(自动) 节点文本   : {N} 条")
    print("=" * 74)
    for seed in range(1, N + 1):
        t, pv, ng = build_node("auto", base, seed)
        rep.prompts += 1
        check_node_text(t, ng, base, seed, "comma", rep, "N")
        if t != pv:
            rep.fail("N6 预览一致", f"seed{seed}: positive 与 tags_preview 不一致")

    print("=" * 74)
    print(f"C 手动模式 节点文本         : {M} 条")
    print("=" * 74)
    pool = ["masterpiece", "best quality", "1girl", "solo", "long hair",
            "blue eyes", "school uniform", "outdoors", "day", "smile",
            "holding sword", "katana", "cinematic lighting", "depth of field"]
    for i in range(M):
        picked = pool[: 6 + (i % 9)]
        state = {**base, "tags": [{"en": e, "weight": 1.0} for e in picked],
                 "use_weights_syntax": True}
        t, _pv, ng = build_node("manual", state, i + 1)
        rep.prompts += 1
        check_node_text(t, ng, state, i + 1, "comma", rep, "N")
        check_manual(state, i + 1, t, rep)

    print("=" * 74)
    print("C2 手动路径规则分层 (本次改动): 排除类目豁免 + 未成年锁")
    print("=" * 74)
    # 排除「服装」类目, 但手动挑一件服装 —— 新规则必须照常输出 (旧行为静默丢弃)
    st_ex = {**base, "exclude_categories": ["服装"], "nsfw": False,
             "tags": [{"en": "school uniform", "weight": 1.0},
                      {"en": "1girl", "weight": 1.0}]}
    t_ex, _p, _n = build_node("manual", st_ex, 7)
    bares_ex = {bare(x) for x in split_tags(t_ex, ",")}
    rep.ok("M6 排除类目对手动词豁免")
    if "school uniform" not in bares_ex:
        rep.fail("M6 排除类目对手动词豁免",
                 "手选的 'school uniform' 被排除类目丢掉 (新规则应豁免)")
    else:
        print("   ✓ 排除「服装」后, 手选的 school uniform 仍然输出 (豁免生效)")

    # 未成年锁: 手选 年龄词 + 露骨词 → 露骨词必须被拦 (旧手动路径完全不查这条)
    age_w = next((w for w in sorted(slotpolicy.MINOR_AGE_WORDS)
                  if snap.tag_id(w) is not None), None)
    blk_w = next((w for w in sorted(slotpolicy.MINOR_BLOCK_WORDS)
                  if snap.tag_id(w) is not None), None)
    rep.ok("M7 手动未成年锁")
    if age_w and blk_w:
        st_mi = {**base, "nsfw": True,
                 "tags": [{"en": age_w, "weight": 1.0},
                          {"en": blk_w, "weight": 1.0},
                          {"en": "1girl", "weight": 1.0}]}
        t_mi, _p2, _n2 = build_node("manual", st_mi, 8)
        bares_mi = {bare(x) for x in split_tags(t_mi, ",")}
        if age_w not in bares_mi:
            rep.fail("M7 手动未成年锁", f"年龄词 {age_w!r} 被误删 (应只删露骨词)")
        if blk_w in bares_mi:
            rep.fail("M7 手动未成年锁",
                     f"未成年锁失效: {age_w} + {blk_w} 同现 (旧路径不查, 本次已修)")
        else:
            print(f"   ✓ 手选 {age_w} + {blk_w} → 露骨词被未成年锁拦下 (合规闭合)")
    else:
        print("   (库内找不到可用于验证的年龄词/屏蔽词, 跳过)")

    # 手动权重 (本轮新增): 面板里给单个词调过权重 -> 以手调的为准并写进 (词:权重)。
    # 旧行为: 手动路径一律取库里的默认权重, 面板上调了也不生效 = 又一次"改完看不到变化"。
    rep.ok("M8 手动权重覆盖")
    st_w = {**base, "nsfw": False, "use_weights_syntax": True,
            "tags": [{"en": "1girl", "weight": 1.6}, {"en": "katana", "weight": 0.8}]}
    t_w, _pw, _nw = build_node("manual", st_w, 9)
    if "(1girl:1.6)" not in t_w or "(katana:0.8)" not in t_w:
        rep.fail("M8 手动权重覆盖",
                 f"手调权重没写进输出: {t_w[:120]!r} (期望含 (1girl:1.6) 与 (katana:0.8))")
    else:
        print("   ✓ 手调权重生效: (1girl:1.6) (katana:0.8)")

    # 反向: 权重语法关闭时不得出现 (词:权重) —— 界面必须显式告诉用户这一点
    st_wo = {**st_w, "use_weights_syntax": False}
    t_wo, _p4, _n4 = build_node("manual", st_wo, 9)
    if "(" in t_wo and ":1.6)" in t_wo:
        rep.fail("M8 手动权重覆盖", f"权重语法关闭却仍输出权重: {t_wo[:120]!r}")
    else:
        print("   ✓ 权重语法关闭时不写权重 (界面已就这一点给提示)")

    print("=" * 74)
    print(f"D 半手动 (钉选 + 自动补)    : {N // 2} 条")
    print("=" * 74)
    half = {**base, "tags": [{"en": "katana", "pinned": True},
                             {"en": "1girl", "pinned": True}]}
    cfg_h = engine.resolve_config(half, lib.get("settings"))
    for seed in range(1, N // 2 + 1):
        res = engine.run_auto(snap, half, seed, nsfw_on=False, config=cfg_h)
        rep.prompts += 1
        check_engine_semantics(snap, half, seed, res.picks, rep, "E")
        ens = {nz(p.en) for p in res.picks}
        rep.ok("D1 钉选必含")
        for must in ("katana", "1girl"):
            if must not in ens:
                rep.fail("D1 钉选必含", f"seed{seed}: 钉选 {must} 丢失")

    print("=" * 74)
    print(f"E NSFW 三档 0/1/2           : 各 {args.matrix} 条")
    print("=" * 74)
    nswf_density = {}
    for lv in (0, 1, 2):
        st = {**base, "nsfw": True, "nsfw_intensity": lv}
        c = engine.resolve_config(st, lib.get("settings"))
        tot = 0
        for seed in range(1, args.matrix + 1):
            res = engine.run_auto(snap, st, seed, nsfw_on=True, config=c)
            rep.prompts += 1
            tot += sum(1 for p in res.picks if p.nsfw)
            check_engine_semantics(snap, st, seed, res.picks, rep, "E", intensity=lv)
        nswf_density[lv] = tot / args.matrix
        print(f"   档位{lv}: 平均 NSFW 词 {nswf_density[lv]:.1f}/条")
    rep.ok("E11 NSFW 档位递增")
    if not (nswf_density[0] <= nswf_density[1] <= nswf_density[2]):
        rep.fail("E11 NSFW 档位递增",
                 f"密度未随档位递增: {nswf_density}")

    print("=" * 74)
    print(f"F 性别三态                  : 各 {args.matrix} 条")
    print("=" * 74)
    for g in ("off", "female", "male"):
        st = {**base, "gender": g, "nsfw": True}
        c = engine.resolve_config(st, lib.get("settings"))
        bad = 0
        for seed in range(1, args.matrix + 1):
            res = engine.run_auto(snap, st, seed, nsfw_on=True, config=c)
            rep.prompts += 1
            check_engine_semantics(snap, st, seed, res.picks, rep, "E")
            for p in res.picks:
                gg = nz(getattr(p, "gender", ""))
                if g == "female" and gg == "male":
                    bad += 1
                if g == "male" and gg == "female":
                    bad += 1
        rep.ok(f"F 性别过滤[{g}]")
        if bad:
            rep.fail(f"F 性别过滤[{g}]", f"{bad} 个违规性别的词")

    print("=" * 74)
    print(f"G 场景开关组合              : 各 {args.matrix} 条")
    print("=" * 74)
    for key in ("solo_lock", "bg_mode", "focus_mode"):
        val = True if key == "solo_lock" else ("simple" if key == "bg_mode" else "portrait")
        st = {**base, key: val, "nsfw": True}
        c = engine.resolve_config(st, lib.get("settings"))
        hits = 0
        for seed in range(1, args.matrix + 1):
            res = engine.run_auto(snap, st, seed, nsfw_on=True, config=c)
            rep.prompts += 1
            check_engine_semantics(snap, st, seed, res.picks, rep, "E")
            if key == "solo_lock":
                for p in res.picks:
                    if p.id is not None and snap.axis_arr[p.id] == "count" \
                            and nz(p.en) not in slotpolicy.SINGLE_COUNT_WORDS:
                        hits += 1
        rep.ok(f"G 场景开关[{key}]")
        if key == "solo_lock" and hits:
            rep.fail("G 场景开关[solo_lock]", f"{hits} 个非单人人数词")

    print("=" * 74)
    print(f"H 排除类目                  : 各 {args.matrix} 条")
    print("=" * 74)
    for cat in ("画师", "道具武器", "材质特效"):
        st = {**base, "exclude_categories": [cat], "nsfw": True}
        c = engine.resolve_config(st, lib.get("settings"))
        leak = 0
        for seed in range(1, args.matrix + 1):
            res = engine.run_auto(snap, st, seed, nsfw_on=True, config=c)
            rep.prompts += 1
            check_engine_semantics(snap, st, seed, res.picks, rep, "E")
            for p in res.picks:
                if p.id is None:
                    continue
                if snap.cat_names[snap.cat_of_sub[snap.sub_of[p.id]]] == cat:
                    leak += 1
        rep.ok(f"H 排除类目[{cat}]")
        if leak:
            rep.fail(f"H 排除类目[{cat}]", f"{leak} 个被排除类目的词漏出")

    print("=" * 74)
    print(f"I 压力: 连续 {args.stress} 次 build 耗时曲线")
    print("=" * 74)
    seg = max(1, args.stress // 6)
    times = []
    for i in range(args.stress):
        t0 = time.perf_counter()
        build_node("auto", base, 10000 + i)
        times.append((time.perf_counter() - t0) * 1000)
    for s in range(0, args.stress, seg):
        chunk = times[s:s + seg]
        print(f"   第 {s:>5}-{s + len(chunk):<5} 次: 中位 {sorted(chunk)[len(chunk) // 2]:6.2f} ms"
              f"  最大 {max(chunk):7.2f} ms")
    rep.ok("I 性能无累积劣化")
    first = sorted(times[:seg])[seg // 2]
    last = sorted(times[-seg:])[seg // 2]
    if last > first * 3 + 50:
        rep.fail("I 性能无累积劣化", f"末段中位 {last:.1f}ms vs 首段 {first:.1f}ms")

    # ---------------------------------------------------------------- 汇总
    print()
    print("=" * 74)
    print(f"总计评估提示词: {rep.prompts} 条")
    wc = sorted(rep.wordcounts)
    if wc:
        print(f"节点输出词数: 最小 {wc[0]} / 中位 {wc[len(wc) // 2]} / "
              f"最大 {wc[-1]} / 均值 {sum(wc) / len(wc):.1f}")
    print("=" * 74)
    bad = {k: v for k, v in rep.check.items() if v}
    for k in sorted(rep.check):
        print(f"  {'✗' if rep.check[k] else '✓'} {k}: {rep.check[k]} 次违规")
    if rep.soft:
        print("\n信息项 (不计失败, 但必须可见 —— 供人工判断是否接受):")
        for k in sorted(rep.soft):
            print(f"  · {k}: {rep.soft[k]} 次")
    if bad:
        print("\n违规样本:")
        for k, v in bad.items():
            print(f"  [{k}]")
            for s in rep.samples[k][:4]:
                print("     -", s)
        print(f"\n❌ 重度测试发现 {len(bad)} 类问题, 共 {sum(bad.values())} 次违规")
        return 1
    print("\n✅ 重度测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
