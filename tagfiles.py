"""标签文件 (.md) 解析器 —— 单文件、内部分类、逗号分隔标签。

文件格式规范:

    # 分类名
    ## 子分类名

    tag英文(中文翻译), another tag, 第三个 [nsfw], 带权重的(翻译){1.2}, plain

规则:
  * `# ` 开头      -> 一级分类 (新分类)
  * `## ` 开头     -> 二级子分类
  * 其余非空行     -> 标签列表, 逗号 (中文全角，也支持) 分隔
  * 标签语法:      `英文` 或 `英文(中文)` 或 `英文{权重}` 或 `英文(中文){1.2}`
                   后缀 `[nsfw]` 表示 NSFW 标签, 可与上述组合:
                   `nsfw_tag(某描述) {1.1} [nsfw]`
  * 同一分类下重复出现同名 `## 子分类` 会自动合并条目
  * 未写子分类直接出现的标签 -> 归入「未分类」
  * 空行 / `---` 分隔线 / HTML 注释 <!-- --> 被忽略

id 生成: category:slug(en), 冲突时追加序号 —— 由 import_conflicts 处理,
导入方负责对重复 (en 相同) 标签去重。
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

# 预编译
_LINE_CAT = re.compile(r"^#\s+(.+)$")
_LINE_SUB = re.compile(r"^##\s+(.+)$")
_LINE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_SPLIT = re.compile(r"[,，\n]")
_TAG_RE = re.compile(
    r"""^\s*
    (?P<en>[^(\[]+?)              # en 文本: 贪婪到第一个 ( 或 [ 前, 允许含空格
    \s*(?:\((?P<zh>[^)]*)\))?     # 可选 (中文)
    \s*(?:\{(?P<weight>[0-9.]+)\})?  # 可选 {权重}
    \s*(?:\[(?P<flags>[^\]]*)\])?    # 可选 [flags] e.g. nsfw
    \s*$""",
    re.VERBOSE,
)


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def parse_tagfile(text: str) -> dict[str, Any]:
    """解析标签文件文本 -> 库结构 {version, categories: [...]}。

    返回结构与库 JSON 一致, 方便直接并入现有 merge 流程。
    """
    text = _LINE_COMMENT.sub("", text)
    lines = text.splitlines()

    categories: list[dict] = []
    cat_index: dict[str, dict] = {}   # name -> cat
    cur_cat: dict | None = None
    cur_sub: dict | None = None

    def ensure_cat(name: str) -> dict:
        nonlocal cur_cat
        key = name.lower()
        if key not in cat_index:
            cat_index[key] = {
                "name": name,
                "icon": "📦",
                "color": "#888888",
                "subcategories": [],
                "_new": True,
            }
            categories.append(cat_index[key])
        cur_cat = cat_index[key]
        return cur_cat

    def ensure_sub(cat: dict, name: str) -> dict:
        nonlocal cur_sub
        for s in cat["subcategories"]:
            if s.get("_raw_name", "").lower() == name.lower():
                cur_sub = s
                return s
        sub = {"_raw_name": name, "name": name, "tags": [], "_new": True}
        cat["subcategories"].append(sub)
        cur_sub = sub
        return sub

    for raw in lines:
        line = _clean(raw)
        if not line or line.startswith("---") or line.startswith(">"):
            continue
        m_cat = _LINE_SUB.match(line)
        if m_cat and cur_cat is not None:
            ensure_sub(cur_cat, m_cat.group(1))
            continue
        m_top = _LINE_CAT.match(line)
        if m_top:
            cat = ensure_cat(m_top.group(1))
            # 新分类后未立即指定子分类的兜底
            cur_sub = None
            continue
        if line.startswith("#"):  # 更深的标题当正文忽略
            continue

        # 标签行
        if cur_cat is None:
            # 文件头没给分类 -> 收进「导入标签」分类
            ensure_cat("导入标签")
        if cur_sub is None:
            cur_sub = ensure_sub(cur_cat, "未分类")

        for piece in _TAG_SPLIT.split(line):
            piece = piece.strip()
            if not piece:
                continue
            m = _TAG_RE.match(piece)
            if not m:
                continue
            en = _clean(m.group("en"))
            zh = _clean(m.group("zh") or "")
            weight_s = m.group("weight")
            flags = (m.group("flags") or "").lower()
            if not en:
                continue
            weight = 1.0
            try:
                if weight_s:
                    weight = max(0.05, min(float(weight_s), 3.0))
            except ValueError:
                pass
            tag: dict[str, Any] = {
                "en": en,
                "aliases": [],
                "weight": weight,
                "enabled": True,
            }
            if zh:
                tag["zh"] = zh
            if "nsfw" in flags:
                tag["nsfw"] = True
            cur_sub["tags"].append(tag)

    # 清理内部标记字段
    out_cats = []
    for c in categories:
        subs = []
        for s in c.get("subcategories", []):
            s.pop("_raw_name", None)
            s.pop("_new", None)
            if s["tags"]:
                subs.append(s)
        c["subcategories"] = subs
        c.pop("_new", None)
        if subs:
            out_cats.append(c)

    return {"version": 1, "categories": out_cats}


def dedupe_against(new_tree: dict, existing_lib: dict) -> tuple[dict, dict]:
    """新树 vs 已有合并库去重。

    去重键: en 小写 (跨别名不查, 保持简单可预期)。
    返回 (清洗后的 new_tree, stats)。被去掉的即视为重复。
    """
    existing = set()
    for cat in existing_lib.get("categories", []):
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []):
                existing.add(t.get("en", "").strip().lower())

    removed = 0
    kept_en = set()
    out_cats = []
    seen_cat_names = {}
    for cat in new_tree.get("categories", []):
        name = cat.get("name") or cat.get("id") or "?"
        # 同名分类合并 id: 复用已有分类 id 或生成 slug
        slug = re.sub(r"[^a-z0-9\-]+", "-", name.lower()).strip("-")[:40] or "cat"
        cid = f"imported.{slug}"
        used_tags = []
        for sub in cat.get("subcategories", []):
            kept = []
            sid_base = re.sub(r"[^a-z0-9\-]+", "-", (sub.get("name") or "misc").lower()).strip("-")[:40] or "misc"
            sid = f"{cid}.{sid_base}"
            used_ids = set()
            for t in sub.get("tags", []):
                en_l = t.get("en", "").strip().lower()
                if en_l in existing or en_l in kept_en:
                    removed += 1
                    continue
                kept_en.add(en_l)
                tid_base = re.sub(r"[^a-z0-9\-]+", "-", en_l)[:40] or "tag"
                tid = f"{sid}.{tid_base}"
                n = 2
                while tid in used_ids:
                    tid = f"{tid}-{n}"
                    n += 1
                used_ids.add(tid)
                t["id"] = tid
                kept.append(t)
            if kept:
                used_tags.append({**sub, "id": sid, "tags": kept})
        if used_tags:
            if name in seen_cat_names:
                # 合并进已输出的同名单分类
                target = seen_cat_names[name]
                target["subcategories"].extend(used_tags)
                continue
            cat_out = {"id": cid, "name": name,
                       "icon": cat.get("icon", "📥"),
                       "color": cat.get("color", "#7bed9f"),
                       "subcategories": used_tags}
            seen_cat_names[name] = cat_out
            out_cats.append(cat_out)
    new_tree["categories"] = out_cats
    stats = {"total_new": sum(len(t["tags"]) for c in out_cats for t in c["subcategories"]),
             "duplicates_removed": removed}
    return new_tree, stats


def scan_folder(folder: str, builtin_dir: str | None = None) -> list[dict]:
    """扫描文件夹内所有 .md/.txt 标签文件 (只列信息, 不解析内容)。

    返回 [{file_name, path, size, source: 'builtin'|'external', mtime}]
    """
    items = []
    def _scan(root: str, source: str):
        if not root or not os.path.isdir(root):
            return
        for fn in sorted(os.listdir(root)):
            if not fn.lower().endswith((".md", ".txt")):
                continue
            p = os.path.join(root, fn)
            if os.path.isfile(p):
                st = os.stat(p)
                items.append({"file_name": fn, "path": p, "source": source,
                              "size": st.st_size, "mtime": int(st.st_mtime)})
    _scan(builtin_dir or "", "builtin")
    _scan(folder or "", "external")
    return items


def load_file_text(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tagfiles")


def default_external_dir() -> str:
    return BUILTIN_DIR
