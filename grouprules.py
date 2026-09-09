"""全局互斥域规则 (1.3.0) —— 组名 → 成员词表, 独立数据文件。

真源: data/default/grouprules.json
  { "version":1, "groups": [ {"id":"legacy.mouth","members":["open mouth",...]} ] }

标签 groups 字段 + 档案束派生组 + 本文件的 legacy 组, 三者在快照编译期
并集成 group_sets。热路径只查 frozenset 交集。

为什么独立文件而不是只存标签字段: md 文件夹热同步重导入会重建标签 dict,
存在标签身上的组名会丢 —— 独立文件按 en 查表, 免疫重导入。
"""

from __future__ import annotations

import json
import os
import threading

try:
    from . import tagfiles
except ImportError:  # pragma: no cover
    import tagfiles

GROUPRULES_PATH = os.path.join(tagfiles.LIBRARY_DIR, "grouprules.json")

_lock = threading.Lock()
_cache: dict | None = None
_cache_key: float | None = None


def _mtime() -> float:
    try:
        return os.stat(GROUPRULES_PATH).st_mtime
    except OSError:
        return 0.0


def load_grouprules() -> list[dict]:
    """→ [{id, members(lower)}]。文件缺失 = 空 (不炸)。"""
    global _cache, _cache_key
    key = _mtime()
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
    try:
        with open(GROUPRULES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        groups = data.get("groups") or []
    except (OSError, json.JSONDecodeError):
        groups = []
    out = []
    for g in groups:
        gid = str(g.get("id") or "").strip()
        members = {str(m).strip().lower() for m in (g.get("members") or [])
                   if str(m).strip()}
        if gid and len(members) >= 2:
            out.append({"id": gid, "members": members})
    with _lock:
        _cache = out
        _cache_key = key
    return out


def en_membership() -> dict[str, frozenset]:
    """en_lower → 组名集合 (编译一次快照用)。"""
    out: dict[str, set] = {}
    for g in load_grouprules():
        gn = f"m:{g['id']}"
        for m in g["members"]:
            out.setdefault(m, set()).add(gn)
    return {k: frozenset(v) for k, v in out.items()}


def save_grouprules(groups: list[dict]) -> None:
    os.makedirs(os.path.dirname(GROUPRULES_PATH), exist_ok=True)
    tmp = GROUPRULES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "groups": groups}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, GROUPRULES_PATH)
    global _cache, _cache_key
    with _lock:
        _cache = None
        _cache_key = None
