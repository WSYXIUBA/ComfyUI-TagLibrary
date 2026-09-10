"""给 profiles.json 的持握系姿势补 weapon_state=held (与 on_back/sheathed 对撞)。"""
import json, os, sys

P = os.path.join(os.path.dirname(__file__), "..", "data", "default", "taglib", "profiles.json")
d = json.load(open(P, encoding="utf-8"))
STORE_IDS = {"on_back", "sheathed", "sheath"}
n = 0
for prof in d["profiles"]:
    for pose in prof.get("poses", []):
        ss = pose.get("state_slot") or {}
        if not ss and pose["id"] not in STORE_IDS:
            pose["state_slot"] = {"weapon_state": "held"}
            n += 1
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("patched", n, "poses with held state")
