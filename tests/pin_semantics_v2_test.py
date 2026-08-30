"""钉选语义 v2 单测 (纯后端, 不起浏览器):

用户拍板语义:
  B. 钉选优先 — 排除类目拦不住钉选词
  钉选占用所在子类目配额 — 1~1 时钉 1 个 → 该子类目不再出词
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library as L
import random_engine as RE
import runtime_snapshot

lib = L.get_merged()
snap = runtime_snapshot.get_snapshot(lib)

def find_tag(en_l):
    tid = snap.en_to_id.get(en_l)
    assert tid is not None, f"tag {en_l} not in lib"
    return tid

def run(state, seed=42):
    return RE.run_auto(snap, state, seed, nsfw_on=False, avoid_conflicts=True,
                       search_text="", cat_weights=None, config={"engine": "fast"},
                       recent_sets=[])

def ids_text(res):
    return [snap.tag_text[i] for i in list(res.fixed_ids) + list(res.rest_ids)]

def subs_of(res):
    out = {}
    for i in list(res.fixed_ids) + list(res.rest_ids):
        si = snap.sub_of[i]
        out.setdefault(snap.sub_names[si], []).append(snap.tag_text[i])
    return out

# --- 准备: 找表情情绪子分类里的一个词 ---
EXPRESSION_SUB = None
for si, name in enumerate(snap.sub_names):
    if "表情" in name:
        EXPRESSION_SUB = si
        break
assert EXPRESSION_SUB is not None, "no expression sub found"
expr_tags = [snap.tag_text[i] for i in snap.pools[EXPRESSION_SUB]][:3]
print("expression sub:", snap.sub_names[EXPRESSION_SUB], "candidates:", expr_tags)

pin_word = expr_tags[0].lower()
pin_id = find_tag(pin_word)

# ================= T1: 钉选占配额 (1~1) =================
state = {
    "tags": [{"en": pin_word, "pinned": True, "enabled": True}],
    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
    "exclude_categories": [],
}
res = run(state)
subs = subs_of(res)
sub_name = snap.sub_names[EXPRESSION_SUB]
got = subs.get(sub_name, [])
assert got == [expr_tags[0]], f"T1 FAIL: expression sub should be exactly the pinned word, got {got}"
others = {k: v for k, v in subs.items() if k != sub_name}
assert others, "T1 FAIL: other subs produced nothing"
print("T1 PASS: pinned word occupies the sole 1~1 slot; other subs still fill:", len(others), "subs")

# ================= T2: 排除类目拦不住钉选 (B) =================
cat_name = snap.cat_names[snap.cat_of_sub[EXPRESSION_SUB]]
state2 = {
    "tags": [{"en": pin_word, "pinned": True, "enabled": True}],
    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
    "exclude_categories": [cat_name],
}
res2 = run(state2)
txt = ids_text(res2)
assert expr_tags[0] in txt, f"T2 FAIL: pinned word should survive exclusion, got {txt[:10]}"
# 其余该大类词不应出现 (排除生效)
cat_subs = [si for si in range(len(snap.sub_names)) if snap.cat_names[snap.cat_of_sub[si]] == cat_name]
for si in cat_subs:
    for i in snap.pools[si]:
        w = snap.tag_text[i]
        if w != expr_tags[0]:
            assert w not in txt, f"T2 FAIL: excluded cat produced extra word {w}"
print(f"T2 PASS: pinned '{expr_tags[0]}' survives excluded cat '{cat_name}', no other words from it")

# ================= T3: 2~3 范围扣减 =================
state3 = {
    "tags": [{"en": pin_word, "pinned": True, "enabled": True}],
    "fill_master": True, "fill_master_min": 2, "fill_master_max": 3,
    "exclude_categories": [],
}
res3 = run(state3)
subs3 = subs_of(res3)
got3 = subs3.get(sub_name, [])
assert got3[0] == expr_tags[0] and 2 <= len(got3) <= 3, f"T3 FAIL: expect pinned + 1~2 extra (total 2~3), got {got3}"
print("T3 PASS: 2~3 with 1 pin -> pinned +", len(got3) - 1, "extra:", got3)

# ================= T4: 钉 3 个 1~1 → 该子类目完全跳过 =================
pins = expr_tags[:3] if len(expr_tags) >= 3 else expr_tags
state4 = {
    "tags": [{"en": w.lower(), "pinned": True, "enabled": True} for w in pins],
    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
    "exclude_categories": [],
}
res4 = run(state4)
subs4 = subs_of(res4)
got4 = subs4.get(sub_name, [])
assert got4 == pins, f"T4 FAIL: expect exactly the 3 pins, got {got4}"
print("T4 PASS: 3 pins in 1~1 sub -> sub skipped, only pins remain")

# ================= T5: 非钉选普通词不受影响 =================
state5 = {
    "tags": [{"en": "masterpiece", "pinned": False, "enabled": True}],
    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
    "exclude_categories": [],
}
res5 = run(state5)
subs5 = subs_of(res5)
assert subs5.get(sub_name), "T5 FAIL: expression sub empty without pins"
print("T5 PASS: no pins -> normal fill")

print("\nALL PIN SEMANTICS TESTS PASS")
