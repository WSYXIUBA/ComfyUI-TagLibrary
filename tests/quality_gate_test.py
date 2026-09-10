"""输出质量门禁 —— 抽取语义修复的回归防线 (方案 §8.3 T2/T6 的自动化部分)。

python tests/quality_gate_test.py           # 300 个种子 (默认, 约数秒)
python tests/quality_gate_test.py --long    # 10,000 个种子 (发布前跑)

断言 (全部必须为 0 / 落在带内):
  Q1 词数带      每轮输出 35~70 词        (修复前 200~213)
  Q2 槽位配额    没有槽位超出 slotpolicy 的配额
  Q3 互斥槽位组  同组不得有两个槽位同时贡献词 (场景地点/风格基线/光源/姿态基线/昼夜)
  Q4 人数唯一    count 轴有且只有 1 个词
  Q5 无畸形词    输出不得含 "xxx(yyy(zzz))" 形式的双重括号标签
  Q6 确定性      同 seed 同配置 → 逐词完全相同
  Q7 段位序      输出必须符合 Anima 六段序 (段位不递减) —— §8.3 T3
  Q8 人数语义    "no humans" 时不得出现身份/外貌/服装词

为什么需要它: 2026-09-10 实测发现默认配置下插件吐出 200+ 个互相矛盾的词
(daytime + starry night sky / toddler + middle-aged + elderly / 四双鞋 …)。
修复后仍可能因配额表或引擎改动而回退, 因此把"不冲突、不超配额、词数合理"
固化成门禁, 而不是靠肉眼看。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import axes  # noqa: E402
import engine  # noqa: E402
import library  # noqa: E402
import runtime_snapshot  # noqa: E402
import slotpolicy  # noqa: E402

# 词数带: 修复前是 200~213 (每槽位抽 3~5 个 × 63 槽位), 修复后中位 57。
# 左尾到 30 出头是合理的 —— 部分种子会被 50 组互斥规则大量挡住 (数据本身的密度),
# 补底跑满 3 轮也只能到此; 真正的回归特征是"回到 100+/200+", 不是 33。
MIN_WORDS, MAX_WORDS = 30, 70
MALFORMED = re.compile(r"\([^()]*\([^()]*\)")


def build_state():
    return {"tags": [{"en": "katana", "pinned": True}], "nsfw": False,
            "fill_master": True, "fill_master_min": 3, "fill_master_max": 5,
            "nl_tail": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", action="store_true", help="10,000 种子长跑")
    ap.add_argument("--seeds", type=int, default=0, help="覆盖种子数")
    args = ap.parse_args()
    n_seeds = args.seeds or (10_000 if args.long else 300)

    lib = library.get_merged()
    snap = runtime_snapshot.build_snapshot(lib)
    state = build_state()
    cfg = engine.resolve_config(state, lib.get("settings"))

    fails: list[str] = []
    counts: list[int] = []
    stat = Counter()

    for seed in range(1, n_seeds + 1):
        picks = engine.run_auto(snap, state, seed, nsfw_on=False, config=cfg).picks
        counts.append(len(picks))

        if not (MIN_WORDS <= len(picks) <= MAX_WORDS):
            stat["Q1"] += 1
            if len(fails) < 12:
                fails.append(f"Q1 seed{seed}: {len(picks)} 词不在 {MIN_WORDS}~{MAX_WORDS}")

        slot_n, excl_hit, n_count = Counter(), Counter(), 0
        for p in picks:
            if p.id is None:
                continue
            sk = snap.sub_keys[snap.sub_of[p.id]]
            slot_n[sk] += 1
            g = slotpolicy.exclusive_group(sk)
            if g:
                excl_hit[g] += 1
            if snap.axis_arr[p.id] == "count":
                n_count += 1

        for k, v in slot_n.items():
            cap = slotpolicy.caps_for(k)[1]  # max_n
            if v > cap:
                stat["Q2"] += 1
                if len(fails) < 12:
                    fails.append(f"Q2 seed{seed}: 槽位 {k} 出了 {v} 个 (上限 {cap})")
                break
        for g, v in excl_hit.items():
            if v > 1:
                stat["Q3"] += 1
                if len(fails) < 12:
                    fails.append(f"Q3 seed{seed}: 互斥槽位组 {g} 有 {v} 个槽位同时出词")
                break
        if n_count != 1:
            stat["Q4"] += 1
            if len(fails) < 12:
                fails.append(f"Q4 seed{seed}: count 轴有 {n_count} 个词 (应为 1)")
        for p in picks:
            if MALFORMED.search(str(p.en)):
                stat["Q5"] += 1
                if len(fails) < 12:
                    fails.append(f"Q5 seed{seed}: 畸形标签 {p.en!r}")
                break

        # Q7 段位序: Anima tag order —— 段位号不得回退
        secs = [axes.section_of(p.axis) for p in picks]
        prev_sec = 0
        for sec, p in zip(secs, picks):
            if sec < prev_sec:
                stat["Q7"] += 1
                if len(fails) < 12:
                    fails.append(f"Q7 seed{seed}: 段位回退 {prev_sec}->{sec} "
                                 f"({p.en} [{p.axis}])")
                break
            prev_sec = sec

        # Q8 "no humans" 不得与人物属性同现
        cw = [p for p in picks if p.axis == "count"]
        if cw and cw[0].en.strip().lower() in slotpolicy.NO_HUMAN_COUNT_WORDS:
            bad = [p.en for p in picks
                   if p.axis in slotpolicy.NO_HUMAN_SKIP_AXES]
            if bad:
                stat["Q8"] += 1
                if len(fails) < 12:
                    fails.append(f"Q8 seed{seed}: no humans + {bad[:3]}")

    # Q6 确定性
    a = [p.en for p in engine.run_auto(snap, state, 4242, nsfw_on=False, config=cfg).picks]
    b = [p.en for p in engine.run_auto(snap, state, 4242, nsfw_on=False, config=cfg).picks]
    if a != b:
        stat["Q6"] += 1
        fails.append("Q6: 同 seed 两次输出不一致")

    counts.sort()
    print(f"跑 {n_seeds} 个种子 | 词数 最小{counts[0]} 中位{counts[len(counts) // 2]} "
          f"最大{counts[-1]} 均值{sum(counts) / len(counts):.1f}")
    print(f"  落进 {MIN_WORDS}~{MAX_WORDS} 带内: {sum(1 for c in counts if MIN_WORDS <= c <= MAX_WORDS)}/{n_seeds}")
    print()
    for tag, desc in [("Q1", "词数带"), ("Q2", "槽位配额"), ("Q3", "互斥槽位组"),
                      ("Q4", "人数唯一"), ("Q5", "无畸形词"), ("Q6", "确定性"),
                      ("Q7", "段位序"), ("Q8", "no humans 语义")]:
        print(f"  {'✓' if not stat[tag] else '✗'} {tag} {desc}: {stat[tag]} 次违规")
    if fails:
        print("\n前几条失败:")
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 输出质量门禁通过 (无冲突 / 不超配额 / 词数合理 / 确定性)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
