""".md 标签文件路由: 扫描 / 预览导入 / 导入 / 导出文件夹。"""

from __future__ import annotations

import json
import os

from aiohttp import web

from .. import library
from .. import tagfiles
from ._common import _PKG_DIR, _json_response, _mirror_folder


async def list_tagfiles(request: web.Request) -> web.Response:
    """GET /taglib/api/tagfiles?dir=... -> 列出标签库目录(两级结构)+兼容旧目录+外置目录。

    ⚠ 文件夹 → 库 的**吸入方向**改由这里显式触发。它原来挂在 `get_merged()` 的
    读路径上 (`_folder_hot_sync()`), 实测在活进程里一次要 **3.7~4.0 秒**
    —— 因为 .md 镜像不幂等 (重写会改内容, 如 `thong(丁字裤)` 补成
    `thong(丁字裤)[nsfw]`), 指纹永远在变, 于是永不收敛、每次都重跑全量。
    后果是 `TagLibraryNode.build()` 偶发卡 3~4 秒, 且连续输出时中位耗时
    从 0.02s 涨到 1.8s (倍率 20~85x)。详见 `library.get_merged` 的注释。
    """
    try:
        library.hot_sync_now()
    except Exception:  # noqa: BLE001 — 同步失败不影响列文件
        pass
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
        tagfiles.apply_tag_meta(tree)   # 编辑层字段从 sidecar 还原 (1.7.0)
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
    """POST /taglib/api/tagfiles/export-folder  {dir?, confirm?}

    把当前合并库镜像导出为两级文件夹结构 (默认写入插件内 data/default/taglib/)。
    导出到插件数据目录之外属于敏感操作 (镜像会覆盖/删除目标位置库结构内的 .md),
    需前端显式 confirm=true (管理页会先弹确认框)。
    """
    try:
        payload = await request.json() if request.can_read_body else {}
    except Exception:
        payload = {}
    folder = (payload.get("dir") or "").strip() or tagfiles.LIBRARY_DIR
    err = _export_dir_error(folder, payload)
    if err:
        status = 400 if "绝对路径" in err else 403
        return _json_response({"ok": False, "error": err}, status)
    try:
        stats = tagfiles.export_to_folder(library.get_merged(), folder)
        return _json_response({"ok": True, **stats})
    except OSError as exc:
        return _json_response({"ok": False, "error": f"导出失败: {exc}"}, 500)


def _export_dir_error(folder: str, payload: dict) -> str | None:
    """导出目录校验: 返回错误信息; 合法返回 None。

    - 必须绝对路径
    - 插件 data/ 子树内直接放行 (taglib 镜像 / 外置导出模板都属于日常路径)
    - data/ 之外要求 payload.confirm is True (配合 CSRF 中间件双保险:
      跨站请求既过不了中间件, 也无法伪造"用户在管理页点过确认"的语义)
    """
    if not os.path.isabs(folder):
        return "目录必须是绝对路径"
    real_dir = os.path.realpath(folder)
    data_root = os.path.realpath(os.path.join(_PKG_DIR, "data"))
    if real_dir == data_root or real_dir.startswith(data_root + os.sep):
        return None
    if payload.get("confirm") is not True:
        return (f"导出到插件数据目录之外 ({folder}) 属于敏感操作: "
                "镜像会覆盖/删除目标位置库结构内的 .md。请在管理页确认后重试")
    return None


# ------------------------------------------------------------ 1.3.0: 档案 / 互斥域 / NL / 抽取
