# -*- coding: utf-8 -*-
"""按槽 dump 全部词 (含 danbooru post_count) —— 供人工判定"是否隐含第二人"。

背景: 单人锁 (solo_lock) 原来只封 动作姿态/互动与双人 整槽, 但"需要搭档的词"散落在
别的槽里 (体位 / 性行为 / 高潮与体液 / 束缚与调教)。判定必须**按词**, 因为同一个槽里
还有单人能做的 (on back / m legs / masturbation / bound / gagged), 整槽封会误杀。
本工具把指定槽的词连 post_count 一起列出来, 作为 SOLO_PARTNER_WORDS 的维护依据。

用法: python tools/dump_slots.py [槽名 ...]      # 默认列单人锁相关槽
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library                    # noqa: E402
import runtime_snapshot as rs     # noqa: E402

COUNTS = os.path.join(ROOT, "data", "packs", "danbooru_counts.json")
DEFAULT_SLOTS = ("动作姿态/体位", "动作姿态/性行为", "动作姿态/束缚与调教",
                 "动作姿态/高潮与体液", "动作姿态/互动与双人")


def main(slots):
    snap = rs.get_snapshot(library.get_merged())
    counts = {}
    if os.path.exists(COUNTS):
        counts = json.load(open(COUNTS, encoding="utf-8"))
    by_space = {k.replace("_", " "): v for k, v in counts.items()}
    for key in slots:
        si = next((i for i, k in enumerate(snap.sub_keys) if k == key), None)
        if si is None:
            print(f"--- {key}: 槽不存在")
            continue
        words = sorted(snap.tag_lower[t] for t in snap.sub_tag_ids[si])
        print(f"--- {key}  ({len(words)} 词)")
        for w in words:
            n = by_space.get(w)
            print(f"    {w:36} {n if n is not None else '—(非 danbooru 词)'}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_SLOTS)
