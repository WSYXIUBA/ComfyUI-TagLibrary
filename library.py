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

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import jsonio
    from . import schema
except ImportError:  # pragma: no cover
    import jsonio
    import schema

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_PKG_DIR, "data")
DEFAULT_DATA_DIR = os.path.join(DATA_DIR, "default")   # v1.1.1: 默认数据分级 data/default/
DEFAULT_PATH = os.path.join(DEFAULT_DATA_DIR, "tag_library.json")
USER_PATH = os.path.join(DEFAULT_DATA_DIR, "tag_library.user.json")
# 1.8.0 扩展包第三源 (NSFW 词表体系 + SFW 高频词补齐):
#   合并优先级 default ← ext ← user; 文件不入 git / 不随插件发布 (合规隔离),
#   缺失时静默跳过 —— 发布版等价于无扩展包。
EXT_PATH = os.path.join(DEFAULT_DATA_DIR, "tag_library.ext.json")


def _migrate_legacy_layout() -> None:
    """v1.1.0 及更早: 数据直接放 data/ 下。升级到 v1.1.1 后自动搬进 data/default/。

    触发条件: data/default 不存在 且 旧结构特征存在 (user.json 或 tag_library.json)。
    只搬一次; 迁移失败不阻塞加载 (文件仍在原地, 但代码只读 default/ — 需手动处理)。
    """
    new_dir = DEFAULT_DATA_DIR
    if os.path.isdir(new_dir):
        return
    legacy_files = [
        ("tag_library.json", "tag_library.json"),
        ("tag_library.user.json", "tag_library.user.json"),
        ("conflicts.json", "conflicts.json"),
    ]
    legacy_dirs = ["taglib", "备份库"]
    has_any = any(os.path.isfile(os.path.join(DATA_DIR, src)) for src, _ in legacy_files) \
        or any(os.path.isdir(os.path.join(DATA_DIR, d)) for d in legacy_dirs)
    if not has_any:
        return
    try:
        os.makedirs(new_dir, exist_ok=True)
        for src, dst in legacy_files:
            p = os.path.join(DATA_DIR, src)
            if os.path.isfile(p):
                os.replace(p, os.path.join(new_dir, dst))
        for d in legacy_dirs:
            src = os.path.join(DATA_DIR, d)
            if os.path.isdir(src):
                dst = os.path.join(new_dir, d)
                if os.path.isdir(dst):
                    continue
                try:
                    os.rename(src, dst)
                except OSError:
                    import shutil
                    shutil.copytree(src, dst)
        print(f"[TagLibrary] 📦 旧数据目录已迁移: data/ -> data/default/")
    except OSError as exc:
        print(f"[TagLibrary] ⚠ 旧数据目录迁移失败 ({exc}); 请手动将 data/ 下的库文件移入 data/default/")


_migrate_legacy_layout()

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{0,79}$")

_lock = threading.RLock()
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


def load_ext_raw() -> dict[str, Any]:
    """扩展包 (第三源)。缺失/损坏 = 空库, 不炸不挡出图。"""
    if not os.path.exists(EXT_PATH):
        return {"version": 1, "categories": []}
    try:
        data = _read_json(EXT_PATH)
        return data if isinstance(data, dict) else {"version": 1, "categories": []}
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "categories": []}


