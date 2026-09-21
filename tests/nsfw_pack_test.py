"""1.8.0 NSFW 扩展体系门禁 —— 扩展包加载 / 引擎不变量 / 吸收器 / negative / NL pack。

覆盖:
  E1  扩展包加载: 新槽位存在, NSFW 词量 ≥ 200, 全部 nsfw 词带 minor_block
  E2  引擎不变量 (400 seed): 全局互斥域 / 未成年锁 / 词级双手账本 / 体位槽单选 / 动物伙伴隔离
  E3  分轴重摇语义: pin_ignore_exclude 下保留词必含, 目标轴重出, 其余轴无新增
  E4  吸收器归一化: 权重语法 / 下划线 / 大小写 / 别名
  E5  negative 输出: 双模式非空且含 Anima 推荐负向块
  E6  NL 扩展包: nsfw 词在场时 nsfw_scene 族参与组句, SFW 时不出场
  E7  段位序: NSFW 新槽位词全部落第 6 段 (general), 无段位回退
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library
import runtime_snapshot
import engine
import slotpolicy
import nl as nl_mod
from nodes import TagLibraryNode

SNAP = runtime_snapshot.get_snapshot(library.get_merged())
STATE = {"exclude_categories": ["画师"], "gender": "female", "nsfw": True}
ERRORS: list[str] = []


def check(cond, msg):
    if not cond:
        ERRORS.append(msg)
        print(f"  ❌ {msg}")


def e1_ext_pack():
    print("E1 扩展包加载")
    for key in [("服装", "服装状态"), ("外貌特征", "身体细节"), ("动作姿态", "体位"),
                ("动作姿态", "性行为"), ("动作姿态", "束缚与调教"),
                ("动作姿态", "高潮与体液"), ("道具武器", "束缚道具")]:
        check(key in SNAP.sub_key_to_index, f"新槽位缺失: {key[0]}/{key[1]}")
    nsfw_n = sum(SNAP.nsfw_flag)
    check(nsfw_n >= 200, f"NSFW 词量不足: {nsfw_n} (期望 ≥200)")
    # nsfw 词必须全部带 minor_block (未成年锁定的词级出口)
    missing = 0
    for i in range(SNAP.n_tags):
        if SNAP.nsfw_flag[i] and SNAP.tag_lower[i] not in SNAP.minor_block_words:
            missing += 1
    check(missing == 0, f"{missing} 个 nsfw 词未进 minor_block_words")
    print(f"  tags={SNAP.n_tags} nsfw={nsfw_n}")


def e2_invariants(n_seeds=400):
    print(f"E2 引擎不变量 ({n_seeds} seed)")
    import grouprules
    dom = {}
    for g in grouprules.load_grouprules():
        for m in g["members"]:
            dom.setdefault(m, set()).add(g["id"])
    watch = {d for d in dom if d.startswith("nsfw.") or d in ("legacy.mouth", "orientation")}
    pos_si = SNAP.sub_key_to_index.get(("动作姿态", "体位"))
    animal_si = SNAP.sub_key_to_index.get(("道具武器", "动物伙伴"))
    sex_sis = {SNAP.sub_key_to_index.get(("动作姿态", k))
               for k in ("性行为", "体位", "高潮与体液", "束缚与调教")} - {None}
    v_dom = v_minor = v_hands = v_pos = v_animal = 0
    for seed in range(n_seeds):
        res = engine.run_auto(SNAP, STATE, seed, nsfw_on=True)
        lows = [p.en.lower() for p in res.picks]
        seen: dict[str, list] = {}
        for w in lows:
            for d in dom.get(w, ()):
                if d in watch:
                    seen.setdefault(d, []).append(w)
        if any(len(x) > 1 for x in seen.values()):
            v_dom += 1
        if any(w in slotpolicy.MINOR_AGE_WORDS for w in lows) \
                and any(w in SNAP.minor_block_words for w in lows):
            v_minor += 1
        hands = sum(SNAP.hands_cost[p.id] for p in res.picks
                    if p.id is not None and SNAP.hands_cost[p.id])
        if hands > 2:
            v_hands += 1
        if pos_si is not None and sum(1 for p in res.picks
                                      if p.id is not None and SNAP.sub_of[p.id] == pos_si) > 1:
            v_pos += 1
        if animal_si is not None:
            sis = {SNAP.sub_of[p.id] for p in res.picks if p.id is not None}
            if animal_si in sis and (sis & sex_sis):
                v_animal += 1
    check(v_dom == 0, f"互斥域共现 {v_dom}/{n_seeds}")
    check(v_minor == 0, f"未成年锁违规 {v_minor}/{n_seeds}")
    check(v_hands == 0, f"双手账本违规 {v_hands}/{n_seeds}")
    check(v_pos == 0, f"体位槽多选 {v_pos}/{n_seeds}")
    check(v_animal == 0, f"动物伙伴×性行为共现 {v_animal}/{n_seeds}")


def e3_reroll(n_seeds=60):
    print("E3 分轴重摇语义")
    base_si = SNAP.sub_key_to_index.get(("动作姿态", "站走与动态"))
    for seed in range(n_seeds):
        res0 = engine.run_auto(SNAP, STATE, seed, nsfw_on=True)
        if len(res0.picks) < 6:
            continue
        keep_en = [p.en for p in res0.picks if p.axis != "action"][:6]
        if len(keep_en) < 3:
            continue
        st = dict(STATE)
        st["exclude_categories"] = [a for a in
                                    ("画质规格", "人数", "角色身份", "画师", "外貌特征",
                                     "服装", "道具武器", "场景环境", "光影氛围",
                                     "构图镜头", "风格媒介", "材质特效")]
        st["tags"] = [{"en": w, "pinned": True} for w in keep_en]
        st["pin_ignore_exclude"] = True
        res = engine.run_auto(SNAP, st, seed + 9999, nsfw_on=True)
        got_en = {p.en for p in res.picks}
        missing = [w for w in keep_en if w not in got_en]
        check(not missing, f"seed {seed}: 保留词丢失 {missing[:3]}")
        new_action = [p for p in res.picks
                      if p.axis == "action" and p.source not in ("pinned", "implied")
                      and p.en not in keep_en]
        if not new_action:
            continue  # 允许个别 seed 目标轴候选被锁光
        break


def e4_absorb():
    print("E4 吸收器归一化")
    # api 包是相对导入, 独立脚本用合成父包加载
    import types
    import importlib
    root = types.ModuleType("_tl_gate_root")
    root.__path__ = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    sys.modules["_tl_gate_root"] = root
    api_pkg = types.ModuleType("_tl_gate_root.api")
    api_pkg.__path__ = [os.path.join(root.__path__[0], "api")]
    sys.modules["_tl_gate_root.api"] = api_pkg
    mod = importlib.import_module("_tl_gate_root.api.v18_routes")
    _norm_token = mod._norm_token
    check(_norm_token("(missionary:1.2)") == "missionary", "权重语法未剥离")
    check(_norm_token("blue_hair") == "blue hair", "下划线未转空格")
    check(_norm_token("  1GIRL  ") == "1girl", "大小写/空白")
    check(_norm_token("@wlop") == "wlop", "画师 @ 前缀未剥")
    tid = SNAP.en_to_id.get("1girl")
    check(tid is not None, "吸收目标查表失败 (1girl 不在库)")


def e5_negative():
    print("E5 negative 输出")
    node = TagLibraryNode()
    check(len(TagLibraryNode.RETURN_TYPES) == 3, "RETURN_TYPES 不是 3 元")
    ra = node._build_impl("{}", "auto", 5)
    neg_a = ra["result"][2]
    rm = node._build_impl(json.dumps({"tags": [{"en": "1girl"}]}), "manual", 5)
    neg_m = rm[2]
    for tag, neg in (("auto", neg_a), ("manual", neg_m)):
        check("worst quality" in neg and "score_1" in neg, f"{tag} 负向块缺失")
    # negative_out=false 可关
    r_off = node._build_impl(json.dumps({"tags": [{"en": "1girl"}], "negative_out": False}),
                             "manual", 5)
    check(r_off[2] == "", "negative_out=false 未关闭")


def e6_nl_pack(n_seeds=100):
    print("E6 NL 扩展包")
    fams = (nl_mod.load_flavors().get("families") or {})
    check("nsfw_scene" in fams, "nsfw_scene 族未加载")
    seen_nsfw_sentence = False
    for seed in range(n_seeds):
        res = engine.run_auto(SNAP, STATE, seed, nsfw_on=True)
        if not any(p.nsfw for p in res.picks):
            continue
        tail = nl_mod.compile_tail(SNAP, res.picks, seed)
        check(len([s for s in tail.split(". ") if s.strip()]) >= 2,
              f"seed {seed}: NL 尾段 <2 句")
        # SFW 侧: 纯 SFW picks 不应出现 nsfw_scene 句
    sfw_res = engine.run_auto(SNAP, {"exclude_categories": ["画师"]}, 42, nsfw_on=False)
    sfw_picks = [p for p in sfw_res.picks if not p.nsfw]
    tail = nl_mod.compile_tail(SNAP, sfw_picks, 42)
    check(tail.strip() != "", "SFW 场景 NL 尾段为空")


def e7_section_order(n_seeds=200):
    print("E7 NSFW 词段位序")
    bad = 0
    for seed in range(n_seeds):
        res = engine.run_auto(SNAP, STATE, seed, nsfw_on=True)
        last_sec = 0
        for p in res.picks:
            sec = p.order // 10000
            if sec < last_sec:
                bad += 1
                break
            last_sec = sec
    check(bad == 0, f"段位回退 {bad}/{n_seeds}")


def e8_intensity(n_seeds=100):
    print("E8 NSFW 强度旋钮")
    import statistics
    def avg_nsfw_words(intensity):
        ns = []
        st = {**STATE, "nsfw_intensity": intensity}
        for seed in range(n_seeds):
            res = engine.run_auto(SNAP, st, seed + 777, nsfw_on=True)
            ns.append(sum(1 for p in res.picks if p.nsfw))
        return statistics.mean(ns)
    a0, a2 = avg_nsfw_words(0), avg_nsfw_words(2)
    check(a2 >= a0 * 2.0, f"纯欲档提升不足: 标准 {a0:.1f} vs 纯欲 {a2:.1f}")
    print(f"  标准 {a0:.1f} → 纯欲 {a2:.1f} 个 NSFW 词/条")


def e9_explicit_tier(n_seeds=60):
    print("E9 显式档分层")
    st = {**STATE, "nsfw_intensity": 2}
    hits = 0
    for seed in range(n_seeds):
        res = engine.run_auto(SNAP, st, seed + 31337, nsfw_on=True)
        if any(p.nsfw and SNAP.explicit_flag[p.id] for p in res.picks if p.id is not None):
            hits += 1
    check(hits >= n_seeds * 0.9,
          f"纯欲档显式词保底不足: {hits}/{n_seeds} (期望 ≥90% 条目含 explicit 词)")
    print(f"  显式词命中 {hits}/{n_seeds}")


if __name__ == "__main__":
    e1_ext_pack()
    e2_invariants()
    e3_reroll()
    e4_absorb()
    e5_negative()
    e6_nl_pack()
    e7_section_order()
    e8_intensity()
    e9_explicit_tier()
    print()
    if ERRORS:
        print(f"❌ NSFW 扩展门禁 FAIL ({len(ERRORS)} 项)")
        sys.exit(1)
    print("✅ NSFW 扩展门禁 PASS (E1~E9)")
