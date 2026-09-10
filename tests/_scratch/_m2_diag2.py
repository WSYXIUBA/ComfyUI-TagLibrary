"""诊断2: 复现 seed 0/1/4/7 的完整 picks。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ".."))
import library, runtime_snapshot, engine

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
state = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3, "tags": []}
WEAPONS = {w.lower() for p in snap.profiles for w in p.tags}

for seed in [0, 4, 7, 42]:
    res = engine.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None, config=None)
    seq = [(p.en.lower() in WEAPONS, p.kind, p.source, p.en) for p in res.picks]
    print(f"--- seed {seed} ---")
    for w, k, s, e in seq:
        if k == "ext" or w:
            print(f"   {'W' if w else ' '} [{k}:{s}] {e}")
    ens = {p.en.lower() for p in res.picks}
    print("   weapons:", sorted(ens & WEAPONS))
