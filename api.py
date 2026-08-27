"""HTTP 路由: /taglib (管理页) 与 /taglib/api/* (数据接口)。"""

from __future__ import annotations

import json
import os
import time

from aiohttp import web

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import library
except ImportError:  # pragma: no cover
    import library
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
