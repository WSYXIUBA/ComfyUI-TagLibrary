"""M3: NL 尾段编译 golden 测试。

python tests/m3_nl_test.py            → 全量断言
python tests/m3_nl_test.py --show     → 打印样本供人工眼评 (反拼接律)
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library            # noqa: E402
import runtime_snapshot   # noqa: E402
import nl                 # noqa: E402
import engine             # noqa: E402
from nodes import TagLibraryNode  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
node = TagLibraryNode()

PIN_KATANA_RAIN = json.dumps({
    "tags": [{"en": e, "pinned": True} for e in
             ("1girl", "katana", "rain", "night", "looking at viewer")],
    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1})

# ---- G1 结构断言 (500 seed)
print("G1 输出结构")
bad = 0
samples = []
for seed in range(500):
    r = node.build(PIN_KATANA_RAIN, "auto", seed)
    text = r["result"][0] if isinstance(r, dict) else r[0]
    if "." not in text:
        bad += 1
        continue
    tail = text.split(", ", 6)[-1]
    # 句子以大写开头且含句号
    m = re.search(r"([A-Z][^.!?]+[.!?](?:\s|$))+", text)
    if not m:
        bad += 1
    if len(samples) < 8:
        samples.append((seed, text))
check("500 seed 全部产出 NL 句", bad == 0, str(bad))

# ---- G2 反拼接律1: 不重念主语 (连续两句不能都以 She 开头)
print("G2 主语回指")
rep = 0
for seed in range(500):
    r = node.build(PIN_KATANA_RAIN, "auto", seed)
    text = r["result"][0] if isinstance(r, dict) else r[0]
    sents = re.findall(r"[A-Z][^.!?]*[.!?]", text)
    starts = [s.split()[0] for s in sents if " " in s]
    for i in range(1, len(starts)):
        if starts[i] == starts[i - 1] == "She":
            rep += 1
            break
check("零连续 She 开头", rep == 0, str(rep))

# ---- G3 句式变体轮换 (换 seed 换写法)
print("G3 变体轮换")
tails = set()
for seed in range(60):
    r = node.build(PIN_KATANA_RAIN, "auto", seed)
    text = r["result"][0] if isinstance(r, dict) else r[0]
    m = re.search(r"([A-Z][^.!?]+[.!?](?:\s|$))+", text)
    if m:
        tails.add(m.group(0).strip())
check("60 seed ≥ 8 种尾段写法", len(tails) >= 8, str(len(tails)))

# ---- G4 同 seed 确定性
print("G4 确定性")
a = node.build(PIN_KATANA_RAIN, "auto", 101)["result"][0]
b = node.build(PIN_KATANA_RAIN, "auto", 101)["result"][0]
check("同 seed 全文一致", a == b)

# ---- G5 nl_tail 开关
print("G5 开关")
off = json.dumps({**json.loads(PIN_KATANA_RAIN), "nl_tail": False})
t = node.build(off, "auto", 5)["result"][0]
check("nl_tail=false → 无句号段", "." not in t, t[-40:])

# ---- G6 宾语正确: 刀句不能出现 rifle/pistol 词 (直接测 compile_tail, 不误伤 tags)
print("G6 宾语档案一致")
wrong_obj = 0
for seed in range(200):
    res = engine.run_auto(snap, json.loads(PIN_KATANA_RAIN), seed, nsfw_on=False,
                          avoid_conflicts=True, search_text="", cat_weights=None,
                          config=None)
    tail = nl.compile_tail(snap, res.picks, seed).lower()
    sents = re.findall(r"[a-z][^.!?]*\.", tail)
    for s in sents:
        if ("katana" in s or "blade" in s) and any(
                w in s for w in (" rifle", " pistol", " a bow")):
            wrong_obj += 1
check("200 seed 零宾语错档", wrong_obj == 0, str(wrong_obj))

# ---- G7 代词跟随 count
print("G7 人称一致")
p_boy = json.dumps({"tags": [{"en": "1boy", "pinned": True},
                             {"en": "gun", "pinned": True}],
                    "fill_master": True, "fill_master_min": 1, "fill_master_max": 1})
he = she = 0
for seed in range(100):
    text = node.build(p_boy, "auto", seed)["result"][0]
    if re.search(r"\bHe\b|\bhis\b", text):
        he += 1
    if re.search(r"\bShe\b|\bher\b", text):
        she += 1
check("1boy 样本用 He/his", he > 0 and she == 0, f"he={he} she={she}")

# ---- 占位符契约: 动作句那条路只替换 {O} (nl.py 步骤3), {S}/{POS} 由 fill() 补。
#      pose_map 指向的族里若混进 {C}/{A}/{E1} (那是"补头句"专用的), 动作句就会把
#      占位符原样吐进 prompt —— 例如把某个姿势词映到 wear 族。
F = nl.load_flavors()
_fam, _pm = F.get("families") or {}, F.get("pose_map") or {}
leak = []
for _w, _f in _pm.items():
    for _s in _fam.get(_f) or []:
        _bad = set(re.findall(r"\{([A-Z0-9]+)\}", _s)) - {"S", "POS", "O"}
        if _bad:
            leak.append(f"{_w} -> {_f} {sorted(_bad)}")
check("pose_map 目标族只含 {S}/{POS}/{O}", not leak, str(leak[:4]))

# ---- 展示
if "--show" in sys.argv:
    print("\n---- 样本 (人工眼评) ----")
    for seed, s in samples[:6]:
        print(f"[seed {seed}] {s}\n")

print()
if FAILS:
    print(f"❌ M3 FAILED: {FAILS}")
    sys.exit(1)
print("✅ M3 NL ALL PASS")
