"""数据路径真源 (1.12.0)。

原 `tagparse.LIBRARY_DIR` —— 1.8.3 四拆后 tagparse 成了「路径常量 + .md 解析」混居地。
1.12.0 删除 .md 镜像层（tagparse/tagmirror/tagsync/tagmeta/tagfiles），常量搬到这里独立，
`grouprules` / `nl` / `profiles` / `tagconflicts` / `api` 一律从这里取。

目录内容（1.12.0 起**只有 .json**，没有 .md）:
    conflicts.json / nsfw_conflicts.json      互斥域
    grouprules.json / nsfw_grouprules.json    分组域
    nl_flavors.json / nsfw_nl.json            NL 风味
    profiles.json                             道具档案
    presets.json                              出厂预设
"""
from __future__ import annotations

import os

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(_PKG_DIR, "data", "default", "taglib")
