"""防冲突引擎 —— 互斥标签组配置与执行。

conflicts.json (与 tag_library.json 同目录):
{
  "groups": [
    {"id": "mouth", "name": "嘴部", "tags": ["open mouth", "closed eyes"], ...},
    ...
  ]
}

* tags 里存的是标签英文文本的**小写**；也支持直接用 tag id。
* 冲突规则: 同一组内最多选 1 个（random 时）。
  `strict: false` 的软组只在随机时避让, 手动选择只提示不阻止。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFLICT_PATH = os.path.join(_PKG_DIR, "data", "conflicts.json")

_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float = -1.0

DEFAULT_GROUPS: list[dict] = []


def _mtime() -> float:
    try:
        return os.path.getmtime(CONFLICT_PATH)
    except OSError:
        return 0.0


def _load() -> dict:
    global _cache, _cache_mtime
    mt = _mtime()
    if _cache is not None and mt == _cache_mtime:
        return _cache
    groups: list[dict] = []
    if os.path.exists(CONFLICT_PATH):
        try:
            with open(CONFLICT_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            for i, g in enumerate(data.get("groups") or []):
                tags = [str(t).strip().lower() for t in g.get("tags", []) if str(t).strip()]
                if len(tags) >= 2:
                    groups.append({
                        "id": g.get("id") or f"group{i}",
                        "name": g.get("name") or g.get("id") or f"组{i}",
                        "strict": bool(g.get("strict", True)),
                        "tags": tags,
                    })
        except (json.JSONDecodeError, OSError):
            groups = []
    with _lock:
        _cache = {"groups": groups}
        _cache_mtime = mt
    return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def get_groups() -> list[dict]:
    return _load()["groups"]


def save_groups(groups: list[dict]) -> None:
    clean = []
    seen_ids = set()
    for i, g in enumerate(groups or []):
        tags = sorted({str(t).strip().lower() for t in g.get("tags", []) if str(t).strip()})
        if len(tags) < 2:
            continue
        gid = str(g.get("id") or f"group{i}").strip()
        n = 2
        while gid in seen_ids:
            gid = f"{g.get('id')}-{n}"
            n += 1
        seen_ids.add(gid)
        clean.append({"id": gid, "name": str(g.get("name") or gid),
                      "strict": bool(g.get("strict", True)), "tags": tags})
    tmp = CONFLICT_PATH + ".tmp"
    with _lock:
        os.makedirs(os.path.dirname(CONFLICT_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "groups": clean}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CONFLICT_PATH)
    invalidate()


# ---------------------------------------------------------------- querying

def conflicts_for(tag_names: list[str], resolved_by_en: dict[str, list[str]] | None = None) -> dict[str, list[dict]]:
    """给定标签英文名列表, 返回 {tag_name: [触发的组...]} (只含有冲突的)。

    resolved_by_en: en -> 该名字对应的所有 tag id 列表 (可选, 用于按 id 配置命中)。
    """
    groups = get_groups()
    out: dict[str, list[dict]] = {}
    lower = [t.strip().lower() for t in tag_names]
    id_map = resolved_by_en or {}
    names = set(lower) | {i.lower() for ids in id_map.values() for i in ids}

    for g in groups:
        gset = set(g["tags"])
        hit = [raw for raw, lo in zip(tag_names, lower) if lo in gset or any(i in gset for i in id_map.get(raw, []))]
        # 组内命中 >=2 个才算真冲突; 单个命中只在其组内与其他选中重叠时才有意义
        hits_in_group = [n for n in (set(lower) | {i.lower() for ids in id_map.values() for i in ids}) if n in gset]
        if len(hits_in_group) < 2 and len(hit) == 0:
            continue
        if len(hits_in_group) >= 2:
            for name in hit:
                out.setdefault(name, []).append(g)
    return out


def filter_conflicts(candidates: list[dict], already_chosen: list[str],
                     rng_pick=None) -> tuple[list[dict], int]:
    """随机抽取时的贪心避让。

    candidates: [{en:..., ...}] 待抽池 (带 en);
    already_chosen: 已确定要含有的 en 小写列表;
    rng_pick: 可选回调 (pool)->list 预抽取钩子, 未用。
    返回 (过滤后的池, 被排除数)。排除的是与 already_chosen 同组的候选。
    """
    chosen_lower = {c.strip().lower() for c in already_chosen}
    banned_sets: list[set] = []
    for g in get_groups():
        gs = set(g["tags"])
        if chosen_lower & gs:
            # 已选已占用该组 -> 全组禁入
            banned_sets.append(gs)
    if not banned_sets:
        return candidates, 0
    out, blocked = [], 0
    for c in candidates:
        lo = str(c.get("en", "")).strip().lower()
        if any(lo in b for b in banned_sets):
            blocked += 1
            continue
        # 候选之间也要互斥: 记录本候选所属组, 后续候选若同组则跳过 — 简化处理:
        # 贪心逐个吸收 (在调用方循环里做); 这里做静态过滤已足够作为二次防线
        conflict_with_kept = False
        for kept in out:
            klo = str(kept.get("en", "")).strip().lower()
            for g in get_groups():
                gs = set(g["tags"])
                if klo in gs and lo in gs:
                    conflict_with_kept = True
                    break
            if conflict_with_kept:
                break
        if conflict_with_kept:
            blocked += 1
            continue
        out.append(c)
    return out, blocked


def check_selection(en_list: list[str]) -> dict[str, list[str]]:
    """手动选择的冲突体检: 返回 {分组名: [命中的 en, ...]} 只含 >=2 命中的组。"""
    result = {}
    lowers = [e.strip().lower() for e in en_list]
    for g in get_groups():
        gs = set(g["tags"])
        hits = [en for en, lo in zip(en_list, lowers) if lo in gs]
        if len(hits) >= 2:
            result[g["name"]] = hits
    return result
