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

# ---- 句式语法契约 (2026-09-23 真机出图审查补): {S} 后面那个词必须是**动词基础形**。
#      _render_subject 把 {S} 后第一个词当动词做三单 —— 模板写成 "holds"/"grips"/
#      "features" 这种已三单的形, 渲染出来就是 "She holdses / She featureses" 直接进
#      正面提示词 (真机出图 43 张里抓到 7 条)。同时禁止 {S} {POS} 连写 (渲染成 "She her")。
_BASE_S_VERBS = {"pass", "focus", "kiss", "cross", "miss", "press", "dress",
                 "guess", "discuss", "bless", "address", "express", "possess",
                 "assess", "confess", "stress", "process", "witness", "gas"}
# {S} 后面跟着这些名词时, 那个名词才是句子主语 (模板应写 {POS})
_SUBJ_NOUNS = {"gaze", "stare", "expression", "voice", "breath", "smile", "eyes",
               "hand", "hands", "body", "face", "hair", "skin", "lips", "fingers",
               "shoulder", "shoulders", "posture", "silhouette", "presence", "heart"}
_tpl_bad, _n_tpl = [], 0
_groups = [(f"families/{k}", v) for k, v in (F.get("families") or {}).items()]
_groups += [(f"{k}/{kk}", v) for k in ("intro", "env", "light")
            for kk, v in (F.get(k) or {}).items()]
for _fam, _verses in _groups:
    for _t in _verses:
        if not isinstance(_t, str):
            continue
        _n_tpl += 1
        # ⚠ 每一个 {S} 都要查, 不能只查句首 —— 句中 {S} 同样会被做三单。实测
        #   "A soft gasp escapes as {S} pulls ..." 句首正则漏掉, 渲染成 "she pullses"。
        for _m in re.finditer(r"\{S\}\s+(\w+)", _t):
            _v = _m.group(1)
            if _v.endswith("s") and _v not in _BASE_S_VERBS and nl._v3s(_v) == _v + "es":
                _tpl_bad.append(f"{_fam}: {_v} -> {nl._v3s(_v)}")
        # {S} 后面跟"名词+已三单动词" = 模板把主格当限定词用了, 该写 {POS}。
        # 实测 "{S} gaze turns heavy-lidded" -> "She gazes turns heavy-lidded"。
        for _m in re.finditer(r"\{S\}\s+([a-z]{3,})\s+([a-z]+(?:s|es))\b", _t):
            if _m.group(1) in _SUBJ_NOUNS:
                _tpl_bad.append(f"{_fam}: {{S}} {_m.group(1)} {_m.group(2)} (应为 {{POS}})")
        if "{S} {POS}" in _t:
            _tpl_bad.append(f"{_fam}: 重复主语 S+POS")
        _r = nl._render_subject(_t, "She", True).replace("{POS}", "her")
        if re.search(r"\bShe\s+her\b", _r):
            _tpl_bad.append(f"{_fam}: 渲染重复主语 -> {_r[:44]}")
check(f"NL 句式语法契约 ({_n_tpl} 条)", not _tpl_bad, str(_tpl_bad[:4]))

# ---- G8 单人场景契约 (2026-09-23): 单人锁下 NL 不许把"第二个人"写进正面提示词 ——
#      实测 solo 与 "as she pulls her partner closer" 同框, 真机直接出 2girls。
print("G8 单人场景不写第二人")
_solo_state = json.loads(PIN_KATANA_RAIN)
_solo_state.update({"solo_lock": True, "nsfw": "on"})
_pt = _pn = 0
for seed in range(200):
    _res = engine.run_auto(snap, _solo_state, seed, nsfw_on=True,
                          avoid_conflicts=True, search_text="", cat_weights=None,
                          config=None)
    _tail = nl.compile_tail(snap, _res.picks, seed).lower()
    _pn += 1 if _tail else 0
    if any(h in _tail for h in ("partner", "another", "shared", "bodies")):
        _pt += 1
check(f"单人场景零第二人句 ({_pn} 条尾段)", _pt == 0, str(_pt))

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
