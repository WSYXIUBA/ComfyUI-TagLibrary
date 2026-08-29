"""HTTP 路由: /taglib (管理页) 与 /taglib/api/* (数据接口)。"""

from __future__ import annotations

import json
import os
import time

from aiohttp import web

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import library
    from . import tagfiles
    from . import tagconflicts
except ImportError:  # pragma: no cover
    import library
    import tagfiles
    import tagconflicts
try:
    from server import PromptServer
except ModuleNotFoundError:  # 独立导入时不炸
    PromptServer = None

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _json_response(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


# ---------------------------------------------------------------- page

async def serve_manager_page(_request: web.Request) -> web.Response:
    """GET /taglib -> 独立管理页。"""
    path = os.path.join(_WEB_DIR, "manager.html")
    if not os.path.exists(path):
        return _json_response({"error": "manager.html not found"}, 404)
    with open(path, "rb") as f:
        body = f.read()
    return web.Response(body=body, content_type="text/html", charset="utf-8")


# ---------------------------------------------------------------- api

async def get_library(_request: web.Request) -> web.Response:
    lib = library.get_merged()
    return _json_response({
        "ok": True,
        "mtime": library._mtime(library.USER_PATH),
        "library": lib,
    })


async def save_library(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    try:
        client_mtime = request.headers.get("X-TagLib-Mtime")
        result = library.save_user_library(
            payload,
            client_mtime=float(client_mtime) if client_mtime else None,
        )
        return _json_response(result)
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"保存失败: {exc}"}, 500)


async def reset_library(_request: web.Request) -> web.Response:
    """DELETE /taglib/api/library -> 删除用户库, 回到纯默认库。"""
    try:
        if os.path.exists(library.USER_PATH):
            os.remove(library.USER_PATH)
        library.invalidate_cache()
        return _json_response({"ok": True})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)


# ------------------------------------------------------------ tagfiles

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


async def import_tagfile(request: web.Request) -> web.Response:
    """POST /taglib/api/tagfiles/import  {path, external_dir?} 或 {text}

    解析 -> 跨库 en 去重 -> 按【名称】合并进现有分类/子分类 (全量快照落盘)。
    返回统计。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    text = payload.get("text")
    path = payload.get("path")
    cat_dir = payload.get("cat_dir")
    sub_dir = payload.get("sub_dir")
    if not text and path:
        # 路径只允许在 内置目录 / 标签库目录 / 用户配置的外置目录 下 (防目录穿越随便读盘)
        allowed_roots = [tagfiles.BUILTIN_DIR, tagfiles.LIBRARY_DIR]
        ext_dir = payload.get("external_dir")
        if ext_dir and os.path.isdir(ext_dir):
            allowed_roots.append(os.path.abspath(ext_dir))
        real = os.path.realpath(path)
        root_match = next((r for r in allowed_roots
                           if real.lower().startswith(os.path.realpath(r).lower())), None)
        if not root_match or not os.path.isfile(real):
            return _json_response({"ok": False, "error": f"不允许读取该路径: {path}"}, 403)
        text = tagfiles.load_file_text(real)
    if not text:
        return _json_response({"ok": False, "error": "空文件或空文本"}, 400)

    # 文件夹扫描进来的文件若没有任何标题, 按所在文件夹名补隐含分类 (文件夹即分类)
    if cat_dir:
        text = tagfiles.apply_implied_headings(text, cat_dir, sub_dir)

    merged_now = library.get_merged()
    new_tree, stats = tagfiles.dedupe_against(tagfiles.parse_tagfile(text), merged_now)
    if not stats["total_new"]:
        return _json_response({"ok": True, "imported_categories": 0,
                               "imported_new_tags": 0, "duplicates_removed": stats["duplicates_removed"]})

    # 基座 = 当前合并库的完整快照 (与管理页保存同语义), 按名称并入后整体落盘
    base = json.loads(json.dumps(merged_now))
    base.pop("_meta", None)
    tagfiles.merge_tree_by_name(base, new_tree)

    client_mtime = request.headers.get("X-TagLib-Mtime")
    result = library.save_user_library(
        base, float(client_mtime) if client_mtime else None)
    return _json_response({
        "ok": True,
        "imported_categories": len(new_tree["categories"]),
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


# ------------------------------------------------------------ conflicts

async def get_conflicts(_request: web.Request) -> web.Response:
    return _json_response({"ok": True, "groups": tagconflicts.get_groups()})


async def save_conflicts(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return _json_response({"ok": False, "error": "groups 必须是数组"}, 400)
    tagconflicts.save_groups(groups)
    return _json_response({"ok": True, "count": len(tagconflicts.get_groups())})


async def check_conflicts(request: web.Request) -> web.Response:
    """POST {ens: [tag en ...]} -> 冲突体检结果。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    ens = [str(e) for e in (payload.get("ens") or [])]
    return _json_response({"ok": True, "conflicts": tagconflicts.check_selection(ens)})


def register_routes() -> None:
    if PromptServer is None or PromptServer.instance is None:
        return
    app = PromptServer.instance.app
    # 页面 + API 直接挂主应用 (PromptServer.app 是暴露的 aiohttp Application)
    app.router.add_get("/taglib", serve_manager_page)
    # 管理页的 js/css 走静态子路径 (避免相对路径解析到根 404)
    app.router.add_static("/taglib/static/", _WEB_DIR)
    app.router.add_get("/taglib/api/library", get_library)
    app.router.add_post("/taglib/api/library", save_library)
    app.router.add_delete("/taglib/api/library", reset_library)
    app.router.add_get("/taglib/api/tagfiles", list_tagfiles)
    app.router.add_post("/taglib/api/tagfiles/import", import_tagfile)
    app.router.add_post("/taglib/api/tagfiles/export-folder", export_folder)
    app.router.add_get("/taglib/api/conflicts", get_conflicts)
    app.router.add_post("/taglib/api/conflicts", save_conflicts)
    app.router.add_post("/taglib/api/conflicts/check", check_conflicts)
