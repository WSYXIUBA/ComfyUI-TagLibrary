"""共享常量与工具 (路由模块共用)。"""

from __future__ import annotations

import json
import os
import re
import time

from aiohttp import web

# 本模块位于 <root>/api/ 下, 路径常量统一以仓库根为基准
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from .. import library
from .. import tagfiles
from .. import tagconflicts
from .. import runtime_snapshot
from .. import profiles as _profiles
from .. import grouprules as _grouprules
from .. import nl as _nl
from .. import engine as _engine


_WEB_DIR = os.path.join(_PKG_DIR, "web")


BACKUP_DIR = os.path.join(_PKG_DIR, "data", "default", "backups")


# 双备份体系 (2026-08-30 用户设计):
#   出厂备份  = 插件包内自带, 随升级覆盖, 代表"当前版本官方库"
#   用户备份  = 用户点「存为默认库」生成, 插件包不带, 升级后存活, 代表"用户自己的基准"
# v1.1.1: 目录 data/备份库 -> data/default/backups, 文件名中文 -> 英文 (旧名启动时自动迁移)
FACTORY_BACKUP_PATH = os.path.join(BACKUP_DIR, "factory_backup.json")


USER_BACKUP_PATH = os.path.join(BACKUP_DIR, "user_backup.json")


# 升级弹窗标记: 插件包内自带; 恢复/取消后销毁; 下次升级随包重新出现
UPGRADE_PROMPT_PATH = os.path.join(BACKUP_DIR, ".upgrade-pending")


# 兼容旧名 (v1.1.0 中文目录/文件名 -> 启动时自动迁移为新英文名)
LEGACY_BACKUP_DIR = os.path.join(_PKG_DIR, "data", "备份库")


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
    legacy_dir_moved = os.path.join(_PKG_DIR,
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


# ---------------------------------------------------------------- CSRF 防护

# 浏览器跨站攻击模型: ComfyUI 主应用无鉴权, 用户浏览器里打开的任意网页都可以把
# 请求打进 http://127.0.0.1:8188 —— 用 text/plain 的"简单请求"即可绕过 CORS
# 预检, 让删库/覆盖库/向任意路径导出文件真正执行 (响应读不到, 但破坏已发生)。
# 防护思路: 写方法 (POST/PUT/DELETE/PATCH) 一旦带了 Origin/Referer 且指向别处,
# 一律拒绝。三类合法调用者全部放行:
#   1. 本插件页面 (节点面板/管理页) —— 同源, Origin 与 Host 一致
#   2. curl / 测试脚本等非浏览器客户端 —— 通常不带 Origin/Referer
#   3. 反向代理后的同域页面 —— authority(含端口) 归一后与 Host 一致
_UNSAFE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_API_PREFIX = "/taglib/api/"
_ORIGIN_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://([^/?#]+)", re.IGNORECASE)


def _authority_of(origin_url: str) -> str | None:
    """从 Origin/Referer 里取 authority (host[:port]); 取不到返回 None。"""
    m = _ORIGIN_RE.match(str(origin_url or "").strip())
    return m.group(1) if m else None


def _norm_authority(authority: str | None) -> str:
    """authority 归一: 小写 + 去默认端口 (http :80 / https :443)。"""
    a = str(authority or "").strip().lower()
    if a.endswith(":80"):
        a = a[:-3]
    elif a.endswith(":443"):
        a = a[:-4]
    return a


def csrf_rejected(request: web.Request) -> bool:
    """该写请求是否应被 CSRF 防护拒绝 (只判 /taglib/api/* 的写方法)。"""
    if request.method not in _UNSAFE_METHODS:
        return False
    if not request.path.startswith(_API_PREFIX):
        return False
    origin_header = (request.headers.get("Origin") or "").strip()
    if origin_header:
        if origin_header.lower() == "null":
            return True          # 沙箱 iframe / file:// 等不透明来源, 拒
        origin_authority = _authority_of(origin_header)
        if not origin_authority:
            return True          # 形态怪异的 Origin: 浏览器不会发, 保守拒绝
    else:
        # 老浏览器/某些环境不发 Origin 只发 Referer —— 取其 authority
        origin_authority = _authority_of(request.headers.get("Referer"))
    if not origin_authority:
        return False             # 无来源信息 → 非浏览器客户端 (curl/测试脚本) 放行
    return _norm_authority(origin_authority) != _norm_authority(request.host)


@web.middleware
async def taglib_csrf_middleware(request: web.Request, handler):
    """aiohttp 中间件: 挡掉指向本插件写接口的跨站请求 (403)。

    只作用于 /taglib/api/*, ComfyUI 其余路由零影响; 同源请求/无 Origin 请求直通。
    """
    if csrf_rejected(request):
        return _json_response(
            {"ok": False, "error": "跨站请求被拒绝 (CSRF 防护): Origin/Referer 与服务地址不一致"},
            403)
    return await handler(request)


# ---------------------------------------------------------------- page


def _mirror_folder() -> None:
    """库 -> 文件夹实时同步 (保存/导入/重置后调用)。失败不影响请求。"""
    try:
        lib_key = (library._mtime(library.DEFAULT_PATH),
                   library._mtime(library.USER_PATH))
        tagfiles.sync_to_folder(library.get_merged())
        tagfiles.mark_synced(lib_key=lib_key)
    except Exception:  # noqa: BLE001
        pass


_migrate_legacy_backup_layout()
