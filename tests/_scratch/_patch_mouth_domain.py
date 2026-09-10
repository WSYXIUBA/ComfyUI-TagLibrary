"""给 grouprules.json 的 legacy.mouth 域补漏网成员 (衔物嘴互斥域)。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ".."))
import grouprules

ADD = ["food in mouth", "holding food in mouth", "sword out of mouth",
       "object in mouth", "knife in mouth", "weapon in mouth",
       "popsicle in mouth", "lollipop in mouth", "flower in mouth",
       "rose in mouth", "leaf in mouth", "feather in mouth",
       "chopsticks in mouth", "pen in mouth", "straw in mouth",
       "finger in own mouth", "thermometer"]

groups = grouprules.load_grouprules()
target = next((g for g in groups if g["id"] == "legacy.mouth"), None)
assert target, "legacy.mouth 组不存在"
before = len(target["members"])
# load 返回 set, 转回 list 存储
have = {m.lower() for m in target["members"]}
added = []
ms = set(target["members"])
for a in ADD:
    if a not in have:
        ms.add(a)
        added.append(a)
target["members"] = sorted(ms)
out = [{"id": g["id"], "members": sorted(g["members"])} for g in groups]
grouprules.save_grouprules(out)
print(f"mouth 域 {before} → {len(target['members'])}, 补: {added}")
