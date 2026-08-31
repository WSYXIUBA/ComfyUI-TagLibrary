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
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "default", "backups")
# 双备份体系 (2026-08-30 用户设计):
#   出厂备份  = 插件包内自带, 随升级覆盖, 代表"当前版本官方库"
#   用户备份  = 用户点「存为默认库」生成, 插件包不带, 升级后存活, 代表"用户自己的基准"
# v1.1.1: 目录 data/备份库 -> data/default/backups, 文件名中文 -> 英文 (旧名启动时自动迁移)
FACTORY_BACKUP_PATH = os.path.join(BACKUP_DIR, "factory_backup.json")
USER_BACKUP_PATH = os.path.join(BACKUP_DIR, "user_backup.json")
# 升级弹窗标记: 插件包内自带; 恢复/取消后销毁; 下次升级随包重新出现
UPGRADE_PROMPT_PATH = os.path.join(BACKUP_DIR, ".upgrade-pending")
# 兼容旧名 (v1.1.0 中文目录/文件名 -> 启动时自动迁移为新英文名)
LEGACY_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "备份库")
LEGACY_BACKUP_PATH = os.path.join(LEGACY_BACKUP_DIR, "tag_library.backup.json")
LEGACY_FACTORY_PATH = os.path.join(LEGACY_BACKUP_DIR, "tag_library.出厂.backup.json")
LEGACY_USER_PATH = os.path.join(LEGACY_BACKUP_DIR, "tag_library.用户.backup.json")
LEGACY_UPGRADE_PROMPT = os.path.join(LEGACY_BACKUP_DIR, ".升级待确认")


