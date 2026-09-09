import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library, runtime_snapshot, engine
lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
state = {"fill_master": True, "fill_master_min": 3, "fill_master_max": 4, "tags": []}
kind_count = collections.Counter()
examples = []
for seed in range(300):
    res = engine.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                          search_text="", cat_weights=None, config=None)
    ids = [p.id for p in res.picks if p.id is not None]
    idset = set(ids)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            gi = snap.group_sets[ids[i]] & snap.group_sets[ids[j]]
            if gi:
                kind_count["group"] += 1
                if len(examples) < 8:
                    examples.append(("GROUP", seed, snap.tag_text[ids[i]], snap.tag_text[ids[j]], tuple(gi)[:3]))
    for lset, rids in snap.cross_rules:
        L = [x for x in lset if x in idset]
        R = [x for x in rids if x in idset]
        if L and R:
            kind_count["cross"] += 1
            if len(examples) < 8:
                examples.append(("CROSS", seed, snap.tag_text[L[0]], snap.tag_text[R[0]], len(lset), len(rids)))
print(kind_count)
for e in examples:
    print(e)
