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
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "备份库")
BACKUP_PATH = os.path.join(BACKUP_DIR, "tag_library.backup.json")


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


def _mirror_folder() -> None:
    """库 -> 文件夹实时同步 (保存/导入/重置后调用)。失败不影响请求。"""
    try:
        lib_key = (library._mtime(library.DEFAULT_PATH),
                   library._mtime(library.USER_PATH))
        tagfiles.sync_to_folder(library.get_merged())
        tagfiles.mark_synced(lib_key=lib_key)
    except Exception:  # noqa: BLE001
        pass


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
        _mirror_folder()  # 实时镜像: 分类/子分类增删改名即刻落到 data/标签库/
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
        _mirror_folder()
        return _json_response({"ok": True})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)


async def backup_library(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/backup -> 把当前合并库存入 data/备份库/。"""
    try:
        lib = library.get_merged()
        lib.pop("_meta", None)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        tmp = BACKUP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lib, f, ensure_ascii=False, indent=1)
        os.replace(tmp, BACKUP_PATH)
        return _json_response({"ok": True, "path": BACKUP_PATH,
                               "mtime": int(os.stat(BACKUP_PATH).st_mtime)})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)


async def backup_info(_request: web.Request) -> web.Response:
    """GET /taglib/api/library/backup -> 备份是否存在及时间。"""
    if os.path.isfile(BACKUP_PATH):
        st = os.stat(BACKUP_PATH)
        return _json_response({"ok": True, "exists": True,
                               "mtime": int(st.st_mtime), "size": st.st_size})
    return _json_response({"ok": True, "exists": False})


async def restore_backup(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/restore-backup -> 从备份恢复 (整体覆盖当前库)。"""
    if not os.path.isfile(BACKUP_PATH):
        return _json_response({"ok": False, "error": "还没有备份 (先「💾 存为默认库」)"}, 404)
    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("categories"), list):
            raise ValueError("备份文件缺少 categories")
        library.save_user_library(data)
        _mirror_folder()
        return _json_response({"ok": True})
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"恢复失败: {exc}"}, 500)


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


# ------------------------------------------------------------ conflicts

async def get_conflicts(_request: web.Request) -> web.Response:
    """GET /taglib/api/conflicts -> 规则 + 失效清单 + AI 说明。"""
    return _json_response(tagconflicts.get_state(library.get_merged()))


async def save_conflicts(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts {rules} -> 整树保存 (设置弹窗用)。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    result = tagconflicts.save_rules(rules)
    state = tagconflicts.get_state(library.get_merged())
    return _json_response({**result, "invalid": state["invalid"]})


async def preview_conflicts_import(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts/preview-import {rules} -> dry-run 校验 (不落盘)。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    lib = library.get_merged()
    idx = tagconflicts._lib_index(lib)
    invalid = []
    kept = []
    for i, r in enumerate(rules):
        if not tagconflicts._valid_shape(r):
            invalid.append({"index": i, "id": r.get("id") or f"#{i}", "reason": "格式不合法"})
            continue
        kept.append(r)
        _, ok_l = tagconflicts.resolve_ref(r["left"], idx)
        if not ok_l:
            invalid.append({"index": i, "id": r.get("id"), "reason":
                            f"库中不存在: {r['left'].get('value')}"})
        for ref in r.get("right", []):
            _, ok_r = tagconflicts.resolve_ref(ref, idx)
            if not ok_r:
                invalid.append({"index": i, "id": r.get("id"), "reason":
                                f"库中不存在: {ref.get('value')}"})
    return _json_response({"ok": True, "total": len(rules), "valid": len(kept),
                           "invalid": invalid})


async def apply_conflicts_import(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts/import {rules, mode: replace|merge} -> 落盘。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    mode = payload.get("mode") or "replace"
    if mode == "merge":
        existing = tagconflicts.load_rules()
        have = {(str(r.get("id")), json.dumps(r.get("left"), sort_keys=True),
                 json.dumps(r.get("right"), sort_keys=True)) for r in existing}
        for r in rules:
            key = (str(r.get("id")), json.dumps(r.get("left"), sort_keys=True),
                   json.dumps(r.get("right"), sort_keys=True))
            if key not in have:
                existing.append(r)
                have.add(key)
        rules = existing
    result = tagconflicts.save_rules(rules)
    state = tagconflicts.get_state(library.get_merged())
    return _json_response({**result, "mode": mode, "invalid": state["invalid"]})


async def check_conflicts(request: web.Request) -> web.Response:
    """POST {ens: [tag en ...]} -> 冲突体检结果。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    ens = [str(e) for e in (payload.get("ens") or [])]
    return _json_response({"ok": True,
                           "conflicts": tagconflicts.check_selection(ens, library.get_merged())})


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
    app.router.add_post("/taglib/api/library/backup", backup_library)
    app.router.add_get("/taglib/api/library/backup", backup_info)
    app.router.add_post("/taglib/api/library/restore-backup", restore_backup)
    app.router.add_get("/taglib/api/tagfiles", list_tagfiles)
    app.router.add_post("/taglib/api/tagfiles/import", import_tagfile)
    app.router.add_post("/taglib/api/tagfiles/preview-import", preview_import)
    app.router.add_post("/taglib/api/tagfiles/export-folder", export_folder)
    app.router.add_get("/taglib/api/conflicts", get_conflicts)
    app.router.add_post("/taglib/api/conflicts", save_conflicts)
    app.router.add_post("/taglib/api/conflicts/check", check_conflicts)
    app.router.add_post("/taglib/api/conflicts/preview-import", preview_conflicts_import)
    app.router.add_post("/taglib/api/conflicts/import", apply_conflicts_import)
