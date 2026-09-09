"""诊断 seed 12/21/31: weapon.gun 的 hold+store 同现。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library, runtime_snapshot, engine

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
state = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3, "tags": []}
for seed in [12, 21, 31]:
    res = engine.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None, config=None)
    print(f"--- seed {seed} ---")
    for p in res.picks:
        if p.kind == "ext":
            print(f"   [{p.bundle}] {p.en} hands={p.hands}")
    # 档案里 gun 的 on_back 定义
for prof in snap.profiles:
    if prof.id == "weapon.gun":
        for pose in prof.poses:
            print(prof.id, pose.pose_id, pose.tags, pose.hands, pose.state_slot_keys)
