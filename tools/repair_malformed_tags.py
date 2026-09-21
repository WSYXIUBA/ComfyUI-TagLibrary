"""一次性数据修复: 清除 .md 往返缺陷产生的畸形标签 (2026-09-10)。

## 缺陷
`tagfiles._TAG_RE` 的 zh 组原先只允许 `[^)]*`, 于是
`1other(单人(其他))` 被整体当成 en 解析 —— 库中因此混入 6 个畸形标签:
    1other(单人(其他))            multiple others(多人(其他))
    jiangshi(僵尸(跳尸))          lap pillow(膝枕(被枕))
    oil painting (medium)(油画(媒介))  watercolor (medium)(水彩(媒介))
其中 `jiangshi` 是**唯一丢失的真词**(其余 5 个是已有词的重复副本)。
后果: 畸形词会被引擎抽中并写进输出 (实测 300 个种子里 32 轮命中)。

## 本脚本
`tagfiles._TAG_RE` 已修 (允许 zh 内一层嵌套括号), `schema.migrate_subcategory`
也会在读取时就地修复 + 同槽位按 en 去重。本脚本把修复**落到磁盘**:
重写 data/default/tag_library.json 与 tag_library.user.json, 并重建 .md 镜像。

用法:
    python tools/repair_malformed_tags.py            # 报告
    python tools/repair_malformed_tags.py --apply    # 落盘 (自动备份)
幂等: 重复执行不再有任何改动。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library  # noqa: E402
import schema  # noqa: E402


def _malformed(d: dict) -> list[tuple[str, str, str]]:
    out = []
    for c in d.get("categories", []):
        for s in c.get("subcategories", []):
            for t in s.get("tags", []) or []:
                if "_MALFORMED_EN_RE" and schema._MALFORMED_EN_RE.match(str(t.get("en") or "")):
                    out.append((c.get("name", ""), s.get("name", ""), str(t.get("en"))))
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    mal_before = mal_after = 0
    words_before = words_after = 0
    for path in (library.DEFAULT_PATH, library.USER_PATH):
        if not os.path.isfile(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        before = _malformed(raw)
        n_before = sum(len(s.get("tags") or [])
                       for c in raw.get("categories", [])
                       for s in c.get("subcategories", []))
        fixed = json.loads(json.dumps(raw, ensure_ascii=False))
        # 必须先摘掉 schema_version: migrate_library 见到当前版本号会直接早退,
        # 而 user.json 因为保存时落过盘、带着 schema_version, 不摘就修不动。
        fixed.pop("schema_version", None)
        schema.migrate_library(fixed)              # 就地修复 + 去重
        after = _malformed(fixed)
        n_after = sum(len(s.get("tags") or [])
                      for c in fixed.get("categories", [])
                      for s in c.get("subcategories", []))
        mal_before += len(before)
        mal_after += len(after)
        words_before += n_before
        words_after += n_after
        name = os.path.basename(path)
        print(f"{name}: 畸形 {len(before)} -> {len(after)} | 词数 {n_before} -> {n_after}")
        for c, s, en in before:
            print(f"    修复 {c}/{s}: {en!r}")
        if apply and (before or n_before != n_after):
            bak = f"{path}.bak-{datetime.now():%Y%m%d%H%M%S}"
            shutil.copy2(path, bak)
            fixed.pop("schema_version", None)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(fixed, f, ensure_ascii=False, indent=1)
            print(f"    ✅ 已落盘 (备份 {os.path.basename(bak)})")

    print(f"\n合计: 畸形 {mal_before} -> {mal_after} 处, 词数 {words_before} -> {words_after}")
    if not apply:
        print("(dry-run; 加 --apply 落盘)")
        return 0

    # 重建 .md 镜像 (镜像内容来自合并库, 修复后自然变干净)
    library.invalidate_cache()
    library.get_merged()
    try:
        # 优先走 library 的正式入口 (会同时维护 _sync_state.json 指纹)
        library.sync_to_folder_snapshot()
        print("✅ .md 镜像已重建 (含 _sync_state.json 指纹)")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 镜像重建失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
