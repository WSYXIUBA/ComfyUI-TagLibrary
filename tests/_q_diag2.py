"""验证 ext 词组名查询一致性。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library, runtime_snapshot, grouprules

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
W = "sword out of mouth"
print("snap.en_groups 命中:", snap.en_groups.get(W))
print("grouprules 命中:", grouprules.en_membership().get(W))
# 文件里到底有没有
import json
p = os.path.join(os.path.dirname(__file__), "..", "data", "default", "taglib", "grouprules.json")
d = json.load(open(p, encoding="utf-8"))
for g in d["groups"]:
    if W in g["members"]:
        print("文件中:", g["id"], "成员数", len(g["members"]))
# eating/panting/smirk 的组
for w in ("eating", "panting", "smirk"):
    print(w, "->", sorted(grouprules.en_membership().get(w, []))[:3])
# _compile_ext 时 prof.poses 里 mouth 姿势的 comp_groups
for prof in snap.profiles:
    for pose in list(prof.poses) + list(prof.extras):
        if any(t == W for t in pose.tags):
            print("pose", prof.id, pose.pose_id, "comp_groups=", pose.comp_groups)
