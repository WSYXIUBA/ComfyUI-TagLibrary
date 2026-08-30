# -*- coding: utf-8 -*-
"""阶段6验收: 自动模式批量出词质检 (真实库, 沙箱只读, 不写盘)。

跑法: python tests/phase6_auto_quality_test.py [N] [--engine fast|smart|both]

检查维度:
  1. 冲突泄漏: 每次出词的结果里, 同一冲突组的标签只能出现 1 个 (strict 组全查,
     non-strict 组只查组内两两都有明确互斥语义的 — 即让位机制实际生效的)
  2. 语义对冲: 手写对冲词表 (二值对立: 裸露↔衣服已由规则管, 这里查规则外的)
  3. 组合质量: 每词输出 标签数分布 / 分类覆盖 / 重复组合率
"""

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import library  # noqa: E402
from runtime_snapshot import RuntimeSnapshot  # noqa: E402
import random_engine  # noqa: E402

N_RUNS = 50

# ---------- 沙箱化: 只读真实库, 但不碰热同步 ----------
library.HOT_SYNC_MIN_INTERVAL = 1e9
try:
    import tagfiles
    tagfiles.LIBRARY_DIR = os.path.join(ROOT, "data", "taglib")  # 只读
except Exception:
    pass

# 手写语义对冲表 (规则文件没覆盖的硬对冲; en 全小写)
SEMANTIC_CLASH = [
    ({"sunny", "clear sky", "daytime", "noon"}, {"night", "midnight", "starry sky"}),
    ({"summer", "spring (season)"}, {"winter", "snowing", "blizzard"}),
    ({"indoors"}, {"outdoors"}),
    ({"underwater"}, {"on fire"}),
    ({"sleeping", "sleepy", "yawning"}, {"excited", "furious", "dancing"}),
]


def load_everything():
    merged = library.get_merged()
    snap = __import__("runtime_snapshot").build_snapshot(merged)
    return snap


def conflict_groups_of(snap):
    """从 snap.conflict_map 还原连通分量 = 互斥组。"""
    seen, comps = set(), []
    for start in snap.conflict_map:
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(snap.conflict_map.get(x, ()))
        seen |= comp
        comps.append(frozenset(comp))
    return comps


def en_of(snap, tid):
    return snap.tag_lower[tid]


def main():
    engine_mode = "both"
    n = N_RUNS
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        n = int(args[0])
    if "--fast" in sys.argv:
        engine_mode = "fast"
    elif "--smart" in sys.argv:
        engine_mode = "smart"

    snap = load_everything()
    comps = conflict_groups_of(snap)
    print(f"库标签 {len(snap.tag_lower)} | 冲突连通分量 {len(comps)} | 引擎 {engine_mode} | runs {n}")

    engines = ["fast", "smart"] if engine_mode == "both" else [engine_mode]
    all_fail = 0
    combo_counter = Counter()
    tag_freq = Counter()
    len_stats = {e: [] for e in engines}

    for eng in engines:
        leaks = []
        semantic = []
        for seed in range(1, n + 1):
            state = {
                "tags": [],
                "fill_master": True, "fill_master_min": 1, "fill_master_max": 2,
                "exclude_categories": [],
            }
            cfg = {"engine": eng} | ({"diversity": 0.7, "avoid_recent": 3} if eng == "smart" else {})
            r = random_engine.run_auto(snap, state, seed, nsfw_on=False, config=cfg)
            ids = list(r.fixed_ids) + list(r.rest_ids)
            ens = [en_of(snap, i) for i in ids]
            combo_counter[tuple(sorted(ens))] += 1
            tag_freq.update(ens)
            len_stats[eng].append(len(ens))

            # 1. 规则冲突: strict 组内 ≥2 即泄漏
            for comp in comps:
                hits = [e for e in ens if any(x == e for x in comp)]
                if len(hits) > 1:
                    leaks.append((seed, eng, hits))
            # 2. 语义对冲
            for a_side, b_side in SEMANTIC_CLASH:
                ha = [e for e in ens if e in a_side]
                hb = [e for e in ens if e in b_side]
                if ha and hb:
                    semantic.append((seed, eng, ha + hb))

        # 输出
        print(f"\n===== {eng} =====")
        print(f"规则冲突泄漏: {len(leaks)} 次 / {n}")
        for s, e, h in leaks[:10]:
            print(f"  seed{s}: {h}")
        print(f"语义对冲: {len(semantic)} 次 / {n}")
        for s, e, h in semantic[:10]:
            print(f"  seed{s}: {h}")
        all_fail += len(leaks)

        ls = sorted(len_stats[eng])
        p50 = ls[len(ls)//2]
        print(f"出词长度: min{ls[0]} p50 {p50} max{ls[-1]}")
        # 分类覆盖: 抽样看一次
        state = {"tags": [], "fill_master": True, "fill_master_min": 1,
                 "fill_master_max": 2, "exclude_categories": []}
        r = random_engine.run_auto(snap, state, 42, nsfw_on=False,
                                   config={"engine": eng})
        ids = list(r.fixed_ids) + list(r.rest_ids)
        cats = Counter()
        for i in ids:
            cats[snap.cat_names[snap.cat_of_sub[snap.sub_of[i]]]] += 1
        print("seed42 分类覆盖:", dict(cats))

    # 组合多样性
    total = sum(combo_counter.values())
    uniq = len(combo_counter)
    print(f"\n组合多样性: {uniq} unique / {total} runs = {uniq/total:.0%}")
    top_dup = [c for c in combo_counter.most_common(3)]
    for c, k in top_dup:
        print(f"  重复 {k} 次: {', '.join(c[:8])}...")

    # 标签使用率 (长尾检查: 是否一堆标签永远抽不到 — spawn_rate=1 时应基本均匀)
    print(f"标签使用: {len(tag_freq)} 个标签至少出现 1 次")
    dead = 0
    for si in range(len(snap.sub_names)):
        for tid in snap.pools[si]:
            if tag_freq.get(snap.tag_lower[tid], 0) == 0:
                dead += 1
    print(f"从未抽中的池内标签: {dead} (排除/NSFW 关闭过滤外的应为 0)")

    verdict = "PASS ✅" if all_fail == 0 else f"FAIL ❌ ({all_fail} 泄漏)"
    print("\n== 质检:", verdict)
    return 0 if all_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
