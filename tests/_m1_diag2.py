import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library, runtime_snapshot, engine
lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
state = {"fill_master": True, "fill_master_min": 3, "fill_master_max": 4, "tags": []}
res = engine.run_auto(snap, state, 0, nsfw_on=False, avoid_conflicts=True,
                      search_text="", cat_weights=None, config=None)
ens = [(p.en, p.id, p.source) for p in res.picks]
print("seed0 picks:", ens)
solo = snap.tag_id("solo")
g5 = snap.tag_id("5girls")
print("ids:", solo, g5)
hits = []
for ri, (lset, rids) in enumerate(snap.cross_rules):
    if solo in lset and g5 in rids:
        hits.append(ri)
    if g5 in lset and solo in rids:
        hits.append(("rev", ri))
print("rules linking them:", hits)
# 该规则左侧集合大小 vs solo 侧
for ri in hits:
    if isinstance(ri, tuple):
        continue
    lset, rids = snap.cross_rules[ri]
    print("rule", ri, "L n=", len(lset), "R n=", len(rids),
          "L∩R overlap:", len(set(lset) & set(rids)))
# 模拟账本回放: 哪个 pick 先提交的
for p in res.picks:
    if p.id in (solo, g5):
        print("picked:", p.en, p.source, p.order)
