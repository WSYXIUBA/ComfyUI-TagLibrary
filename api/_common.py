"""共享常量与工具 (路由模块共用)。"""

from __future__ import annotations

import json
import os
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
