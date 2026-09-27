"""全局互斥域规则 —— 组名 → 成员词表, 内嵌于词库文件 (1.14.0 单文件化)。

真源: 各层词库文件的 rules.groups 段, 按层归并 (default ← ext ← user, 同名 id 成员并集):
  data/default/tag_library.json      → 出厂互斥域
  data/default/tag_library.ext.json  → NSFW 扩展互斥域 (与出厂同名域并集)
管理页保存写回默认库文件的 rules 段。
旧独立文件 (grouprules.json / nsfw_grouprules.json) 由 library._migrate_rules_files() 启动时并入。

标签 groups 字段 + 档案束派生组 + 本模块的规则域, 三者在快照编译期并集成 group_sets。
热路径只查 frozenset 交集。
"""

from __future__ import annotations

import threading

try:
    from . import library
except ImportError:  # pragma: no cover
    import library

_lock = threading.Lock()
_cache: list | None = None
_cache_key: tuple | None = None


def _mtime() -> float:
    """规则真源 = 各层库文件 (runtime_snapshot 缓存键用), 取三层最大 mtime。"""
    return max(library._mtime(library.DEFAULT_PATH),
               library._mtime(library.EXT_PATH),
               library._mtime(library.USER_PATH))


def _groups_from_lib() -> list[dict]:
    """从合并库读互斥域段 → [{id, members(frozenset)}] (成员小写去重, <2 成员丢弃)。"""
    lib = library.get_merged()
    out: list[dict] = []
    for g in ((lib.get("rules") or {}).get("groups") or []):
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "").strip()
        members = {str(m).strip().lower() for m in (g.get("members") or [])
                   if str(m).strip()}
        if gid and len(members) >= 2:
            out.append({"id": gid, "members": frozenset(members)})
    return out


def load_grouprules() -> list[dict]:
    """→ [{id, members(frozenset)}]。同名域并集已在 library 层归并完成。"""
    global _cache, _cache_key
    key = (_mtime(),)
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
    out = _groups_from_lib()
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
    """整表保存 (管理页用): 写回默认库文件的 rules.groups 段。"""
    clean = []
    for g in groups or []:
        gid = str(g.get("id") or "").strip()
        members = sorted({str(m).lower() for m in (g.get("members") or []) if str(m).strip()})
        if gid and len(members) >= 2:
            item = {"id": gid, "members": members}
            if g.get("note"):
                item["note"] = str(g["note"])
            clean.append(item)
    library.save_rules_into_default(groups=clean)
    global _cache, _cache_key
    with _lock:
        _cache = None
        _cache_key = None