def _migrate_legacy_backup_layout() -> None:
    """v1.1.0 中文备份布局 (data/备份库/*.中文.backup.json) -> v1.1.1 (data/default/backups/*.json)。

    data/default/backups 已存在时跳过 (library.py 的目录迁移会把整个 备份库 挪进 default/,
    那时目录名还是中文 — 这里负责把中文目录内容并入 backups/ 并改名)。
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    pairs = [
        (LEGACY_FACTORY_PATH, FACTORY_BACKUP_PATH),
        (LEGACY_USER_PATH, USER_BACKUP_PATH),
        (LEGACY_UPGRADE_PROMPT, UPGRADE_PROMPT_PATH),
    ]
    # library.py 目录迁移后, 中文目录在 data/default/备份库
    legacy_dir_moved = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "data", "default", "备份库")
    if os.path.isdir(legacy_dir_moved):
        pairs.extend([
            (os.path.join(legacy_dir_moved, "tag_library.出厂.backup.json"), FACTORY_BACKUP_PATH),
            (os.path.join(legacy_dir_moved, "tag_library.用户.backup.json"), USER_BACKUP_PATH),
            (os.path.join(legacy_dir_moved, ".升级待确认"), UPGRADE_PROMPT_PATH),
        ])
    migrated = False
    for src, dst in pairs:
        if os.path.isfile(src) and not os.path.isfile(dst):
            try:
                os.replace(src, dst)
                migrated = True
            except OSError:
                pass
    if migrated:
        print("[TagLibrary] 📦 备份文件已迁移为英文命名: data/default/backups/")


_migrate_legacy_backup_layout()


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

def _skeleton(lib: dict) -> dict:
    """分类树骨架: 不含标签正文, 只有 id/名称/计数 (方案 V2.1 阶段 4)。"""
    cats = []
    for c in lib.get("categories", []):
        subs = [{"id": s.get("id"), "name": s.get("name"),
                 "tag_count": len(s.get("tags") or [])}
                for s in c.get("subcategories", [])]
        cats.append({"id": c.get("id"), "name": c.get("name"),
                     "icon": c.get("icon"), "color": c.get("color"),
                     "subcategories": subs})
    return {"version": lib.get("version", 1),
            "schema_version": lib.get("schema_version", 2),
            "categories": cats}


async def get_library(request: web.Request) -> web.Response:
    """GET /taglib/api/library[?mode=skeleton]

    skeleton 模式返回分类树骨架 (无标签正文), 供管理页首屏快速渲染;
    标签正文经 /taglib/api/subtags 按子分类懒加载。
    """
    lib = library.get_merged()
    if request.query.get("mode") == "skeleton":
        return _json_response({
            "ok": True,
            "mtime": library._mtime(library.USER_PATH),
            "library": _skeleton(lib),
        })
    return _json_response({
        "ok": True,
        "mtime": library._mtime(library.USER_PATH),
        "library": lib,
    })


async def get_subtags(request: web.Request) -> web.Response:
    """GET /taglib/api/subtags?cat_id=&sub_id= -> 单个子分类的标签正文 (懒加载)。"""
    cat_id = request.query.get("cat_id") or ""
    sub_id = request.query.get("sub_id") or ""
    lib = library.get_merged()
    for c in lib.get("categories", []):
        if c.get("id") != cat_id:
            continue
        for s in c.get("subcategories", []):
            if s.get("id") == sub_id:
                return _json_response({
                    "ok": True,
                    "tags": s.get("tags") or [],
                    "groups": s.get("groups") or [],
                })
    return _json_response({"ok": False, "error": f"子分类不存在: {sub_id}"}, 404)


async def search_tags(request: web.Request) -> web.Response:
    """GET /taglib/api/search?q= -> 服务端全文搜索 (en/zh/别名), 上限 500 条。"""
    q = (request.query.get("q") or "").strip().lower()
    if not q:
        return _json_response({"ok": True, "results": []})
    lib = library.get_merged()
    results = []
    for c in lib.get("categories", []):
        cname = c.get("name", "")
        for s in c.get("subcategories", []):
            sname = s.get("name", "")
            for t in s.get("tags", []) or []:
                en = str(t.get("en", ""))
                if (q in en.lower() or q in str(t.get("zh", "")).lower()
                        or any(q in str(a).lower() for a in (t.get("aliases") or []))):
                    results.append({
                        "cat": cname, "cat_id": c.get("id"),
                        "sub": sname, "sub_id": s.get("id"),
                        "en": en, "zh": t.get("zh", ""),
                        "nsfw": bool(t.get("nsfw")),
                        "weight": t.get("weight", 1.0),
                    })
                    if len(results) >= 500:
                        return _json_response({"ok": True, "results": results,
                                               "truncated": True, "count": len(results)})
    return _json_response({"ok": True, "results": results, "count": len(results)})


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
        # 数据丢失护栏: 载荷标签数骤减 (如懒加载未完成就保存) → 拒绝
        # (清空标签库走 DELETE 端点, 不受此护栏影响)
        try:
            cur_total = sum(len(s.get("tags") or [])
                            for c in library.get_merged().get("categories", [])
                            for s in c.get("subcategories", []))
            new_total = sum(len(s.get("tags") or [])
                            for c in payload.get("categories", [])
                            for s in c.get("subcategories", []))
        except Exception:  # noqa: BLE001
            cur_total = new_total = 0
        if cur_total >= 20 and new_total < cur_total * 0.5:
            return _json_response({
                "ok": False,
                "error": (f"保存被拒绝: 提交载荷 {new_total} 个标签, 远少于当前库 "
                          f"{cur_total} 个 (疑似加载未完成)。请刷新管理页重试; "
                          f"大批量删除请使用「🗑 清空标签库」或分批进行。"),
            }, 409)
        client_mtime = request.headers.get("X-TagLib-Mtime")
        result = library.save_user_library(
            payload,
            client_mtime=float(client_mtime) if client_mtime else None,
        )
        _mirror_folder()  # 实时镜像: 分类/子分类增删改名即刻落到 data/taglib/
        return _json_response(result)
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"保存失败: {exc}"}, 500)


async def reset_library(_request: web.Request) -> web.Response:
    """DELETE /taglib/api/library -> 「🗑 清空标签库」: 用户库清成空库 (0分类0标签)。

    不动默认库文件、不动备份文件。空库状态由 user.json 的 _cleared 标记表达,
    下次导入模板/管理页保存会自动退出空库状态。
    """
    try:
        os.makedirs(library.DEFAULT_DATA_DIR, exist_ok=True)
        cleared = {"version": 1, "categories": [], "_cleared": True, "_tombstones": []}
        tmp = library.USER_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cleared, f, ensure_ascii=False, indent=1)
        os.replace(tmp, library.USER_PATH)
        library.invalidate_cache()
        # taglib 镜像文件夹同步清空 (删除全部分类文件夹, 保留 _ 开头文件与 conflicts.json)
        keep = {"conflicts.json", "_sync_state.json", "_说明.md"}
        lib_dir = tagfiles.LIBRARY_DIR
        if os.path.isdir(lib_dir):
            for entry in os.listdir(lib_dir):
                p = os.path.join(lib_dir, entry)
                if entry in keep or entry.startswith("_"):
                    continue
                import shutil
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try: os.remove(p)
                    except OSError: pass
        # 重建空基线, 防止热同步把清空前状态判定为 pull
        library.sync_to_folder_snapshot()
        return _json_response({"ok": True})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)


async def backup_library(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/backup -> 「💾 存为默认库」。

    当前合并库存为 用户备份 (tag_library.用户.backup.json) 并升格为默认库基准。
    出厂备份 (tag_library.出厂.backup.json) 永不被此操作覆盖。
    """
    try:
        lib = library.get_merged()
        lib.pop("_meta", None)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        tmp = USER_BACKUP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lib, f, ensure_ascii=False, indent=1)
        os.replace(tmp, USER_BACKUP_PATH)
        # 用户备份不存在时 (首次点存为默认库), 出厂备份尚未生成 → 从当前默认库补生成
        if not os.path.isfile(FACTORY_BACKUP_PATH) and os.path.isfile(LEGACY_BACKUP_PATH):
            try:
                import shutil
                shutil.copy(LEGACY_BACKUP_PATH, FACTORY_BACKUP_PATH)
            except OSError:
                pass
        return _json_response({"ok": True, "path": USER_BACKUP_PATH,
                               "mtime": int(os.stat(USER_BACKUP_PATH).st_mtime)})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)


