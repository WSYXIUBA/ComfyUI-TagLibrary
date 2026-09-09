"""M2 验收: 武器档案束上线后, repro 五缺陷全部翻案 + 质量长跑。

python tests/m2_weapon_slice_test.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library            # noqa: E402
import runtime_snapshot   # noqa: E402
import engine             # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)

# 从档案动态取: 武器身份词全集 / 束成员全集 (库内部分)
WEAPONS = {w.lower() for p in snap.profiles for w in p.tags}
BUNDLED = {snap.tag_text[i].lower() for i in snap.bundled_only}
print(f"档案 {len(snap.profiles)} 份 | 身份词 {len(WEAPONS)} | 束成员(库内) {len(BUNDLED)}")

state = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3, "tags": []}
N = 500


def run(seed):
    return engine.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                           search_text="", cat_weights=None, config=None)


# ---- ①② 束出生统计以 ext picks 为准 (束成员词可能在库外——档案输出全集)
print("① 武器→姿势 出生率")
with_weapon = with_pose = 0
t0 = time.perf_counter()
for seed in range(N):
    picks = run(seed).picks
    ens = {p.en.lower() for p in picks}
    has_w = bool(ens & WEAPONS)
    has_bundle = any(p.kind == "ext" and p.source == "bundle" for p in picks)
    if has_w:
        with_weapon += 1
        if has_bundle:
            with_pose += 1
rate = with_pose / max(with_weapon, 1)
print(f"    {N} seed: {with_weapon} 出武器, {with_pose} 带姿势 ({rate:.0%}) {time.perf_counter()-t0:.1f}s")
check("武器场景带束率 >= 60% (理论85%, 资源挤占容忍)", rate >= 0.60, f"{rate:.2%}")

# ---- ② 束成员裸出 = 0 (姿势无武器): ext pick 必与武器同现
print("② 束词必带武器")
bare = 0
bare_ex = []
for seed in range(N):
    picks = run(seed).picks
    ens = {p.en.lower() for p in picks}
    if any(p.kind == "ext" for p in picks) and not (ens & WEAPONS):
        bare += 1
        if len(bare_ex) < 3:
            bare_ex.append(seed)
check(f"{N} seed 零裸姿势", bare == 0, str(bare_ex))

# ---- ③ hands/gaze 账本: 直接审计 Pick
print("③ 资源账本审计")
over_h = over_g = 0
ex_h = []
for seed in range(N):
    res = run(seed)
    h = sum(p.hands for p in res.picks)
    g = sum(p.gaze for p in res.picks)
    if h > 2:
        over_h += 1
        if len(ex_h) < 3:
            ex_h.append((seed, h, sorted(p.en for p in res.picks if p.hands)))
    if g > 1:
        over_g += 1
check("零 hands 超配", over_h == 0, str(ex_h))
check("零 gaze 超配", over_g == 0)

# ---- ④ 物理矛盾: 同一档案 (pid) 的 持握姿 + 收纳姿 不同现 (配件 extras 不计)
print("④ 同档案 持握↔收纳 物理矛盾")
viol = 0
viol_ex = []
STORE_WORDS = {"weapon on back", "katana on back", "sheathed sword", "katana sheath"}
for seed in range(N):
    res = run(seed)
    per_pid: dict = {}
    for p in res.picks:
        if p.kind != "ext" or not p.bundle or p.is_extra:
            continue
        pid = p.bundle.split(":", 1)[0]
        st = per_pid.setdefault(pid, set())
        st.add("store" if p.en.lower() in STORE_WORDS else "hold")
    for pid, st in per_pid.items():
        if {"hold", "store"} <= st:
            viol += 1
            if len(viol_ex) < 3:
                viol_ex.append((seed, pid))
check(f"{N} seed 同档案零持握/收纳同现", viol == 0, str(viol_ex[:3]))

# ---- ⑤ 束相邻: 武器与紧随其后的 ext 成员距离 <= 4
print("⑤ 束相邻输出")
far = 0
for seed in range(N):
    picks = run(seed).picks
    for i, p in enumerate(picks):
        if p.kind == "ext" and p.source == "bundle":
            # 往上找最近的宿主武器 tag
            host = None
            for j in range(i - 1, max(i - 6, -1), -1):
                if picks[j].en.lower() in WEAPONS:
                    host = j
                    break
            if host is None:
                far += 1
check(f"{N} seed 束成员紧贴武器", far == 0, str(far))

# ---- ⑥ 复现性
print("⑥ 复现性")
a = run(7)
b = run(7)
check("同 seed 同输出", [p.en for p in a.picks] == [p.en for p in b.picks])

# ---- ⑦ 双钉武器各带束 (repro①)
print("⑦ 双钉武器各自带束 (旧缺陷①)")
KAT_POSE = {"drawing sword", "two-handed sword", "holding sword", "reverse grip",
            "weapon resting on shoulder", "sword out of mouth", "sheathing sword",
            "katana sheath", "katana on back"}
GUN_POSE = {"aiming gun", "aiming at viewer", "holding gun", "holding gun behind back",
            "holding weapon two-handed", "weapon on back", "gun lowered", "sniper scope"}
dual = {"fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
        "tags": [{"en": "katana", "pinned": True}, {"en": "rifle", "pinned": True}]}
both = 0
for seed in range(100):
    res = engine.run_auto(snap, dual, seed, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None,
                          config={"bundle_pose_prob": 1.0})
    ens = {p.en.lower() for p in res.picks}
    if ens & KAT_POSE and ens & GUN_POSE:
        both += 1
check("100 seed 双武器 100% 各带姿势", both == 100, f"{both}/100")

# ---- ⑧ 弓不蹭 gun 词 (repro③)
print("⑧ 弓组零 aiming gun (旧缺陷③)")
bow_state = {"fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
             "tags": [{"en": "bow (weapon)", "pinned": True}]}
wrong = 0
for seed in range(100):
    res = engine.run_auto(snap, bow_state, seed, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None,
                          config={"bundle_pose_prob": 1.0})
    ens = {p.en.lower() for p in res.picks}
    if "aiming gun" in ens:
        wrong += 1
check("100 seed 弓组零 aiming gun", wrong == 0, str(wrong))

# ---- ⑨ 旧姿势池词不再裸进 auto (池自抽被 bundled_only 拦)
print("⑨ 束专属词池自抽 = 0")
solo_pose = 0
for seed in range(N):
    res = run(seed)
    for p in res.picks:
        if p.kind == "tag" and p.source not in ("pinned", "bundle", "implied") \
                and p.en.lower() in BUNDLED:
            solo_pose += 1
check(f"{N} seed 池自抽束词零命中", solo_pose == 0, str(solo_pose))

print()
if FAILS:
    print(f"❌ M2 FAILED: {FAILS}")
    sys.exit(1)
print("✅ M2 WEAPON SLICE ALL PASS")
