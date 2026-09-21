"""标签库路由: 管理页 / 库 CRUD / 备份恢复 / 设置 / 面板索引。"""

from __future__ import annotations

import json
import os
import re

from aiohttp import web

from .. import jsonio
from .. import library
from .. import slotpolicy
from ._common import (
    _WEB_DIR, BACKUP_DIR, FACTORY_BACKUP_PATH, USER_BACKUP_PATH,
    UPGRADE_PROMPT_PATH, LEGACY_BACKUP_PATH, USER_AUTO_BACKUP_PATH, _json_response,
)


async def serve_manager_page(_request: web.Request) -> web.Response:
    """GET /taglib -> 独立管理页。"""
    path = os.path.join(_WEB_DIR, "manager.html")
    if not os.path.exists(path):
        return _json_response({"error": "manager.html not found"}, 404)
    with open(path, "rb") as f:
        body = f.read()
    return web.Response(body=body, content_type="text/html", charset="utf-8")


# ---------------------------------------------------------------- api

# 插件版本 (单一真源 = pyproject.toml)。前端面板把它与自己编译进来的 TL_BUILD 比对,
# 不一致就提示"插件已更新, 点这里刷新" —— 改完 JS 用户不用自己猜要不要刷新。
def _read_plugin_version() -> str:
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "unknown"
    except Exception:  # noqa: BLE001 — 版本读不到不该影响服务
        return "unknown"


PLUGIN_VERSION = _read_plugin_version()

# 导出 .json 的 `_说明` (JSON 没有注释, 用保留键; 导入时会被剥掉)
_EXPORT_DOC = {
    "格式": "categories[].subcategories[].tags[] 三级树。标签字段: en(英文词,必填) / zh(中文) / "
            "weight(权重) / enabled(是否可用) / priority(优先级) / rarity(稀有度) / aliases(别名) / "
            "groups(分组) / requires(需同现) / mutex_with(互斥) / nsfw / minor_block",
    "合并顺序": "出厂库 → 扩展包(ext.*) → 我的层; 分类/子分类按 name 合并, 标签按 en 合并, 后者覆盖前者",
    "scope": "merged = 三级归并后的整库 (含出厂内容); user = 只有「我的」层的增删改, 可叠加到别人的库上",
    "导入": "只覆盖「我的」层, 出厂库与扩展包不动。导入整库文件时它整体成为「我的」层 (等于换一套库); "
            "导入前建议先在管理页点「💾 存为默认库」留个备份",
    "规则不在本文件": "互斥域见 data/default/taglib/conflicts.json, 分组域见 grouprules.json, "
                "NL 风味见 nl_flavors.json, 道具档案见 profiles.json, 出厂预设见 presets.json",
    "保留键": "_说明 = 本说明 (导入时自动剥掉); _cleared = 空库标记; _tombstones = 删除墓碑 (防旧文件回魂)",
}


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


async def get_panel_index(_request: web.Request) -> web.Response:
    """GET /taglib/api/panel-index -> 节点面板所需的轻量索引。

    面板实际只需要三样东西: 分类名/图标 (chip 分组标题与类目排序)、每个词的
    树路径 (en → [大类, 子类, 孙类])、词的性别/NSFW 标记 (回显反查与过滤)。
    标签正文只有挑选器用得到 —— /taglib/api/library 全量约 1.27MB, 面板每次
    启动都整个拉下来是纯浪费。这里只回索引进而省掉大部分体积 (实测约 1/5),
    挑选器改为「打开时才懒加载全量」。

    路径口径与前端 buildLibPath 完全一致: 先按孙分类 (groups) 记名, 再记直属
    标签 (已有条目不被覆盖)。

    体积优化: 路径不重复内联分类名, 而是 (子分类下标, 孙分类下标) 二元组 ——
    分类名在 subs/groups 里去重后只出现一次 (实测 336KB -> 约 120KB)。
    """
    lib = library.get_merged()
    cats: list[dict] = []
    subs: list[list] = []                 # [[大类名, 子类名], ...]
    caps: list[list[int]] = []            # 与 subs 同序: [下限, 上限] = 引擎内置槽位配额
    groups: list[str] = []                # 去重后的孙分类名
    groups_idx: dict[str, int] = {}
    paths: dict[str, list] = {}           # en_lower -> [子分类下标, 孙分类下标] (-1=直属)
    gender: dict[str, str] = {}
    nsfw: list[str] = []

    def _note(t: dict, path: list) -> None:
        en_l = str(t.get("en", "")).strip().lower()
        if not en_l:
            return
        if en_l not in paths:
            paths[en_l] = path
        g = str(t.get("gender") or "").strip().lower()
        if g in ("female", "male"):
            gender[en_l] = g
        if t.get("nsfw"):
            nsfw.append(en_l)

    for c in lib.get("categories", []) or []:
        cname = str(c.get("name", ""))
        cats.append({"name": cname,
                     "icon": str(c.get("icon") or ""),
                     "color": str(c.get("color") or "")})
        for s in c.get("subcategories", []) or []:
            sname = str(s.get("name", ""))
            si = len(subs)
            subs.append([cname, sname])
            # 引擎内置配额 (真源 = slotpolicy.SLOT_MAX)。带上它, 面板才能显示
            # 「引擎实际会出几个」—— 此前面板固定显示 1/1, 而引擎按 SLOT_MAX 走
            # (画质增强 5/3、眼部 2 …), 用户按面板理解必然算错。
            mn, mx = slotpolicy.caps_for(f"{cname}/{sname}")
            caps.append([mn, mx])
            for g in s.get("groups") or []:
                gname = str(g.get("name", ""))
                if gname not in groups_idx:
                    groups_idx[gname] = len(groups)
                    groups.append(gname)
                gi = groups_idx[gname]
                for t in g.get("tags") or []:
                    _note(t, [si, gi])
            for t in s.get("tags") or []:
                _note(t, [si, -1])

    return _json_response({"ok": True,
                           "mtime": library._mtime(library.USER_PATH),
                           "version": PLUGIN_VERSION,
                           "cats": cats, "subs": subs, "groups": groups,
                           "caps": caps,
                           "paths": paths, "gender": gender, "nsfw": nsfw,
                           "count": len(paths)})


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
        cleared = {"version": 1, "categories": [], "_cleared": True, "_tombstones": []}
        jsonio.atomic_write_json(library.USER_PATH, cleared)
        library.invalidate_cache()
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
        jsonio.atomic_write_json(USER_BACKUP_PATH, lib)
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
    else:  # auto: 手动备份 > 自动滚动备份 > 出厂备份
        for cand in (USER_BACKUP_PATH, USER_AUTO_BACKUP_PATH, FACTORY_BACKUP_PATH):
            if os.path.isfile(cand):
                path = cand
                break
        else:
            path = FACTORY_BACKUP_PATH
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
        # 恢复成功 → 升级弹窗使命完成, 销毁标记
        try:
            if os.path.isfile(UPGRADE_PROMPT_PATH):
                os.remove(UPGRADE_PROMPT_PATH)
        except OSError:
            pass
        return _json_response({"ok": True, "source": ("user" if path == USER_BACKUP_PATH
                               else "auto" if path == USER_AUTO_BACKUP_PATH else "factory")})
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"恢复失败: {exc}"}, 500)