async def backup_info(_request: web.Request) -> web.Response:
    """GET /taglib/api/library/backup -> 双备份状态 + 升级弹窗标记。

    惰性迁移: v1.x 旧单备份 (tag_library.backup.json) 首次访问时复制为出厂备份。
    """
    if not os.path.isfile(FACTORY_BACKUP_PATH) and os.path.isfile(LEGACY_BACKUP_PATH):
        try:
            import shutil
            shutil.copy(LEGACY_BACKUP_PATH, FACTORY_BACKUP_PATH)
        except OSError:
            pass
    def _info(path):
        if os.path.isfile(path):
            st = os.stat(path)
            return {"exists": True, "mtime": int(st.st_mtime), "size": st.st_size}
        return {"exists": False}
    out = {"ok": True,
           "factory": _info(FACTORY_BACKUP_PATH),
           "user": _info(USER_BACKUP_PATH),
           "upgrade_prompt": os.path.isfile(UPGRADE_PROMPT_PATH),
           "legacy": _info(LEGACY_BACKUP_PATH)}
    return _json_response(out)


async def restore_backup(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/restore-backup {source?: "user"|"factory"} -> 「↺ 恢复默认库」。

    优先用户备份; 用户备份不存在时回落出厂备份。恢复后销毁升级弹窗标记。
    """
    payload = {}
    if _request.can_read_body:
        try:
            payload = await _request.json()
        except Exception:
            payload = {}
    source = str(payload.get("source") or "auto")
    if source == "user":
        path = USER_BACKUP_PATH
    elif source == "factory":
        path = FACTORY_BACKUP_PATH
    else:  # auto: 用户备份优先
        path = USER_BACKUP_PATH if os.path.isfile(USER_BACKUP_PATH) else FACTORY_BACKUP_PATH
        if not os.path.isfile(path) and os.path.isfile(LEGACY_BACKUP_PATH):
            path = LEGACY_BACKUP_PATH  # v1.x 旧单备份兼容
    if not os.path.isfile(path):
        return _json_response({"ok": False,
                               "error": "还没有备份文件 (点「💾 存为默认库」生成用户备份)"}, 404)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("categories"), list):
            raise ValueError("备份文件缺少 categories")
        library.save_user_library(data)
        _mirror_folder()
        # 恢复成功 → 升级弹窗使命完成, 销毁标记
        try:
            if os.path.isfile(UPGRADE_PROMPT_PATH):
                os.remove(UPGRADE_PROMPT_PATH)
        except OSError:
            pass
        return _json_response({"ok": True, "source": "user" if path == USER_BACKUP_PATH
                               else "factory"})
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"恢复失败: {exc}"}, 500)


async def get_settings(_request: web.Request) -> web.Response:
    """GET /taglib/api/settings -> 合并后的 settings (含 one_way_delete 等开关)。"""
    lib = library.get_merged()
    settings = dict(lib.get("settings") or {})
    settings.setdefault("one_way_delete", True)
    return _json_response({"ok": True, "settings": settings})


async def save_settings(request: web.Request) -> web.Response:
    """POST /taglib/api/settings {settings} -> 合并进用户库 settings 并落盘。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    incoming = payload.get("settings")
    if not isinstance(incoming, dict):
        return _json_response({"ok": False, "error": "settings 必须是对象"}, 400)
    # 在当前用户库快照上合并 settings (不动分类树)
    user_raw = library.load_user_raw()
    if user_raw.get("_cleared"):
        user_raw["settings"] = {**(user_raw.get("settings") or {}), **incoming}
        tmp = library.USER_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(user_raw, f, ensure_ascii=False, indent=1)
        os.replace(tmp, library.USER_PATH)
        library.invalidate_cache()
    else:
        merged = json.loads(json.dumps(library.get_merged()))
        merged.pop("_meta", None)
        merged.setdefault("settings", {})
        merged["settings"].update(incoming)
        client_mtime = request.headers.get("X-TagLib-Mtime")
        library.save_user_library(merged, float(client_mtime) if client_mtime else None)
    lib = library.get_merged()
    settings = dict(lib.get("settings") or {})
    settings.setdefault("one_way_delete", True)
    return _json_response({"ok": True, "settings": settings})


async def dismiss_upgrade_prompt(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/upgrade-dismiss -> 用户点「取消」: 销毁弹窗标记, 不恢复。"""
    try:
        if os.path.isfile(UPGRADE_PROMPT_PATH):
            os.remove(UPGRADE_PROMPT_PATH)
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
    app.router.add_get("/taglib/api/subtags", get_subtags)
    app.router.add_get("/taglib/api/search", search_tags)
    app.router.add_post("/taglib/api/library", save_library)
    app.router.add_delete("/taglib/api/library", reset_library)
    app.router.add_post("/taglib/api/library/backup", backup_library)
    app.router.add_get("/taglib/api/library/backup", backup_info)
    app.router.add_post("/taglib/api/library/restore-backup", restore_backup)
    app.router.add_post("/taglib/api/library/upgrade-dismiss", dismiss_upgrade_prompt)
    app.router.add_get("/taglib/api/settings", get_settings)
    app.router.add_post("/taglib/api/settings", save_settings)
    app.router.add_get("/taglib/api/tagfiles", list_tagfiles)
    app.router.add_post("/taglib/api/tagfiles/import", import_tagfile)
    app.router.add_post("/taglib/api/tagfiles/preview-import", preview_import)
    app.router.add_post("/taglib/api/tagfiles/export-folder", export_folder)
    app.router.add_get("/taglib/api/conflicts", get_conflicts)
    app.router.add_post("/taglib/api/conflicts", save_conflicts)
    app.router.add_post("/taglib/api/conflicts/check", check_conflicts)
    app.router.add_post("/taglib/api/conflicts/preview-import", preview_conflicts_import)
    app.router.add_post("/taglib/api/conflicts/import", apply_conflicts_import)
