"""质量审计 v2: 30 条完整提示词 + 修正后的断言 (solo 才锁性别; 束率按整体统计)。"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library            # noqa: E402
import runtime_snapshot   # noqa: E402
import engine             # noqa: E402
import nl                 # noqa: E402

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
WEAPONS = {w.lower() for p in snap.profiles for w in p.tags}
SOLO_F = {"1girl"}
SOLO_M = {"1boy"}
MALE = {"2boys", "3boys", "multiple boys", "teenage boy", "mature male",
        "young boy", "old man", "shota", "prince", "king", "waiter", "postman",
        "policeman", "policeman", "conductor", "adult male", "incubus",
        "grandfather", "boy", "grown man", "silver fox", "mature male"}
FEMALE = {"2girls", "3girls", "multiple girls", "milf", "teenage girl",
          "schoolgirl", "maid girl", "elf girl", "catgirl", "doggirl", "mermaid",
          "valkyrie", "princess", "queen", "waitress", "adult female", "loli",
          "girl", "young woman", "cougar", "granny", "succubus", "witch"}
# 衔物嘴域 (mouth-hold): 与开口/进食/吸烟类表情动作全互斥
MOUTH_HOLD = {"sword out of mouth", "food in mouth", "cigarette in mouth",
              "straw in mouth", "object in mouth", "knife in mouth",
              "flower in mouth", "popsicle in mouth", "thermometer",
              "biting lip", "biting tongue", "cigarette", "eating", "drinking",
              "open mouth", "mouth hold", "licking", "kiss", "blowing kiss",
              "whistling", "smoking", "bubblegum", "fangs out", "showing teeth"}
MOUTH_CLASH = [("sword out of mouth", "biting lip"), ("sword out of mouth", "open mouth"),
               ("food in mouth", "sword out of mouth")]

SCENARIOS = [
    ("刀+雨夜+看镜头", {"tags": [{"en": "1girl", "pinned": True},
        {"en": "katana", "pinned": True}, {"en": "rain", "pinned": True},
        {"en": "night", "pinned": True}, {"en": "looking at viewer", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}),
    ("双枪少女", {"tags": [{"en": "1girl", "pinned": True},
        {"en": "dual pistols", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}),
    ("草原长杖", {"tags": [{"en": "1girl", "pinned": True},
        {"en": "staff", "pinned": True}, {"en": "forest", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}),
    ("少年剑士", {"tags": [{"en": "1boy", "pinned": True},
        {"en": "sword", "pinned": True}],
        "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}),
    ("无钉纯随机A", {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3}),
    ("无钉纯随机B", {"fill_master": True, "fill_master_min": 1, "fill_master_max": 2}),
]

problems = []
bundle_stat = [0, 0]  # 出武器次数, 其中带束次数


def _fixed_hash(s: str) -> int:
    return sum(ord(c) * (i + 7) for i, c in enumerate(s)) % 100000


print("=" * 100)
SEEDS_PER_SCEN = int(os.environ.get("QA_SEEDS", "5"))
for name, state in SCENARIOS:
    for seed in range(SEEDS_PER_SCEN):
        res = engine.run_auto(snap, state, seed * 97 + _fixed_hash(name),
                              nsfw_on=False, avoid_conflicts=True,
                              search_text="", cat_weights=None,
                              config={"bundle_pose_prob": 1.0})
        tail = nl.compile_tail(snap, res.picks, seed)
        tags = ", ".join(p.en for p in res.picks)
        text = tags + ((". " + tail) if tail else "")
        ens = {p.en.lower() for p in res.picks}

        # a) solo 性别锁: 1girl 场不出男词 / 1boy 场不出女词
        if ens & SOLO_F and (ens & MALE):
            problems.append((name, seed, "solo女场出男词", sorted(ens & MALE)[:4]))
        if ens & SOLO_M and (ens & FEMALE):
            problems.append((name, seed, "solo男场出女词", sorted(ens & FEMALE)[:4]))
        # b2) 出口组交集复核: 任意两词 (含 ext 词按 en_groups) 不得共享互斥域
        gmap = []
        for p in res.picks:
            if p.id is not None:
                g = snap.group_sets[p.id]
            else:
                g = snap.en_groups.get(p.en.lower(), frozenset())
            gmap.append((p.en, g))
        for i in range(len(gmap)):
            for j in range(i + 1, len(gmap)):
                if gmap[i][1] & gmap[j][1]:
                    problems.append((name, seed, "组交集漏网",
                                     [gmap[i][0], gmap[j][0]]))
                    break
        # c) hands 账本
        h = sum(p.hands for p in res.picks)
        if h > 2:
            problems.append((name, seed, f"hands={h}", ""))
        # d) 束率统计
        if ens & WEAPONS:
            bundle_stat[0] += 1
            if any(p.kind == "ext" and p.source == "bundle" for p in res.picks):
                bundle_stat[1] += 1

        rate_note = ""
        if seed < 5:
            print(f"### {name} seed{seed}")
            print(text[:520] + ("…" if len(text) > 520 else ""))
            print()

rate = bundle_stat[1] / max(bundle_stat[0], 1)
print(f"束出生率: {bundle_stat[1]}/{bundle_stat[0]} = {rate:.0%}")
if rate < 0.95:
    problems.append(("束率", "", f"{rate:.0%} < 95%", ""))

print("=" * 100)
if problems:
    print(f"❌ 发现 {len(problems)} 处问题:")
    for p in problems[:20]:
        print("   ", p)
    sys.exit(1)
print("✅ 30 条全断言通过")
