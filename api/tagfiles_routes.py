""".md 标签文件路由: 扫描 / 预览导入 / 导入 / 导出文件夹。"""

from __future__ import annotations

import json
import os
import time

from aiohttp import web

from .. import library
from .. import tagfiles
from .. import tagconflicts
from .. import runtime_snapshot
from .. import profiles as _profiles
from .. import grouprules as _grouprules
from .. import nl as _nl
from .. import engine as _engine
from ._common import (
    _WEB_DIR, BACKUP_DIR, FACTORY_BACKUP_PATH, USER_BACKUP_PATH,
    UPGRADE_PROMPT_PATH, LEGACY_BACKUP_PATH, _json_response, _mirror_folder,
)


async def list_tagfiles(request: web.Request) -> web.Response:
    """GET /taglib/api/tagfiles?dir=... -> 列出标签库目录(两级结构)+兼容旧目录+外置目录。"""
    ext = request.query.get("dir") or ""
    items = tagfiles.scan_folder(ext, tagfiles.LIBRARY_DIR)
    items += tagfiles.scan_folder("", tagfiles.BUILTIN_DIR)  # 旧内置目录兼容
    return _json_response({
        "ok": True,
        "files": items,
        "builtin_dir": tagfiles.LIBRARY_DIR,
        "library_dir": tagfiles.LIBRARY_DIR,
        "legacy_dir": tagfiles.BUILTIN_DIR,
    })


def _collect_texts(payload: dict) -> list[dict]:
    """从请求体收集待导入文本列表 [{text, cat_dir, sub_dir}]。

    兼容三种写法: {text} / {path, external_dir?} / {items: [{text} | {path,...}]}
    路径只允许 内置/标签库/外置 目录 (防目录穿越)。文件无标题时按文件夹补隐含分类。
    """
    allowed_roots = [tagfiles.BUILTIN_DIR, tagfiles.LIBRARY_DIR]
    ext_dir = payload.get("external_dir")
    if ext_dir and os.path.isdir(ext_dir):
        allowed_roots.append(os.path.abspath(ext_dir))

    raw_items: list[dict] = []
    if payload.get("items"):
        raw_items = list(payload["items"])
    elif payload.get("text") or payload.get("path"):
        raw_items = [payload]
    else:
        raise ValueError("没有可导入的内容")

    out: list[dict] = []
    for item in raw_items:
        text = item.get("text")
        if not text and item.get("path"):
            real = os.path.realpath(item["path"])
            root_match = next((r for r in allowed_roots
                               if real.lower().startswith(os.path.realpath(r).lower())), None)
            if not root_match or not os.path.isfile(real):
                raise ValueError(f"不允许读取该路径: {item['path']}")
            text = tagfiles.load_file_text(real)
        if not text:
            continue
        cat_dir = item.get("cat_dir")
        sub_dir = item.get("sub_dir")
        if cat_dir:
            text = tagfiles.apply_implied_headings(text, cat_dir, sub_dir)
        out.append({"text": text, "cat_dir": cat_dir, "sub_dir": sub_dir})
    if not out:
        raise ValueError("空文件或空文本")
    return out


def _parse_and_merge_tree(payload: dict) -> tuple[dict, dict]:
    """解析请求内容 -> (聚合导入树, 统计)。已对现有合并库去重, 多文件聚合归组。"""
    merged_now = library.get_merged()
    agg: dict = {"version": 1, "categories": []}
    dup_total = 0
    for item in _collect_texts(payload):
        tree = tagfiles.parse_tagfile(item["text"])
        tree, stats = tagfiles.dedupe_against(tree, merged_now)
        dup_total += stats["duplicates_removed"]
        tagfiles.merge_tree_by_name(agg, tree)
    return agg, {"total_new": sum(len(s.get("tags", []))
                                  for c in agg["categories"] for s in c["subcategories"]),
                 "duplicates_removed": dup_total}


async def preview_import(request: web.Request) -> web.Response:
    """POST /taglib/api/tagfiles/preview-import  (dry-run, 不落盘)

    返回按 大类/子分类 分组的新增标签预览 + 去重统计, 供前端确认弹窗。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    try:
        agg, stats = _parse_and_merge_tree(payload)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"解析失败: {exc}"}, 500)
    groups = [{"cat": c.get("name"), "cat_icon": c.get("icon", "📦"),
               "sub": s.get("name"),
               "tags": [{"en": t.get("en"), "zh": t.get("zh", ""),
                         "weight": t.get("weight", 1.0), "nsfw": bool(t.get("nsfw"))}
                        for t in s.get("tags", [])]}
              for c in agg.get("categories", []) for s in c.get("subcategories", [])]
    return _json_response({"ok": True, "groups": groups,
                           "total_new": stats["total_new"],
                           "duplicates_removed": stats["duplicates_removed"]})


async def import_tagfile(request: web.Request) -> web.Response:
    """POST /taglib/api/tagfiles/import  {text|path|items}

    解析 -> 跨库 en 去重 -> 按【名称】合并进现有分类/子分类 (全量快照落盘 + 文件夹镜像)。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    try:
        merged_now = library.get_merged()
        agg, stats = _parse_and_merge_tree(payload)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"导入失败: {exc}"}, 500)
    if not stats["total_new"]:
        return _json_response({"ok": True, "imported_categories": 0,
                               "imported_new_tags": 0,
                               "duplicates_removed": stats["duplicates_removed"]})

    # 基座 = 当前合并库的完整快照 (与管理页保存同语义), 按名称并入后整体落盘
    base = json.loads(json.dumps(merged_now))
    base.pop("_meta", None)
    tagfiles.merge_tree_by_name(base, agg)

    client_mtime = request.headers.get("X-TagLib-Mtime")
    result = library.save_user_library(
        base, float(client_mtime) if client_mtime else None)
    _mirror_folder()
    return _json_response({
        "ok": True,
        "imported_categories": len(agg["categories"]),
        "imported_new_tags": stats["total_new"],
        "duplicates_removed": stats["duplicates_removed"],
        "save": result,
    })


async def export_folder(request: web.Request) -> web.Response:
    """POST /taglib/api/tagfiles/export-folder  {dir?}

    把当前合并库镜像导出为两级文件夹结构 (默认写入插件内 data/标签库/)。
    """
    try:
        payload = await request.json() if request.can_read_body else {}
    except Exception:
        payload = {}
    folder = (payload.get("dir") or "").strip() or tagfiles.LIBRARY_DIR
    if not os.path.isabs(folder):
        return _json_response({"ok": False, "error": "目录必须是绝对路径"}, 400)
    try:
        stats = tagfiles.export_to_folder(library.get_merged(), folder)
        return _json_response({"ok": True, **stats})
    except OSError as exc:
        return _json_response({"ok": False, "error": f"导出失败: {exc}"}, 500)


# ------------------------------------------------------------ 1.3.0: 档案 / 互斥域 / NL / 抽取
