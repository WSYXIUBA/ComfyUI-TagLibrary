"""标签库的加载 / 合并 / 校验 / 保存。

数据分两层:
  data/tag_library.json       默认库, 随插件发布, 插件更新可覆盖
  data/tag_library.user.json  用户库 (管理页保存的完整树), 永不被插件更新覆盖

合并语义:
  按 id 两级归并 —— 分类/子分类/标签三个层级都是 "用户版本整体优先,
  默认库里用户没有的新条目追加进来"。
  用户删除过的 id 记入墓碑 (_tombstones), 默认库日后重新带出也会被过滤;
  用户重新添加同一 id 时自动移除墓碑。

读取结果带 mtime 缓存, 文件变化自动失效。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_PKG_DIR, "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "tag_library.json")
USER_PATH = os.path.join(DATA_DIR, "tag_library.user.json")

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{0,79}$")

_lock = threading.RLock()  # 可重入: save_user_library 持锁期间还会调 invalidate_cache/get_merged
_cache: dict[str, Any] | None = None
_cache_key: tuple[float, float] | None = None


class LibraryError(ValueError):
    """库数据不合法。"""


# ---------------------------------------------------------------- helpers

def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- load

def load_default() -> dict[str, Any]:
    data = _read_json(DEFAULT_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        raise LibraryError("默认库结构损坏: 缺少 categories 数组")
    return data


def load_user_raw() -> dict[str, Any]:
    if not os.path.exists(USER_PATH):
        return {}
    try:
        data = _read_json(USER_PATH)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # 用户库损坏时不能挡住出图: 改名备份后当作空库
        try:
            os.replace(USER_PATH, USER_PATH + ".corrupt")
        except OSError:
            pass
        return {}


# ---------------------------------------------------------------- merge

def _merge_level(default_items: list[dict], user_items: list[dict]) -> list[dict]:
    """按 id 归并同一层级的节点列表: 用户版本整体优先, 默认独有条目保留。"""
    d_map = {d.get("id"): dict(d) for d in default_items}
    u_map = {u.get("id"): dict(u) for u in user_items}
    merged: list[dict] = []
    for did, d in d_map.items():
        merged.append(u_map[did] if did in u_map else d)
    for uid, u in u_map.items():
        if uid not in d_map:
            merged.append(u)
    return merged


def deep_merge(default: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """default + user -> 完整库 (不修改两个输入)。"""
    tombstones = set(user.get("_tombstones") or [])

    cats = _merge_level(default.get("categories") or [],
                        user.get("categories") or [])
    out_cats: list[dict] = []
    for cat in cats:
        cid = cat.get("id")
        if cid in tombstones:
            continue
        cat = dict(cat)
        subs = _merge_level(cat.get("subcategories") or [],
                            _find_user_subcats(user, cid))
        out_subs: list[dict] = []
        for sub in subs:
            sid = sub.get("id")
            if sid in tombstones:
                continue
            sub = dict(sub)
            tags = _merge_level(sub.get("tags") or [],
                                _find_user_tags(user, sid))
            sub["tags"] = [t for t in tags if t.get("id") not in tombstones]
            # 三级: 归并孙分类 groups (用户版本优先)
            if "groups" in sub:
                groups = _merge_level(sub.get("groups") or [],
                                      _find_user_groups(user, sid))
                clean_groups = []
                for g in groups:
                    if g.get("id") in tombstones:
                        continue
                    gtags = [t for t in (g.get("tags") or []) if t.get("id") not in tombstones]
                    g = dict(g)
                    g["tags"] = gtags
                    clean_groups.append(g)
                sub["groups"] = clean_groups
                # 同步 tags 汇总 = groups 标签 + 子分类直属标签
                g_en = {t.get("en", "").lower() for g in clean_groups for t in g.get("tags", [])}
                sub["tags"] = [t for t in sub["tags"]
                               if t.get("en", "").lower() not in g_en]
                for g in clean_groups:
                    sub["tags"].extend(g.get("tags", []))
            out_subs.append(sub)
        cat["subcategories"] = out_subs
        out_cats.append(cat)

    return {
        **default,
        "categories": out_cats,
        "settings": {**default.get("settings", {}), **user.get("settings", {})},
        "_meta": {
            "merged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "has_user_data": bool(user.get("categories")) or bool(tombstones),
        },
    }


def _user_cat(user: dict, cid: str | None) -> dict | None:
    for c in user.get("categories") or []:
        if c.get("id") == cid:
            return c
    return None


def _find_user_subcats(user: dict, cid: str | None) -> list[dict]:
    cat = _user_cat(user, cid)
    return (cat or {}).get("subcategories") or []


def _find_user_tags(user: dict, sid: str | None) -> list[dict]:
    for cat in user.get("categories") or []:
        for sub in cat.get("subcategories") or []:
            if sub.get("id") == sid:
                return sub.get("tags") or []
    return []


# ---------------------------------------------------------------- validate & save

def validate(library_data: dict) -> dict:
    """管理页提交的库结构校验。就地补默认值并返回原对象, 有问题抛 LibraryError。"""
    if not isinstance(library_data, dict):
        raise LibraryError("顶层必须是对象")
    cats = library_data.get("categories")
    if not isinstance(cats, list):
        raise LibraryError("categories 必须是数组")

    top_seen: set[str] = set()
    for cat in cats:
        if not isinstance(cat, dict):
            raise LibraryError("分类必须是对象")
        cid = _require_id(cat, "分类")
        _uniq(cid, top_seen, "分类")
        _ensure_icon_color(cat)

        sub_seen: set[str] = set()
        subs = cat.setdefault("subcategories", [])
        if not isinstance(subs, list):
            raise LibraryError(f"分类 {cid} 的 subcategories 必须是数组")
        for sub in subs:
            sid = _require_id(sub, f"{cid} 的子分类")
            _uniq(sid, sub_seen, "子分类")
            # 三级: 子分类可再含孙分类 (groups) 或直接挂 tags
            if "groups" in sub:
                groups = sub.get("groups")
                if not isinstance(groups, list):
                    raise LibraryError(f"子分类 {sid} 的 groups 必须是数组")
                g_seen: set[str] = set()
                all_tags: list[dict] = []
                for g in groups:
                    gid = _require_id(g, f"{sid} 的孙分类")
                    _uniq(gid, g_seen, "孙分类")
                    gtags = g.setdefault("tags", [])
                    if not isinstance(gtags, list):
                        raise LibraryError(f"孙分类 {gid} 的 tags 必须是数组")
                    _validate_tags(gid, gtags)
                    all_tags.extend(gtags)
                # tags 字段 = 全部孙分类标签的汇总 (运行时统一遍历用)
                sub["tags"] = all_tags
            else:
                tags = sub.setdefault("tags", [])
                _validate_tags(sid, tags)
    library_data.setdefault("version", 1)
    library_data.pop("_meta", None)
    return library_data


def _validate_tags(owner_id: str, tags: list) -> None:
    """校验一个标签数组 (就地补默认值)。"""
    for i, tag in enumerate(tags):
        if not isinstance(tag, dict):
            raise LibraryError(f"{owner_id} 第{i}项不是对象")
        if not (tag.get("en") or "").strip():
            raise LibraryError(f"{owner_id} 存在缺少英文文本的标签")
        w = tag.get("weight", 1.0)
        try:
            w = float(w)
        except (TypeError, ValueError):
            raise LibraryError(f"标签 {tag.get('en')} 权重必须是数字")
        if not 0 < w <= 3:
            raise LibraryError(f"标签 {tag.get('en')} 权重须在 (0, 3]")
        tag["weight"] = w
        if not tag.get("id"):
            tag["id"] = _make_tag_id(owner_id, tag["en"], tags)
        aliases = tag.setdefault("aliases", [])
        if not isinstance(aliases, list):
            tag["aliases"] = []
    _dedupe_tag_ids(tags)


def _require_id(obj: dict, what: str) -> str:
    oid = obj.get("id")
    if not oid or not isinstance(oid, str):
        raise LibraryError(f"{what}缺少 id")
    if not _ID_RE.match(oid):
        raise LibraryError(f"id 非法: {oid!r} (只允许字母数字._-)")
    return oid


def _uniq(oid: str, seen: set[str], what: str) -> None:
    if oid in seen:
        raise LibraryError(f"{what} id 重复: {oid}")
    seen.add(oid)


def _ensure_icon_color(cat: dict) -> None:
    cat.setdefault("icon", "🏷️")
    color = cat.get("color")
    if not (isinstance(color, str) and re.match(r"^#[0-9a-fA-F]{6}$", color)):
        cat["color"] = "#888888"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "tag"


def _make_tag_id(parent_sid: str, en_text: str, existing: list[dict]) -> str:
    taken = {t.get("id") for t in existing if isinstance(t, dict)}
    base = f"{parent_sid}.{_slug(en_text)}"
    cand, n = base, 2
    while cand in taken:
        cand = f"{base}-{n}"
        n += 1
    return cand


def _dedupe_tag_ids(tags: list[dict]) -> None:
    """防手滑 id 冲突: 重复的后缀化。"""
    seen: set[str] = set()
    for t in tags:
        tid = t.get("id") or ""
        if tid in seen:
            n = 2
            while f"{tid}-{n}" in seen:
                n += 1
            t["id"] = f"{tid}-{n}"
        seen.add(t["id"])


def _collect_ids(lib: dict) -> set[str]:
    ids: set[str] = set()
    for cat in lib.get("categories", []):
        if cat.get("id"):
            ids.add(cat["id"])
        for sub in cat.get("subcategories", []):
            if sub.get("id"):
                ids.add(sub["id"])
            for tag in sub.get("tags", []):
                if tag.get("id"):
                    ids.add(tag["id"])
    return ids


def save_user_library(payload: dict, client_mtime: float | None = None,
                      merge_base: dict | None = None) -> dict:
    """校验 + 原子写入用户库。client_mtime 乐观锁防双开互相覆盖。

    merge_base: 追加式导入时传入"提交前的完整底座"(如 默认库+已有用户库),
    墓碑只对底座里消失的 id 记账 —— 提交树 = 底座的超集, 不会误删。
    不传则为全量覆盖语义 (墓碑按提交树记账, 管理页整体保存用这个)。
    """
    payload = validate(json.loads(json.dumps(payload)))  # 深拷贝后再改
    with _lock:
        server_mtime = _mtime(USER_PATH)
        if client_mtime is not None and server_mtime > client_mtime + 0.001:
            raise LibraryError(
                "服务器上的用户库比你看到的更新 (可能在别处已修改), 请刷新页面后重试"
            )
        if merge_base is None:
            base_for_tombstones = load_default()
        else:
            base_for_tombstones = merge_base
        keep_ids = _collect_ids(payload)
        old = load_user_raw()
        old_tombs = set(old.get("_tombstones") or [])
        gone = _collect_ids(base_for_tombstones) - keep_ids
        new_tombs = (old_tombs | gone) - keep_ids  # 重新添加过的自动除名

        out = dict(payload)
        out["_tombstones"] = sorted(new_tombs)
        out["settings"] = {**load_default().get("settings", {}),
                           **payload.get("settings", {})}
        out.pop("_meta", None)

        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = USER_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        os.replace(tmp, USER_PATH)
        invalidate_cache()
        return {"ok": True, "mtime": _mtime(USER_PATH), "tombstones": len(new_tombs)}


# ---------------------------------------------------------------- cache

def get_merged() -> dict[str, Any]:
    global _cache, _cache_key
    key = (_mtime(DEFAULT_PATH), _mtime(USER_PATH))
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
        merged = deep_merge(load_default(), load_user_raw())
        _cache, _cache_key = merged, key
        return merged


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _find_user_groups(user: dict, sid: str) -> list[dict]:
    """找到用户库中指定子分类的孙分类列表 (groups)。"""
    for cat in user.get("categories", []):
        for sub in cat.get("subcategories", []):
            if sub.get("id") == sid:
                return sub.get("groups") or []
    return []
