"""标签文件 (.md) 读写 —— 兼容 re-export 壳。

1.8.3 起按职责拆成四个模块 (纯搬移, 零逻辑改动):

    tagparse.py   解析: .md -> 库树 (+ 路径常量; 它是叶子模块)
    tagmeta.py    编辑层 sidecar: _tagmeta.json
    tagsync.py    清单与同步状态: 指纹 / _sync_state.json / 双向计划 / 文件夹 -> 库
    tagmirror.py  镜像: 库 -> 文件夹 (严格一致)

拆的原因是它 788 行里混了四件事, 改一处要在四个方向里找。外部导入路径
(`from . import tagfiles; tagfiles.parse_tagfile(...)`) 全部保持不变 —— 这里只做搬运。
"""

from __future__ import annotations

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from .tagmeta import (  # noqa: F401  (对外保持可用)
        TAG_META_NAME, _tag_meta_of, _write_tag_meta, apply_tag_meta, load_tag_meta)
    from .tagmirror import (  # noqa: F401
        _GUIDE_TEXT, _ILLEGAL_FS, _desired_files, export_to_folder, sanitize_fsname,
        sync_to_folder)
    from .tagparse import (  # noqa: F401
        BUILTIN_DIR, LIBRARY_DIR, _LINE_CAT, _LINE_COMMENT, _LINE_SUB, _TAG_RE,
        _TAG_SPLIT, _clean, _slug_en, apply_implied_headings, dedupe_against,
        load_file_text, merge_tree_by_name, parse_tagfile, scan_folder)
    from .tagsync import (  # noqa: F401
        SYNC_STATE_NAME, _load_sync_state, _migrate_legacy_folder, _save_sync_state,
        _scan_fingerprint, folder_sync_plan, import_files_into, mark_synced)
except ImportError:  # pragma: no cover
    from tagmeta import (  # noqa: F401
        TAG_META_NAME, _tag_meta_of, _write_tag_meta, apply_tag_meta, load_tag_meta)
    from tagmirror import (  # noqa: F401
        _GUIDE_TEXT, _ILLEGAL_FS, _desired_files, export_to_folder, sanitize_fsname,
        sync_to_folder)
    from tagparse import (  # noqa: F401
        BUILTIN_DIR, LIBRARY_DIR, _LINE_CAT, _LINE_COMMENT, _LINE_SUB, _TAG_RE,
        _TAG_SPLIT, _clean, _slug_en, apply_implied_headings, dedupe_against,
        load_file_text, merge_tree_by_name, parse_tagfile, scan_folder)
    from tagsync import (  # noqa: F401
        SYNC_STATE_NAME, _load_sync_state, _migrate_legacy_folder, _save_sync_state,
        _scan_fingerprint, folder_sync_plan, import_files_into, mark_synced)
