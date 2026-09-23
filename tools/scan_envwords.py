# -*- coding: utf-8 -*-
"""全库扫描: 简背景闸门的两类漏洞 —— 跨槽重名 + 别槽里的环境暗示词。

背景: bg_mode=simple 的闸门按**槽**封 (场景环境/*) + 背景处理槽白名单, 但

  1. 库里 en 可以重名挂多个槽 (en_to_id 只指向最后一个) —— 同一份副本从别的槽被抽到
     就绕过了按槽的判定 (实测 "detailed background" 同时在 画质规格/细节强化);
  2. 别的类目里也有"会摆出一个具体环境"的词 (candlelit room / looking out window /
     interior photography ...), 它们不在任何被禁的槽里, 简背景开着照样出。

用法:
  python tools/scan_envwords.py            # 打印两类漏洞
  python tools/scan_envwords.py --words    # 只打印建议封禁的词 (可直接贴进 slotpolicy)
"""
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library          # noqa: E402
import runtime_snapshot as rs   # noqa: E402
import slotpolicy       # noqa: E402

RE = re.compile(
    r"\b(room|house|home|beach|shore|seaside|street|city|town|village|cafe|bar|"
    r"restaurant|shop|store|market|school|office|church|temple|shrine|castle|"
    r"forest|woods|jungle|garden|park|field|meadow|mountain|hill|valley|river|"
    r"lake|sea|ocean|sky|cloud|rain|snow|storm|fog|mist|thunder|lightning|wind|"
    r"night|evening|morning|dawn|dusk|sunset|sunrise|moon|star|sun|day|season|"
    r"winter|summer|spring|autumn|indoor|outdoor|interior|exterior|"
    r"window|door|wall|floor|ceiling|balcony|rooftop|alley|harbor|harbour|"
    r"desert|ruins|ruin|lab|laboratory|library|bathroom|bedroom|kitchen|"
    r"classroom|train|station|airport|tunnel|bridge|pyramid)\b", re.I)


def main() -> None:
    snap = rs.get_snapshot(library.get_merged())
    banned = set(slotpolicy.SIMPLE_BG_BAN_SLOTS)
    by_text = defaultdict(set)
    for tid, low in enumerate(snap.tag_lower):
        by_text[low].add(snap.sub_keys[snap.sub_of[tid]])

    print("=== 1. 跨槽重名, 能从别的槽绕过简背景闸门的背景词 ===")
    leaks = sorted(w for w, slots in by_text.items()
                   if "场景环境/背景处理" in slots
                   and any(s not in banned and s != "场景环境/背景处理" for s in slots)
                   and w not in slotpolicy.SIMPLE_BG_WORDS)
    print(f"  {len(leaks)} 个: {leaks}")

    print("\n=== 2. 不在禁列、却带环境语义的词 ===")
    groups = defaultdict(list)
    for w, slots in by_text.items():
        if not RE.search(w):
            continue
        free = [s for s in slots if s not in banned and s != "场景环境/背景处理"]
        if free:
            groups[sorted(free)[0]].append(w)
    advice = set()
    for k in sorted(groups, key=lambda x: -len(groups[x])):
        ws = sorted(groups[k])
        print(f"  [{k}] {len(ws)}: {', '.join(ws[:20])}")
        advice |= set(ws)

    if "--words" in sys.argv:
        print("\n=== 建议清单 (人工筛后再进 slotpolicy) ===")
        for w in sorted(advice):
            print(f'    "{w}",')


if __name__ == "__main__":
    main()
