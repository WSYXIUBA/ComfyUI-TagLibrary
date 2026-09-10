"""一次性: 从库内 tags.groups 字段汇出 grouprules.json (真源独立化)。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ".."))
import library  # noqa: E402
import grouprules  # noqa: E402

lib = library.get_merged()
by_group: dict[str, set] = {}
for cat in lib.get("categories", []):
    for sub in cat.get("subcategories", []):
        for t in sub.get("tags", []) or []:
            for g in (t.get("groups") or []):
                g = str(g)
                if g.startswith("m:"):
                    by_group.setdefault(g[2:], set()).add(str(t.get("en", "")).strip().lower())

groups = [{"id": gid, "members": sorted(ms)} for gid, ms in sorted(by_group.items())]
grouprules.save_grouprules(groups)
print(f"wrote {len(groups)} groups")
