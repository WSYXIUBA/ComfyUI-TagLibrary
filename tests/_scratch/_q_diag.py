"""定点回放审计失败样本: 打印每个 pick 的出处 (pool/pinned/implied/bundle)。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ".."))
import library, runtime_snapshot, engine

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)

SCEN = [
    ("双枪少女", {"tags": [{"en": "1girl", "pinned": True},
        {"en": "dual pistols", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}, 2),
    ("草原长杖", {"tags": [{"en": "1girl", "pinned": True},
        {"en": "staff", "pinned": True}, {"en": "forest", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}, 2),
    ("无钉纯随机A", {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3}, 4),
    ("无钉纯随机B", {"fill_master": True, "fill_master_min": 1, "fill_master_max": 2}, 0),
    ("无钉纯随机B", {"fill_master": True, "fill_master_min": 1, "fill_master_max": 2}, 4),
]

for name, st, seed in SCEN:
    real = (seed * 97 + (hash(name) & 1023))
    res = engine.run_auto(snap, st, real, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None,
                          config={"bundle_pose_prob": 1.0})
    print(f"\n=== {name} seed{seed} (hands总计={sum(p.hands for p in res.picks)}) ===")
    for p in res.picks:
        g = snap.group_sets[p.id] if p.id is not None else snap.en_groups.get(p.en.lower(), frozenset())
        mark = "H" if p.hands else " "
        print(f"  {mark} [{p.source:8s}] {'ext' if p.kind=='ext' else 'tag '} {p.en:26s} g={len(g)}")
    # 性别泄漏点
    lock = None
    for p in res.picks:
        if p.id is not None and snap.axis_arr[p.id] == "count" and snap.gender_flag[p.id]:
            lock = ("F" if snap.gender_flag[p.id] == 1 else "M") + ":" + p.en
            break
    print("  count锁源:", lock)
    if lock and "girl" in lock:
        for p in res.picks:
            if p.id is not None and snap.gender_flag[p.id] == 2:
                print("   男词漏网:", p.en, "source=", p.source, "axis=", snap.axis_arr[p.id])
