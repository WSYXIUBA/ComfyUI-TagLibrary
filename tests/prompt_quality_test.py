"""完整提示词重度测试 —— 在**最终提示词文本**层面做质量断言。

与 quality_gate_test 的分工:
  · quality_gate_test: 查**抽取结果**(Pick) 的结构属性 —— 配额/互斥组/人数/畸形词/段位。
  · 本测试 (prompt_quality_test): 把结果按节点的真实拼装方式合成**最终提示词**,
    再对那段文本做语义断言 —— 这才是用户真正看到/喂给模型的东西。

为什么需要它: 结构全对 ≠ 文本没问题。例如两处看似无关的槽位可能产出语义冲突
(写实摄影 + 二次元向), 或者负向提示词的词不小心漏进正片段。

用法:
    python tests/prompt_quality_test.py            # 200 个种子, 打印 3 条样本
    python tests/prompt_quality_test.py --long     # 5,000 个种子
    python tests/prompt_quality_test.py --samples 8
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
import nl  # noqa: E402
import runtime_snapshot  # noqa: E402

MIN_WORDS, MAX_WORDS = 28, 72

# 语义互斥对 (高置信, 人工整理) —— 出现在同一段正向提示词里即为矛盾。
# 结构层已有互斥槽位组/配额拦一部分, 这里在**文本层**端到端复核。
CONTRADICTIONS: list[tuple[str, str, str]] = [
    ("写实与二次元并存", "realistic", "anime style"),
    ("写实与二次元并存", "photorealistic", "manga style"),
    ("室内与自然景观并存", "indoors", "outdoors"),
    ("室内与室外自然并存", "indoor", "mountain"),
    ("白天与夜晚并存", "daytime", "night"),
    ("白天与星空并存", "daytime", "starry sky"),
    ("白天与满月并存", "daytime", "full moon"),
    ("昼夜与月并存", "afternoon", "moon"),
    ("站立与坐姿并存", "standing", "sitting"),
    ("站立与躺下并存", "standing", "lying"),
    ("俯视与仰视并存", "from above", "from below"),
    ("笑脸与哭脸并存", "smile", "crying"),
    ("张嘴与闭嘴并存", "open mouth", "closed mouth"),
    ("长发与短发并存", "long hair", "short hair"),
    ("大胸与小胸并存", "large breasts", "small breasts"),
    ("大胸与小胸并存", "huge breasts", "flat chest"),
    ("粗腿与细腿并存", "thick thighs", "thin thighs"),
    ("看向镜头与移开视线并存", "looking at viewer", "looking away"),
    ("睁眼与闭眼并存", "open eyes", "closed eyes"),
    ("伸舌与闭嘴并存", "tongue out", "closed mouth"),
    ("雨与雪并存", "rain", "snow"),
    ("赤足与鞋并存", "barefoot", "high heels"),
    ("赤足与靴并存", "bare feet", "boots"),
    ("全裸与穿着并存", "nude", "school uniform"),
    # 未成年 × 成人内容 (1.7.0: 引擎已做词级锁定, 这里文本层端到端复核)
    ("未成年与裸露并存", "toddler", "nude"),
    ("未成年与内衣并存", "preteen", "panties"),
    ("未成年与泳装并存", "child", "swimsuit"),
    ("未成年与成人氛围并存", "teenage girl", "erotic mood"),
]

# 负向提示词的词绝不该出现在正片段 (Anima 官方负向模板里的那些)
NEGATIVE_LEAK = [
    "worst quality", "low quality", "jpeg artifacts", "blurry",
    "bad anatomy", "bad hands", "bad feet", "extra digits", "watermark",
    "score_1", "score_2", "score_3",
]

MALFORMED = re.compile(r"\([^()]*\([^()]*\)")


def build_state(nl_on: bool):
    return {"tags": [{"en": "katana", "pinned": True}], "nsfw": False,
            "fill_master": True, "nl_tail": nl_on, "separator": "comma"}


def build_prompt(snap, state, seed: int, cfg) -> tuple[str, list]:
    """完全按 nodes.py 的拼装方式生成最终提示词: 标签段 + 空行 + NL 尾段。"""
    res = engine.run_auto(snap, state, seed, nsfw_on=False, config=cfg)
    sep = ", " if state.get("separator", "comma") == "comma" else " "
    tags_text = sep.join(p.en for p in res.picks)
    tail = ""
    if state.get("nl_tail", True):
        try:
            tail = nl.compile_tail(snap, res.picks, seed) or ""
        except Exception as e:  # noqa: BLE001
            tail = f"(NL 编译异常: {e})"
    full = tags_text + (("\n\n" + tail) if tail.strip() else "")
    return full, res.picks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", action="store_true")
    ap.add_argument("--seeds", type=int, default=0)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()
    n_seeds = args.seeds or (5000 if args.long else 200)

    lib = library.get_merged()
    snap = runtime_snapshot.build_snapshot(lib)
    stat = Counter()
    fails: list[str] = []
    counts: list[int] = []
    samples: list[str] = []

    for nl_on in (True, False):
        state = build_state(nl_on)
        cfg = engine.resolve_config(state, lib.get("settings"))
        for seed in range(1, n_seeds + 1):
            prompt, picks = build_prompt(snap, state, seed, cfg)
            tag_text = prompt.split("\n\n")[0]
            words = [w.strip() for w in tag_text.split(",") if w.strip()]
            low = [w.lower() for w in words]
            if nl_on:
                counts.append(len(words))

            tag = "NL" if nl_on else "纯标签"

            # P1 词数带
            if not (MIN_WORDS <= len(words) <= MAX_WORDS):
                stat[f"P1·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"P1({tag}) seed{seed}: {len(words)} 词不在 {MIN_WORDS}~{MAX_WORDS}")
            # P2 无重复
            dup = [w for w, c in Counter(low).items() if c > 1]
            if dup:
                stat[f"P2·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"P2({tag}) seed{seed}: 重复词 {dup[:3]}")
            # P3 无畸形词
            bad = [w for w in words if MALFORMED.search(w)]
            if bad:
                stat[f"P3·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"P3({tag}) seed{seed}: 畸形词 {bad[:2]}")
            # P4 语义互斥 (文本层端到端复核)
            for label, a, b in CONTRADICTIONS:
                if a in low and b in low:
                    stat[f"P4·{tag}"] += 1
                    if len(fails) < 15:
                        fails.append(f"P4({tag}) seed{seed}: {label} ({a} + {b})")
                    break
            # P5 段位序 (文本层: 段位号不得回退)
            prev = 0
            for p in picks:
                sec = axes.section_of(p.axis)
                if sec < prev:
                    stat[f"P5·{tag}"] += 1
                    if len(fails) < 15:
                        fails.append(f"P5({tag}) seed{seed}: 段位回退 {prev}->{sec} ({p.en})")
                    break
                prev = sec
            # P6 人数与性别一致
            cw = [p for p in picks if p.axis == "count"]
            if cw:
                g = cw[0].gender
                wrong = [p.en for p in picks if p.gender == ("female" if g == "male" else "male")]
                if g and wrong:
                    stat[f"P6·{tag}"] += 1
                    if len(fails) < 15:
                        fails.append(f"P6({tag}) seed{seed}: {cw[0].en} 与 {wrong[:2]} 冲突")
            # P7 NL 尾段存在且 >= 2 句
            if nl_on:
                tail = prompt.split("\n\n", 1)[1] if "\n\n" in prompt else ""
                n_sent = len([s for s in re.split(r"[.!?。！？]+", tail) if s.strip()])
                if n_sent < 2:
                    stat["P7"] += 1
                    if len(fails) < 15:
                        fails.append(f"P7 seed{seed}: NL 尾段只有 {n_sent} 句")
            # P8 负向词不得漏进正向
            leak = [w for w in NEGATIVE_LEAK if w in low]
            if leak:
                stat[f"P8·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"P8({tag}) seed{seed}: 负向词漏入 {leak}")
            # P9 NL 人称与人数词一致 (1.7.0: "large group + She has" 实测回归)
            if nl_on and cw and "\n\n" in prompt:
                tail = prompt.split("\n\n", 1)[1]
                exp_s = nl._PRONOUN.get(cw[0].en.strip().lower(), ("She", "her"))[0]
                forbidden = {"They": ("She", "He", "her", "his"),
                             "She": ("He", "his", "They"),
                             "He": ("She", "her", "They")}[exp_s]
                bad_p = [f for f in forbidden
                         if re.search(r"\b" + f + r"\b", tail)]
                if bad_p:
                    stat["P9"] += 1
                    if len(fails) < 15:
                        fails.append(f"P9 seed{seed}: 人数词 {cw[0].en!r} 应为 "
                                     f"{exp_s}, 尾段出现 {bad_p}")
            if not nl_on and len(samples) < args.samples and seed <= 5:
                samples.append(prompt)

    print(f"跑 {n_seeds} 种子 × 2 模式 (开/关 NL 尾段)")
    print(f"  开 NL 时词数: 最小 {min(counts)} / 中位 {sorted(counts)[len(counts) // 2]} / "
          f"最大 {max(counts)} / 均值 {sum(counts) / len(counts):.1f}")
    print()
    checks = [("P1", "词数带"), ("P2", "无重复词"), ("P3", "无畸形词"),
              ("P4", "语义互斥对不共现 (文本层)"), ("P5", "段位序不回退 (文本层)"),
              ("P6", "人数与性别一致"), ("P8", "负向词不漏入正向")]
    total_bad = 0
    for key, desc in checks:
        for tag in ("NL", "纯标签"):
            v = stat[f"{key}·{tag}"]
            total_bad += v
            print(f"  {'✓' if not v else '✗'} {key} {desc} [{tag}]: {v}")
    v7 = stat["P7"]
    total_bad += v7
    print(f"  {'✓' if not v7 else '✗'} P7 NL 尾段 ≥2 句: {v7}")
    v9 = stat["P9"]
    total_bad += v9
    print(f"  {'✓' if not v9 else '✗'} P9 NL 人称与人数词一致: {v9}")

    if samples:
        print("\n=== 完整提示词样本 ===")
        for i, sp in enumerate(samples, 1):
            print(f"\n[{i}] {sp}")
    if fails:
        print(f"\n❌ 前几条失败 ({len(fails)} 条):")
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 完整提示词重度测试通过 (文本层零违规)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