def merged_base() -> dict[str, Any]:
    """default + ext (不含用户库) —— 用户库合并底座 / 墓碑记账口径。"""
    return deep_merge(load_default(), load_ext_raw())


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

    # 用户库一次性索引: 分类/子分类按 id 直查 (取代逐子分类的线性扫描,
    # 65 子分类 × 用户库规模 的 O(n²) -> O(n); 首见优先与旧线性扫描一致)
    u_cat_by_id: dict[str, dict] = {}
    u_sub_by_id: dict[str, dict] = {}
    for c in user.get("categories") or []:
        if c.get("id") and c["id"] not in u_cat_by_id:
            u_cat_by_id[c["id"]] = c
        for s in c.get("subcategories") or []:
            if s.get("id") and s["id"] not in u_sub_by_id:
                u_sub_by_id[s["id"]] = s

    cats = _merge_level(default.get("categories") or [],
                        user.get("categories") or [])
    d_cat_map = {c.get("id"): c for c in (default.get("categories") or [])}
    out_cats: list[dict] = []
    for cat in cats:
        cid = cat.get("id")
        if cid in tombstones:
            continue
        cat = dict(cat)
        # ⚠ 默认库版本作二级 merge 底座: cats 里同 id 分类是"用户版整体优先",
        # 直接用它会把默认库新增的子分类丢掉 (deep_merge 遮蔽 bug, 阶段6扩库踩中)
        d_subs = (d_cat_map.get(cid) or {}).get("subcategories") or []
        d_sub_by_id = {s.get("id"): s for s in d_subs if s.get("id")}
        subs = _merge_level(d_subs,
                            (u_cat_by_id.get(cid) or {}).get("subcategories") or [])
        out_subs: list[dict] = []
        for sub in subs:
            sid = sub.get("id")
            if sid in tombstones:
                continue
            sub = dict(sub)
            # ⚠ 标签层同理: 用户库同 id 子分类快照整体优先, 默认库新增标签会丢 —
            # 用默认库版本子分类的 tags 作 default 侧底座 (阶段6扩库踩中, 与二级修复配套)
            d_tags = (d_sub_by_id.get(sid) or sub).get("tags") or []
            tags = _merge_level(d_tags,
                                (u_sub_by_id.get(sid) or {}).get("tags") or [])
            sub["tags"] = [t for t in tags if t.get("id") not in tombstones]
            # 三级: 归并孙分类 groups (用户版本优先)
            if "groups" in sub:
                groups = _merge_level(sub.get("groups") or [],
                                      (u_sub_by_id.get(sid) or {}).get("groups") or [])
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
            # 注意: groups=[] (空数组) 视为"无三级结构", 不得用空汇总覆盖 tags!
            # (管理页懒加载会给所有子分类挂 groups=[], 覆盖后 tags 全灭 — 2026-08-31 清空重导 bug)
            if sub.get("groups"):  # 非空数组才走三级汇总
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
    cat.setdefault("icon", "🗂")
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
            base_for_tombstones = merged_base()
        else:
            base_for_tombstones = merge_base
        keep_ids = _collect_ids(payload)
        old = load_user_raw()
        old_tombs = set(old.get("_tombstones") or [])
        gone = _collect_ids(base_for_tombstones) - keep_ids
        new_tombs = (old_tombs | gone) - keep_ids  # 重新添加过的自动除名

        out = dict(payload)
        out.pop("_cleared", None)  # 显式保存 = 退出空库状态 (清空标记只在 DELETE 端点写入)
        out["_tombstones"] = sorted(new_tombs)
        out["settings"] = {**load_default().get("settings", {}),
                           **payload.get("settings", {})}
        out.pop("_meta", None)

        jsonio.atomic_write_json(USER_PATH, out)
        _auto_backup_user(out)
        invalidate_cache()
        return {"ok": True, "mtime": _mtime(USER_PATH), "tombstones": len(new_tombs)}


def _auto_backup_user(payload: dict) -> None:
    """每次保存都留一份滚动备份 (data/default/backups/user_auto.json)。

    为什么: 用户库是唯一不進 git 的活数据 (gitignore 了), 丢一次就是全丢 —— 2026-09-21 真发生过
    (文件在门禁跑到一半时消失, 7 条自建预设差点没了, 靠浏览器内存里的副本才捞回来)。
    手动「💾 存为默认库」是用户主动行为, 覆盖不到"最近一次自动保存"; 这里每存一次就刷一份。
    失败不影响保存本身。
    """
    try:
        dst = os.path.join(os.path.dirname(DEFAULT_PATH), "backups", "user_auto.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        jsonio.atomic_write_json(dst, payload)
    except Exception:  # noqa: BLE001 — 备份失败不能挡保存
        pass


# ---------------------------------------------------------------- cache

def _user_settings_value(key: str, default):
    """读用户库 settings 开关 (不经缓存, 避免同步循环)。"""
    try:
        raw = load_user_raw()
        return (raw.get("settings") or {}).get(key, default)
    except Exception:  # noqa: BLE001
        return default


def get_merged() -> dict[str, Any]:
    """合并视图 (纯读, 1.12.0 起也不写盘)。

    历史上它曾在读路径里触发 .md 镜像热同步, 导致 build() 偶发卡 2.5~4 秒 (镜像不幂等
    → 指纹永不收敛 → 每次都重跑全量)。1.12.0 删掉 .md 镜像层后, 读库与磁盘写入彻底解耦。
    """
    global _cache, _cache_key
    key = (_mtime(DEFAULT_PATH), _mtime(EXT_PATH), _mtime(USER_PATH))
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
        user_raw = load_user_raw()
        if user_raw.get("_cleared"):
            # 「🗑 清空标签库」后的空库标记: 用户库显式清空, 默认库不透传 (等导入重建)
            merged = {"version": 1, "schema_version": schema.SCHEMA_VERSION,
                      "categories": [], "settings": user_raw.get("settings", {}),
                      "_meta": {"cleared": True}}
        else:
            # default ← ext ← user 三级归并 (1.8.0: ext 扩展包作二级底座)
            merged = deep_merge(merged_base(), user_raw)
            # v2 只读迁移: 内存中升级编辑层字段 (type/rarity/priority/...), 不写盘
            try:
                schema.migrate_library(merged)
            except Exception:  # noqa: BLE001 — 迁移失败不阻塞读库
                pass
        _cache, _cache_key = merged, key
        return merged


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None
