"""M4 专项: 日常物品档案束 + 泛化约束长跑审计。

python tests/m4_objects_test.py            → 断言 + 前6条样本
python tests/m4_objects_test.py --long     → 5000 seed 长跑 (打印问题清单)
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library            # noqa: E402
import runtime_snapshot   # noqa: E402
import engine             # noqa: E402
import nl                 # noqa: E402

LONG = "--long" in sys.argv
lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


OBJ_PREFIX = ("obj.",)
objs = [p for p in snap.profiles if p.id.startswith(OBJ_PREFIX)]
print(f"物品档案: {len(objs)} 份 | 总档案 {len(snap.profiles)}")
check("≥10 份物品档案", len(objs) >= 10, str(len(objs)))

OBJ_HOSTS = {w.lower() for p in objs for w in p.tags}
MOUNT_MISS = [f"{p.id}:{w}" for p in objs for w in p.tags if snap.tag_id(w) is None]
check("物品身份词全部挂上库内词", not MOUNT_MISS, str(MOUNT_MISS[:6]))

# NL 覆盖: 物品姿势词都有句式族 (sub_family 或 pose_map)
F = nl.load_flavors()
sub_fam = F.get("sub_family") or {}
pose_map = F.get("pose_map") or {}
uncovered = []
for p in objs:
    tbl = sub_fam.get(p.id) or {}
    for pose in p.poses:
        fam = tbl.get(pose.pose_id) or pose_map.get(pose.tags[0].lower())
        if not fam and pose.hands == 0 and pose.is_extra:
            continue  # 配件不需要独立句
        if not fam:
            uncovered.append(f"{p.id}:{pose.pose_id}")
check("物品姿势 NL 族全覆盖", not uncovered, str(uncovered[:6]))


def run(state, seed, cfg=None):
    c = {"bundle_pose_prob": 1.0}
    if cfg:
        c.update(cfg)
    return engine.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                           search_text="", cat_weights=None, config=c)


# ---- 单物品钉选: 必带束 / 资源 / 组冲突 / 物理矛盾 (每个物品 300 seed)
STATE_TMPL = {"fill_master": True, "fill_master_min": 1, "fill_master_max": 2}
MOUTH_LOCK = {"food in mouth", "sword out of mouth", "cigarette in mouth",
              "straw in mouth", "biting food", "sucking object", "holding lollipop"}
total_draws = 0
no_bundle = []
res_bad = []
mouth_bad = []
t0 = time.perf_counter()
for p in objs:
    host = next((w for w in p.tags if snap.tag_id(w) is not None), None)
    if host is None:
        continue
    st = dict(STATE_TMPL, tags=[{"en": host, "pinned": True}])
    for seed in range(300):
        res = run(st, seed)
        total_draws += 1
        ens = {q.en.lower() for q in res.picks}
        ext = [q for q in res.picks if q.kind == "ext"]
        if not ext:
            no_bundle.append((p.id, seed))
        if sum(q.hands for q in res.picks) > 2:
            res_bad.append((p.id, seed, sorted(q.en for q in res.picks if q.hands)))
        if len(ens & MOUTH_LOCK) >= 2:
            mouth_bad.append((p.id, seed, sorted(ens & MOUTH_LOCK)))
dt = time.perf_counter() - t0
check(f"{total_draws} 次抽取全部带束", not no_bundle, str(no_bundle[:4]))
check("零 hands 超配", not res_bad, str(res_bad[:4]))
check("零嘴部双占", not mouth_bad, str(mouth_bad[:4]))
print(f"  [perf] {total_draws} draws in {dt:.1f}s = {dt/total_draws*1000:.2f}ms/draw")

# ---- 双物品资源互斥: 伞+双手捧杯 (1手+2手=3>2) → 不可能全双手
st2 = {"fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
       "tags": [{"en": "umbrella", "pinned": True},
                {"en": "teacup", "pinned": True}]}
over = 0
for seed in range(200):
    res = run(st2, seed)
    if sum(q.hands for q in res.picks) > 2:
        over += 1
check("伞+杯 200seed 零三手", over == 0)

# ---- 书+看手机 视线互斥 (gaze=1 只能一个)
st3 = {"fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
       "tags": [{"en": "book", "pinned": True},
                {"en": "smartphone", "pinned": True}]}
both_gaze = 0
for seed in range(200):
    res = run(st3, seed)
    ens = {q.en.lower() for q in res.picks}
    if "looking at phone" in ens and ("open book" in ens or "holding book" in ens):
        both_gaze += 1
check("书+手机 零双视线", both_gaze == 0, str(both_gaze))

# ---- 泛化随机 (不钉选) 1000 seed: 裸束词/男女锁/嘴锁/资源 全出口复核
st_rand = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3}
bad_rand = []
N = 5000 if LONG else 1000
for seed in range(N):
    res = run(st_rand, seed)
    ens = {q.en.lower() for q in res.picks}
    allw = snap.bundled_only | {w.lower() for p in snap.profiles for e in list(p.poses)+list(p.extras) for w in e.tags}
    if (ens & allw) and not (ens & {w.lower() for p in snap.profiles for w in p.tags}):
        bad_rand.append(("裸束", seed))
    if sum(q.hands for q in res.picks) > 2:
        bad_rand.append(("超手", seed))
    if len(ens & MOUTH_LOCK) >= 2:
        bad_rand.append(("嘴锁", seed, sorted(ens & MOUTH_LOCK)))
check(f"{N} seed 泛化随机出口复核", not bad_rand, str(bad_rand[:5]))

if not LONG:
    print("\n---- 样本 (人工眼评) ----")
    seen = 0
    for p in objs[:6]:
        host = next((w for w in p.tags if snap.tag_id(w)), None)
        res = run({"fill_master": True, "fill_master_min": 1, "fill_master_max": 2,
                   "tags": [{"en": host, "pinned": True},
                            {"en": "1girl", "pinned": True}]}, 11)
        tail = nl.compile_tail(snap, res.picks, 11)
        text = ", ".join(q.en for q in res.picks) + ((". " + tail) if tail else "")
        print(f"[{p.id}] {text[:400]}")
        print()

print()
if FAILS:
    print(f"❌ M4 FAILED: {FAILS}")
    sys.exit(1)
print("✅ M4 OBJECTS ALL PASS")
