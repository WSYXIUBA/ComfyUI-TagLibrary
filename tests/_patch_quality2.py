"""质量审计 v2 数据补口: 嘴域/年龄域/legwear 成员词 + 脏词清理 + 平静/兴奋 cross 规则。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import grouprules
import tagconflicts

# ---- 1) grouprules 成员补口
groups = grouprules.load_grouprules()
gmap = {g["id"]: g for g in groups}

def add(gid, words):
    g = gmap.get(gid)
    if g is None:
        print("!! 组不存在", gid)
        return []
    ms = set(g["members"])
    added = [w for w in words if w not in ms]
    ms.update(added)
    g["members"] = sorted(ms)
    return added

a1 = add("legacy.mouth", ["tongue between teeth", "biting lower lip", "biting upper lip",
                          "lips parted slightly", "wavy mouth", "pursed lips", "tongue out",
                          "open-mouthed gasp", "fang open mouth", "covering mouth",
                          "holding food in mouth"])
a2 = add("legacy.age_group", ["old man", "young girl", "grown man(成年男性)",
                              "lady", "ladyboy"])
a3 = add("age_group", ["old man", "young girl"])
a4 = add("legacy.emotion_opp", ["laughing", "crying", "smiling", "grinning"])
print("mouth +", a1)
print("age +", a2, a3)
print("emotion +", a4)
grouprules.save_grouprules([{"id": g["id"], "members": sorted(g["members"])}
                            for g in groups])

# ---- 2) legwear 域: thighhighs 变体 (socks-single 组) 查库内全部变体
import library
lib = library.get_merged()
thigh_variants = set()
for c in lib["categories"]:
    for s in c["subcategories"]:
        for t in s.get("tags", []) or []:
            en = str(t.get("en", "")).lower()
            if en.startswith("thighhighs") or en.startswith("thigh highs"):
                thigh_variants.add(en)
groups = grouprules.load_grouprules()
gmap = {g["id"]: g for g in groups}
socks = gmap.get("socks-single")
if socks:
    ms = set(socks["members"])
    addv = [v for v in thigh_variants if v not in ms]
    ms.update(thigh_variants)
    socks["members"] = sorted(ms)
    grouprules.save_grouprules([{"id": g["id"], "members": sorted(g["members"])}
                                for g in groups])
    print(f"socks-single + {len(addv)} thighhighs 变体: {sorted(thigh_variants)}")

# ---- 3) cross 规则: 平静系 ↔ 兴奋系; solo 系 ↔ multiple others; 0others 收紧
rules = tagconflicts.load_rules()
byid = {r.get("id"): r for r in rules}

CALM = ["calm", "serene expression", "sleepy", "tired", "bored", "sleeping",
        "unconscious", "contemplative", "meditating", "relieved"]
EXCITED = ["ecstatic", "frantic", "overwhelmed", "laughing", "giggling",
           "screaming", "shouting", "yelling", "crying", "orgasm"]
newr = []
if "calm-vs-excited" not in byid:
    newr.append({"id": "calm-vs-excited", "note": "平静状态 ↔ 激烈情绪",
                 "left": {"kind": "tags", "value": CALM},
                 "right": [{"kind": "tag", "value": x} for x in EXCITED],
                 "type": "mutex", "enabled": True, "priority": 100,
                 "scope": ["auto", "manual_fill"], "params": {}})
# 0others / solo focus ↔ 所有多人词 (含 multiple others 变体)
if "solo-focus-vs-multi" not in byid:
    newr.append({"id": "solo-focus-vs-multi", "note": "聚焦单人 ↔ 多人词",
                 "left": {"kind": "tags", "value": ["0others", "solo focus", "solo"]},
                 "right": [{"kind": "tag", "value": x} for x in
                           ["multiple others(多人(其他))", "multiple others", "crowd",
                            "group", "large group", "small group", "everyone",
                            "couple", "pair", "trio", "quartet", "2girls", "3girls",
                            "4girls", "5girls", "6+girls", "2boys", "3boys",
                            "multiple girls", "multiple boys", "1girl and 1boy"]],
                 "type": "mutex", "enabled": True, "priority": 100,
                 "scope": ["auto", "manual_fill"], "params": {}})
if newr:
    rules.extend(newr)
    tagconflicts.save_rules(rules)
    print(f"cross 新增 {len(newr)}: {[r['id'] for r in newr]}")

# ---- 4) 脏词 en 修形: multiple others(多人(其他)) → multiple others (zh 归位)
# (直接改库文件三份 + backups, 保持同步规矩)
import shutil
paths = [library.USER_PATH, library.DEFAULT_PATH]
backup_dir = os.path.join(os.path.dirname(library.USER_PATH), "backups")
for bn in ("factory_backup.json", "user_backup.json"):
    bp = os.path.join(backup_dir, bn)
    if os.path.exists(bp):
        paths.append(bp)
fixed = 0
for p in paths:
    if not os.path.exists(p):
        continue
    d = json.load(open(p, encoding="utf-8"))
    ch = 0
    for c in d.get("categories", []):
        for s in c.get("subcategories", []):
            for t in s.get("tags", []) or []:
                en = str(t.get("en", ""))
                if "multiple others(" in en:
                    t["en"] = "multiple others"
                    t["zh"] = "多人（其他）"
                    ch += 1
    if ch:
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        fixed += ch
        print(f"  {os.path.basename(p)}: 修 {ch} 处")
print(f"脏词修复共 {fixed}")
