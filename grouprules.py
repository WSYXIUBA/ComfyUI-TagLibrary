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
    from . import jsonio
    from . import tagfiles
except ImportError:  # pragma: no cover
    import jsonio
    import tagfiles

GROUPRULES_PATH = os.path.join(tagfiles.LIBRARY_DIR, "grouprules.json")
# 1.8.0: NSFW 互斥域扩展文件 (ext 扩展包配套, 不入 git/发布)。
# 与出厂文件同名 id 的域按**并集**合并 —— 口部域 (legacy.mouth) 等资源账本
# 由两侧词共同守护, 而不必把 NSFW 词写进出厂文件。
NSFW_GROUPS_PATH = os.path.join(tagfiles.LIBRARY_DIR, "nsfw_grouprules.json")

_lock = threading.Lock()
_cache: dict | None = None
_cache_key: float | None = None


def _mtime() -> float:
    m1 = m2 = 0.0
    try:
        m1 = os.stat(GROUPRULES_PATH).st_mtime
    except OSError:
        pass
    try:
        m2 = os.stat(NSFW_GROUPS_PATH).st_mtime
    except OSError:
        pass
    return max(m1, m2)


def _read_groups(path: str) -> list[dict]:
    """→ [{id, members(lower)}] 文件级解析; 缺失/损坏 = 空。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        groups = data.get("groups") or []
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for g in groups:
        gid = str(g.get("id") or "").strip()
        members = {str(m).strip().lower() for m in (g.get("members") or [])
                   if str(m).strip()}
        if gid and len(members) >= 2:
            out.append({"id": gid, "members": members})
    return out


def load_grouprules() -> list[dict]:
    """→ [{id, members(lower)}]。出厂文件 + NSFW 扩展文件, 同名 id 并集。"""
    global _cache, _cache_key
    key = _mtime()
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
    merged: dict[str, set] = {}
    for g in _read_groups(GROUPRULES_PATH) + _read_groups(NSFW_GROUPS_PATH):
        merged.setdefault(g["id"], set()).update(g["members"])
    out = [{"id": gid, "members": frozenset(m)} for gid, m in merged.items()]
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
    jsonio.atomic_write_json(GROUPRULES_PATH, {"version": 1, "groups": groups})
    global _cache, _cache_key
    with _lock:
        _cache = None
        _cache_key = None
