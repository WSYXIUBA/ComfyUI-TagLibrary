"""编辑层字段 sidecar (_tagmeta.json) —— aliases / priority / rarity / enabled。

.md 只承载输出层字段 (en/zh/weight/nsfw/gender), 这些编辑层字段按 en 查表存这里,
于是"文件夹重建库"(pull / 清空重导 / user.json 损坏重建) 不再静默丢字段 (1.7.0)。

`_` 前缀 = 指纹扫描 / 导入扫描 / 清空保留 都跳过, 不会形成同步循环。

从 tagfiles.py 按职责拆出的四个模块之一 (1.8.3, 纯搬移零逻辑改动)。
"""

from __future__ import annotations

import json
import os

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import jsonio, tagparse
except ImportError:  # pragma: no cover
    import jsonio
    import tagparse

TAG_META_NAME = "_tagmeta.json"


def _tag_meta_of(lib: dict, skip_ens=None) -> dict[str, dict]:
    """合并库 → {en_lower: 仅非默认的编辑层字段}。默认值不进 sidecar, 控制体积。

    1.8.0: skip_ens —— 扩展包词不进 sidecar (与镜像过滤同口径)。
    """
    out: dict[str, dict] = {}
    skip_ens = skip_ens or set()
    for cat in lib.get("categories", []):
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []):
                en_l = str(t.get("en") or "").strip().lower()
                if not en_l or en_l in skip_ens:
                    continue
                entry: dict = {}
                if t.get("aliases"):
                    entry["aliases"] = list(t["aliases"])
                try:
                    if float(t.get("priority", 50) or 50) != 50:
                        entry["priority"] = float(t["priority"])
                except (TypeError, ValueError):
                    pass
                if t.get("rarity") and t["rarity"] != "common":
                    entry["rarity"] = str(t["rarity"])
                if t.get("enabled") is False:
                    entry["enabled"] = False
                if entry:
                    out[en_l] = entry
    return out


def _write_tag_meta(lib: dict, folder: str, skip_ens=None) -> None:
    os.makedirs(folder, exist_ok=True)
    payload = {"version": 1, "tags": _tag_meta_of(lib, skip_ens=skip_ens)}
    jsonio.atomic_write_json(os.path.join(folder, TAG_META_NAME), payload)


def load_tag_meta(folder: str | None = None) -> dict:
    """sidecar → {en_lower: meta}; 缺失/损坏 = 空 (不炸)。

    folder 默认 None = 调用时取 tagparse.LIBRARY_DIR (测试沙箱会替换该全局, 不能在
    定义期绑定默认值)。
    """
    folder = folder or tagparse.LIBRARY_DIR
    try:
        with open(os.path.join(folder, TAG_META_NAME), "r", encoding="utf-8") as f:
            data = json.load(f)
        tags = data.get("tags")
        return tags if isinstance(tags, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_tag_meta(tree: dict, folder: str | None = None) -> dict:
    """把 sidecar 字段就地补进解析树的同名标签。

    parse_tagfile 会把 aliases/enabled 物化成默认值 ([]) / True —— 所以:
      aliases/priority/rarity 只填"缺省或空"; enabled 只做单向还原
      (sidecar 说停用 → 覆盖成 False, 绝不反向把停用改回启用)。
    """
    meta = load_tag_meta(folder)
    if not meta:
        return tree
    for cat in tree.get("categories", []):
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []):
                m = meta.get(str(t.get("en") or "").strip().lower())
                if not m:
                    continue
                if m.get("aliases") and not t.get("aliases"):
                    t["aliases"] = list(m["aliases"])
                if "priority" in m and "priority" not in t:
                    t["priority"] = m["priority"]
                if m.get("rarity") and not t.get("rarity"):
                    t["rarity"] = m["rarity"]
                if m.get("enabled") is False:
                    t["enabled"] = False
    return tree
