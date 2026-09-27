"""时代门 (1.15.x): 场景定调 + 道具/配饰时代一致性回归。

机制: 钉选/手选词与场景轴词中首个带 era 的词定调 (era_lock); 之后抽取中,
管辖词 (道具轴全集 + 服装的头部配饰/首饰珠宝/手套围巾与包袋) 若 era 明确
且与锁不符, 候选级排除; era 未标/中性词永远放行。

python tests/era_gate_test.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine            # noqa: E402
import library           # noqa: E402
import runtime_snapshot  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)

# 独立于实现的管辖槽名单 (重复声明 —— 与 runtime_snapshot 里的常量互为印证)
GATED_SLOTS = {
    ("道具武器", "武器装备"), ("道具武器", "食物饮品"), ("道具武器", "日用道具"),
    ("道具武器", "乐器与运动"), ("道具武器", "动物伙伴"), ("道具武器", "束缚道具"),
    ("服装", "头部配饰"), ("服装", "首饰珠宝"), ("服装", "手套围巾与包袋"),
}
ERA_CODE = {"modern": 1, "retro": 2, "fantasy": 3}

print("T1 era 编译")
n_era = sum(1 for i in range(snap.n_tags) if snap.era_flag[i])
check("era 词数 350~430", 350 <= n_era <= 430, str(n_era))
n_gated = sum(snap.era_gated)
check("管辖词数 >= 300", n_gated >= 300, str(n_gated))
# gated 词必须只落在名单槽位 (逐词回查槽名)
bad_gate = 0
for tid in range(snap.n_tags):
    if not snap.era_gated[tid]:
        continue
    ci = snap.cat_of_sub[snap.sub_of[tid]]
    key = (snap.cat_names[ci], snap.sub_names[snap.sub_of[tid]])
    if key not in GATED_SLOTS:
        bad_gate += 1
check("gated 全集 = 名单槽位", bad_gate == 0, str(bad_gate))


def gated_era_violations(res, want_codes):
    """返回 selector 结果里 era 违例的 (en, era) 列表 (仅管辖词)。"""
    bad = []
    for p in res.picks:
        if p.id is None:
            continue
        if not snap.era_gated[p.id]:
            continue
        ef = snap.era_flag[p.id]
        if ef and ef not in want_codes:
            bad.append((str(p.en), ef))
    return bad


def run(state, seed):
    return engine.run_auto(snap, state, seed, nsfw_on=False,
                           avoid_conflicts=True, search_text="",
                           cat_weights=None, config=None)


print("T2 钉选 fantasy 场景 -> 管辖词只出 fantasy/中性")
st_f = {"fill_master": True, "fill_master_min": 6, "fill_master_max": 12,
        "tags": [{"en": "cyberpunk city", "pinned": True}]}
viol = 0
sample = []
for seed in range(30):
    res = run(st_f, seed)
    v = gated_era_violations(res, {0, ERA_CODE["fantasy"]})
    if v:
        viol += len(v)
        sample += v[:2]
check("30 seeds 零违例", viol == 0, f"{viol} 例: {sample[:6]}")

print("T3 钉选 retro 场景 -> 管辖词只出 retro/中性")
st_r = {"fill_master": True, "fill_master_min": 6, "fill_master_max": 12,
        "tags": [{"en": "medieval street", "pinned": True}]}
viol = 0
sample = []
for seed in range(30):
    res = run(st_r, seed)
    v = gated_era_violations(res, {0, ERA_CODE["retro"]})
    if v:
        viol += len(v)
        sample += v[:2]
check("30 seeds 零违例", viol == 0, f"{viol} 例: {sample[:6]}")

print("T4 无定调 -> 门不生效 (老行为)")
seen_era = set()
for seed in range(20):
    res = run({"fill_master": True, "fill_master_min": 6, "fill_master_max": 12,
               "tags": []}, seed)
    for p in res.picks:
        if p.id is not None and snap.era_gated[p.id] and snap.era_flag[p.id]:
            seen_era.add(snap.era_flag[p.id])
check("无钉选时多时代词都能出", len(seen_era) >= 2, str(seen_era))

print("T5 钉选词豁免门 (钉了就出)")
st5 = {"fill_master": True, "fill_master_min": 6, "fill_master_max": 12,
       "tags": [{"en": "cyberpunk city", "pinned": True},
                {"en": "vinyl record", "pinned": True}]}
ok = 0
for seed in range(10):
    res = run(st5, seed)
    ens = {str(p.en).lower() for p in res.picks}
    if "cyberpunk city" in ens and "vinyl record" in ens:
        ok += 1
check("双钉选 (fantasy+retro) 都出", ok == 10, f"{ok}/10")

print("T6 场景违和闸: 钉 beach -> 配对毁图词被拉黑")
_SCENE_BANNED = {"frying pan", "chef knife", "scissors", "trowel", "laptop",
                 "tablet computer", "vr headset", "game controller",
                 "knitting needles", "needle and thread", "cassette player",
                 "walkman", "megaphone"}
st6 = {"fill_master": True, "fill_master_min": 8, "fill_master_max": 16,
       "tags": [{"en": "beach", "pinned": True}]}
hits = 0
sample6 = []
for seed in range(40):
    res = run(st6, seed)
    ens = {str(p.en).lower() for p in res.picks}
    hit = ens & _SCENE_BANNED
    if hit:
        hits += len(hit)
        sample6 += list(hit)[:2]
check("40 seeds 零违例", hits == 0, f"{hits} 例: {sample6[:6]}")

print("T7 无场景词时这些词仍可出现 (闸不误杀)")
seen = set()
for seed in range(40):
    res = run({"fill_master": True, "fill_master_min": 8, "fill_master_max": 16,
               "tags": []}, seed)
    ens = {str(p.en).lower() for p in res.picks}
    seen |= (ens & {"laptop", "chef knife", "frying pan", "scissors",
                    "game controller", "trowel"})
check("至少出现 1 个", len(seen) >= 1, str(seen))

print()
if FAILS:
    print(f"结果: {len(FAILS)} 项失败: {FAILS}")
    sys.exit(1)
print("结果: 全部通过")
