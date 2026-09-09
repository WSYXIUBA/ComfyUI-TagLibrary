"""诊断: attach_bundle fitted 候选为何常空。"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library, runtime_snapshot, engine

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
state = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3, "tags": []}

# monkeypatch: 记录每次 attach 的宿主/fitted 长度/失败原因
orig_run = engine.run_auto
import random as _r

stats = collections.Counter()
reasons = collections.Counter()
failsample = []

for seed in range(200):
    res = orig_run(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                   search_text="", cat_weights=None, config=None)
    picks = res.picks
    ens = {p.en.lower() for p in picks}
    # 武器词: 有束 vs 无束
    # (束词 = kind==ext)
    ext_host_missing = 0
    for p in picks:
        if p.kind == "tag" and p.source in ("random",):
            pass
    nb = sum(1 for p in picks if p.kind == "ext")
    nw = sum(1 for p in picks if p.en.lower() in {w.lower() for pr in snap.profiles for w in pr.tags})
    stats[(nw, nb > 0)] += 1

print("(武器数, 是否带束) → 次数")
for k in sorted(stats):
    print("  ", k, stats[k])
