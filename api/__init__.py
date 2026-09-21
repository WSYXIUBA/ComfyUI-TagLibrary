"""HTTP 路由包: /taglib (管理页) 与 /taglib/api/* (数据接口)。

按域拆分为四个子模块 (库 / 标签文件 / 反冲突 / 1.3.0 引擎), 本文件只做
对外契约与路由注册 —— 外部导入路径保持 `from .api import register_routes` 不变。
"""

from __future__ import annotations

from ._common import (_WEB_DIR, _json_response,  # noqa: F401  (对外保持可用)
                      taglib_csrf_middleware)
from .library_routes import (
    serve_manager_page, get_library, get_subtags, search_tags, get_panel_index,
    save_library, reset_library, backup_library, backup_info, restore_backup,
    export_library, import_library, lookup_tags,
    get_settings, save_settings, dismiss_upgrade_prompt,
)
from .conflicts_routes import (
    get_conflicts, save_conflicts, preview_conflicts_import,
    apply_conflicts_import, check_conflicts,
)
from .v13_routes import (
    get_profiles, save_profiles, get_grouprules, save_grouprules,
    get_nl, save_nl, draw_tags,
)
from .v18_routes import (
    get_presets, draw_batch, draw_reroll, absorb, absorb_add,
)
from .tag_edit_routes import (
    get_axes_overview, preview_derive, create_tag, update_tag, get_incomplete,
)

try:
    from server import PromptServer
except ModuleNotFoundError:  # 独立导入时不炸
    PromptServer = None

__all__ = ["register_routes"]

def register_routes() -> None:
    if PromptServer is None or PromptServer.instance is None:
        return
    app = PromptServer.instance.app
    # 页面 + API 直接挂主应用 (PromptServer.app 是暴露的 aiohttp Application)
    # CSRF 防护中间件: 只拦 /taglib/api/* 的跨站写请求, 其余路由零影响
    app.middlewares.append(taglib_csrf_middleware)
    app.router.add_get("/taglib", serve_manager_page)
    # 管理页的 js/css 走静态子路径 (避免相对路径解析到根 404)
    app.router.add_static("/taglib/static/", _WEB_DIR)
    app.router.add_get("/taglib/api/library", get_library)
    app.router.add_get("/taglib/api/panel-index", get_panel_index)
    app.router.add_get("/taglib/api/subtags", get_subtags)
    app.router.add_get("/taglib/api/search", search_tags)
    app.router.add_post("/taglib/api/library", save_library)
    app.router.add_delete("/taglib/api/library", reset_library)
    app.router.add_post("/taglib/api/library/backup", backup_library)
    app.router.add_get("/taglib/api/library/backup", backup_info)
    app.router.add_post("/taglib/api/library/restore-backup", restore_backup)
    app.router.add_get("/taglib/api/library/export", export_library)
    app.router.add_post("/taglib/api/library/import", import_library)
    app.router.add_post("/taglib/api/tags-lookup", lookup_tags)
    app.router.add_post("/taglib/api/library/upgrade-dismiss", dismiss_upgrade_prompt)
    app.router.add_get("/taglib/api/settings", get_settings)
    app.router.add_post("/taglib/api/settings", save_settings)
    app.router.add_get("/taglib/api/conflicts", get_conflicts)
    app.router.add_post("/taglib/api/conflicts", save_conflicts)
    app.router.add_post("/taglib/api/conflicts/check", check_conflicts)
    app.router.add_post("/taglib/api/conflicts/preview-import", preview_conflicts_import)
    app.router.add_post("/taglib/api/conflicts/import", apply_conflicts_import)
    # 1.3.0 新架构端点
    app.router.add_get("/taglib/api/profiles", get_profiles)
    app.router.add_post("/taglib/api/profiles", save_profiles)
    app.router.add_get("/taglib/api/grouprules", get_grouprules)
    app.router.add_post("/taglib/api/grouprules", save_grouprules)
    app.router.add_get("/taglib/api/nl", get_nl)
    app.router.add_post("/taglib/api/nl", save_nl)
    app.router.add_post("/taglib/api/draw", draw_tags)
    app.router.add_get("/taglib/api/presets", get_presets)
    app.router.add_post("/taglib/api/draw_batch", draw_batch)
    app.router.add_post("/taglib/api/draw_reroll", draw_reroll)
    app.router.add_post("/taglib/api/absorb", absorb)
    app.router.add_post("/taglib/api/absorb_add", absorb_add)
    # 编辑体验改造 (2026-09-19): 流水线首页 / 标签就地编辑 / 待完善汇总
    app.router.add_get("/taglib/api/axes-overview", get_axes_overview)
    app.router.add_post("/taglib/api/tag/derive", preview_derive)
    app.router.add_post("/taglib/api/tag/create", create_tag)
    app.router.add_post("/taglib/api/tag/update", update_tag)
    app.router.add_get("/taglib/api/tag/incomplete", get_incomplete)
