"""文件夹同步的清单与状态 (_sync_state.json) + 文件夹 -> 库 的导入。

指纹 = 全部 .md 的 (mtime, size); `folder_sync_plan` 用它和库 mtime 判断这一轮该
pull (文件 -> 库) / mirror (库 -> 文件) / none。

从 tagfiles.py 按职责拆出的四个模块之一 (1.8.3, 纯搬移零逻辑改动)。
"""

from __future__ import annotations

import json
import os

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import jsonio, tagparse
    from .tagmeta import apply_tag_meta
    from .tagparse import (LIBRARY_DIR, apply_implied_headings, dedupe_against,
                           load_file_text, merge_tree_by_name, parse_tagfile)
except ImportError:  # pragma: no cover
    import jsonio
    import tagparse
    from tagmeta import apply_tag_meta
    from tagparse import (LIBRARY_DIR, apply_implied_headings, dedupe_against,
                          load_file_text, merge_tree_by_name, parse_tagfile)

SYNC_STATE_NAME = "_sync_state.json"


def _migrate_legacy_folder() -> None:
    """旧版中文目录 数据/标签库 → data/taglib (一次性, 旧在新无时执行)。"""
    lib_dir = tagparse.LIBRARY_DIR
    legacy = os.path.join(os.path.dirname(lib_dir), "标签库")
    if os.path.isdir(legacy) and not os.path.isdir(lib_dir):
        try:
            os.rename(legacy, lib_dir)
        except OSError:
            pass


def _scan_fingerprint(folder: str) -> dict[str, list]:
    """收集非 `_` 开头的 .md/.txt 的 {相对路径: [mtime, size]}。目录不存在返回 None。"""
    if not os.path.isdir(folder):
        return None
    fp: dict[str, list] = {}
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if fn.startswith(("_", ".", "~$")) or not fn.lower().endswith((".md", ".txt")):
                continue
            p = os.path.join(root, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rel = os.path.relpath(p, folder)
            fp[rel] = [round(st.st_mtime, 3), st.st_size]
    return fp


def _load_sync_state(folder: str) -> dict | None:
    path = os.path.join(folder, SYNC_STATE_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_sync_state(folder: str) -> None:
    """以当前磁盘指纹写入清单 (基线)。"""
    fp = _scan_fingerprint(folder)
    if fp is None:
        return
    os.makedirs(folder, exist_ok=True)
    jsonio.atomic_write_json(os.path.join(folder, SYNC_STATE_NAME), {"fingerprint": fp})


def mark_synced(folder: str = LIBRARY_DIR, lib_key: tuple = ()) -> None:
    """把当前磁盘指纹 + 库 mtime 记为已同步基线 (公开接口)。"""
    fp = _scan_fingerprint(folder)
    if fp is None:
        return
    os.makedirs(folder, exist_ok=True)
    jsonio.atomic_write_json(os.path.join(folder, SYNC_STATE_NAME),
                             {"fingerprint": fp, "lib_key": list(lib_key)}, indent=None)


def folder_sync_plan(folder: str, lib_key: tuple) -> tuple:
    """热同步决策 (双向核对): 清单同时记录 文件夹指纹 与 库 mtime。

    返回:
      ("baseline", None)         无清单/目录缺失 -> 整体镜像建立基线 (自动修复漂移)
      ("pull", [changed files], [missing rels])  文件夹有外部改动 -> 处理
        - changed  = 新增/修改的文件 -> 吸入库
        - missing  = 文件夹里被删除的文件 -> 单向删除开=镜像回填; 关=库同步删除
      ("mirror", None)           库在清单之后变过 (保存漏镜像/JSON 被手改) -> 重新镜像
      ("none", None)             两侧一致, 无需动作
    """
    state = _load_sync_state(folder)
    fp = _scan_fingerprint(folder)
    if state is None or fp is None:
        return ("baseline", None, [])
    old_fp = state.get("fingerprint") or {}
    if fp != old_fp:
        changed, missing = [], []
        for rel, meta in fp.items():
            if old_fp.get(rel) != meta:
                parts = rel.split(os.sep)
                cat_dir = parts[0] if len(parts) >= 2 else None
                sub_dir = parts[1] if len(parts) >= 3 else None
                changed.append({"path": os.path.join(folder, rel),
                                "cat_dir": cat_dir, "sub_dir": sub_dir})
        for rel in old_fp:
            if rel not in fp:
                missing.append(rel)
        return ("pull", changed, missing)
    if tuple(state.get("lib_key") or ()) != tuple(lib_key):
        return ("mirror", None, [])
    return ("none", None, [])


def import_files_into(base: dict, files: list[dict]) -> dict:
    """把变更文件解析后按名称吸入 base 快照 (只增不删, 自动去重)。"""
    total_new = 0
    for info in files:
        try:
            text = load_file_text(info["path"])
        except OSError:
            continue
        text = apply_implied_headings(text, info.get("cat_dir"), info.get("sub_dir"))
        tree = parse_tagfile(text)
        apply_tag_meta(tree)   # 编辑层字段从 sidecar 还原 (aliases/priority/rarity/enabled)
        _tree, stats = dedupe_against(tree, base)
        if stats["total_new"]:
            merge_tree_by_name(base, _tree)
            total_new += stats["total_new"]
    return {"total_new": total_new, "files": len(files)}