async def export_library(request: web.Request) -> web.Response:
    """GET /taglib/api/library/export?scope=merged|user -> 下载一份库 .json。

    merged (默认): 出厂库 + 扩展包 + 我的层 三级归并后的整库 —— 拿去导入即得完整一套。
    user: 只有「我的」层 (增删改), 文件小, 可叠加到别人的库存上。

    JSON 不支持注释, 所以用保留键 `_说明` 写清格式与规则 (导入时会被剥掉, 不进库)。
    """
    scope = (request.query.get("scope") or "merged").strip()
    if scope == "user":
        data = library.load_user_raw()
        name = "tag_library_user.json"
    else:
        data = json.loads(json.dumps(library.get_merged()))
        name = "tag_library_full.json"
    data.pop("_meta", None)
    body = json.dumps({"_说明": _EXPORT_DOC, **data}, ensure_ascii=False, indent=1)
    return web.Response(
        text=body, content_type="application/json", charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"',
                 "Cache-Control": "no-store"},
    )


async def import_library(request: web.Request) -> web.Response:
    """POST /taglib/api/library/import {library} -> 把一份库 .json 导进「我的」层。

    **只覆盖用户层**: 出厂库与扩展包不动 (最安全)。导入的是整库文件时, 这份内容整体
    成为「我的」层 → 盖住出厂层, 效果等于换一套库; 导入的是「我的」导出时, 就是原样还魂。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    data = payload.get("library") if isinstance(payload.get("library"), dict) else payload
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        return _json_response({"ok": False, "error": "文件里没有 categories 数组, 不是库文件"}, 400)
    clean = json.loads(json.dumps(data))
    clean.pop("_说明", None)
    clean.pop("_meta", None)
    try:
        result = library.save_user_library(clean)
    except library.LibraryError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"ok": False, "error": f"导入失败: {exc}"}, 500)
    return _json_response({"ok": True, **(result or {})})


async def lookup_tags(request: web.Request) -> web.Response:
    """POST /taglib/api/tags-lookup {ens:[...]} -> {tags:{en:{zh,cat,sub}}}

    预设快照里的词可能只存了 en (出厂预设只有 pinned 词表) → 面板补词时按显示语言
    需要 zh。这里按 en 现查合并库, 只给点名的那些词, 不整库传中文 (index 已经很肥)。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    ens = payload.get("ens")
    if not isinstance(ens, list):
        return _json_response({"ok": False, "error": "ens 必须是数组"}, 400)
    want = {str(x).strip().lower() for x in ens[:2000] if str(x).strip()}
    out: dict[str, dict] = {}
    for cat in library.get_merged().get("categories", []):
        cat_name = cat.get("name") or ""
        for sub in cat.get("subcategories", []):
            sub_name = sub.get("name") or ""
            for t in sub.get("tags", []):
                en = str(t.get("en") or "").strip().lower()
                if en and en in want and en not in out:
                    out[en] = {"zh": t.get("zh") or "", "cat": cat_name, "sub": sub_name}
    return _json_response({"ok": True, "tags": out})


async def get_settings(_request: web.Request) -> web.Response:
    """GET /taglib/api/settings -> 合并后的 settings。"""
    lib = library.get_merged()
    return _json_response({"ok": True, "settings": dict(lib.get("settings") or {})})


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
        jsonio.atomic_write_json(library.USER_PATH, user_raw)
        library.invalidate_cache()
    else:
        merged = json.loads(json.dumps(library.get_merged()))
        merged.pop("_meta", None)
        merged.setdefault("settings", {})
        merged["settings"].update(incoming)
        client_mtime = request.headers.get("X-TagLib-Mtime")
        library.save_user_library(merged, float(client_mtime) if client_mtime else None)
    lib = library.get_merged()
    return _json_response({"ok": True, "settings": dict(lib.get("settings") or {})})


async def dismiss_upgrade_prompt(_request: web.Request) -> web.Response:
    """POST /taglib/api/library/upgrade-dismiss -> 用户点「取消」: 销毁弹窗标记, 不恢复。"""
    try:
        if os.path.isfile(UPGRADE_PROMPT_PATH):
            os.remove(UPGRADE_PROMPT_PATH)
        return _json_response({"ok": True})
    except OSError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 500)

