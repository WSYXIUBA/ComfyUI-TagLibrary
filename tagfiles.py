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
    used_sids = set()
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
            n = 2
            while sid in used_sids:
                sid = f"{cid}.{sid_base}-{n}"
                n += 1
            used_sids.add(sid)
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
    """扫描标签文件夹 (最多两层目录 = 大类/子分类), 列出 .md/.txt 文件。

    目录结构约定 (与标签库管理页两级分类一一对应):
        <root>/<大类>/<子分类>/xxx.md     -> cat_dir=大类, sub_dir=子分类
        <root>/<大类>/xxx.md              -> cat_dir=大类 (分类以文件内标题为准)
        <root>/xxx.md                     -> cat_dir=None (分类以文件内标题为准)

    文件内容若完全无 `#`/`##` 标题, 导入时会按所在文件夹名补隐含标题
    (见 apply_implied_headings)。以 `.` `_` `~$` 开头的条目跳过。

    返回 [{file_name, path, size, source: 'builtin'|'external', mtime,
           cat_dir, sub_dir}]
    """
    items: list[dict] = []

    def _scan_dir(root: str, source: str, cat_dir: str | None, sub_dir: str | None):
        if not root or not os.path.isdir(root):
            return
        for fn in sorted(os.listdir(root)):
            if fn.startswith((".", "_", "~$")):
                continue
            p = os.path.join(root, fn)
            if os.path.isdir(p):
                if cat_dir is None:
                    _scan_dir(p, source, fn, None)      # 一级目录 = 大类
                elif sub_dir is None:
                    _scan_dir(p, source, cat_dir, fn)   # 二级目录 = 子分类
                # 更深层级不再展开
            elif os.path.isfile(p) and fn.lower().endswith((".md", ".txt")):
                st = os.stat(p)
                items.append({"file_name": fn, "path": p, "source": source,
                              "size": st.st_size, "mtime": int(st.st_mtime),
                              "cat_dir": cat_dir, "sub_dir": sub_dir})

    _scan_dir(builtin_dir or "", "builtin", None, None)
    _scan_dir(folder or "", "external", None, None)
    return items


def apply_implied_headings(text: str, cat_dir: str | None, sub_dir: str | None) -> str:
    """文件内容没有任何 `#` 标题时, 按所在文件夹名补隐含的两级标题。"""
    if cat_dir is None:
        return text
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") and not s.startswith("#!"):
            return text  # 文件自带标题, 尊重文件内容
    head = f"# {cat_dir}\n"
    if sub_dir:
        head += f"## {sub_dir}\n"
    return head + text


_ILLEGAL_FS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def sanitize_fsname(name: str, fallback: str = "未命名") -> str:
    """把分类名转成合法的文件夹/文件名 (Windows 保留字符剔除)。"""
    clean = _ILLEGAL_FS.sub("_", (name or "").strip()).strip(" .")
    return clean[:60] or fallback


def export_to_folder(lib: dict, folder: str) -> dict:
    """把库镜像导出为两级文件夹结构: <folder>/<大类>/<子分类>.md。

    - 每个子分类一个 .md, 文件内容自带 `# 大类` / `## 子类` 标题 (可再次导入/直接发 AI)
    - 同名文件覆盖写, 不删除文件夹里的其他既有文件
    - 孙分类 groups (若有) 的标签并入子分类文件
    返回统计 {categories, subcategories, files, tags, folder}。
    """
    os.makedirs(folder, exist_ok=True)
    used_cats: set[str] = set()
    stats = {"categories": 0, "subcategories": 0, "files": 0, "tags": 0,
             "folder": folder}

    def _uniq(taken: set[str], base: str) -> str:
        cand, n = base, 2
        while cand.lower() in taken:
            cand = f"{base}({n})"
            n += 1
        taken.add(cand.lower())
        return cand

    def _tag_piece(t: dict) -> str:
        s = (t.get("en") or "").strip()
        if not s:
            return ""
        if t.get("zh"):
            s += f"({t['zh']})"
        w = float(t.get("weight") or 1.0)
        if abs(w - 1.0) > 1e-6:
            s += f"{{{w:g}}}"
        if t.get("nsfw"):
            s += "[nsfw]"
        return s

    for cat in lib.get("categories", []):
        cat_name = cat.get("name") or cat.get("id") or "未命名"
        cdir_name = _uniq(used_cats, sanitize_fsname(cat_name))
        cdir = os.path.join(folder, cdir_name)
        os.makedirs(cdir, exist_ok=True)
        used_subs: set[str] = set()
        for sub in cat.get("subcategories", []):
            sub_name = sub.get("name") or "未命名"
            tags = list(sub.get("tags") or [])
            for g in sub.get("groups") or []:
                tags.extend(g.get("tags") or [])
            sdir_name = _uniq(used_subs, sanitize_fsname(sub_name))
            sdir = os.path.join(cdir, sdir_name)
            os.makedirs(sdir, exist_ok=True)
            fname = f"{sdir_name}.md"
            lines = [f"# {cat_name}", f"## {sub_name}", ""]
            pieces = [_tag_piece(t) for t in tags]
            pieces = [p for p in pieces if p]
            if pieces:
                for i in range(0, len(pieces), 6):
                    lines.append(", ".join(pieces[i:i + 6]))
            else:
                lines.append("<!-- (此子分类暂无标签) -->")
            with open(os.path.join(sdir, fname), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            stats["subcategories"] += 1
            stats["files"] += 1
            stats["tags"] += len(pieces)
        stats["categories"] += 1

    guide = os.path.join(folder, "_说明.md")
    if not os.path.exists(guide):
        with open(guide, "w", encoding="utf-8") as f:
            f.write(
                "# 标签库文件夹\n"
                "<!-- 本文件以 _ 开头, 插件扫描时自动跳过 -->\n\n"
                "目录结构 = 标签库分类结构:\n"
                "- 第一层子文件夹 = 一级分类 (如 质量与技术)\n"
                "- 第二层子文件夹 = 二级分类 (如 画质强化)\n"
                "- 二级分类文件夹里的 .md = 该子分类的标签 (可放多个文件)\n"
                "- .md 文件格式: `# 大类` / `## 子类` 两级标题 + 标签行\n"
                "  标签语法: `english(中文翻译){权重}[nsfw]`, 逗号分隔\n"
                "  没有标题的文件会按所在文件夹名自动归分类\n\n"
                "在标签库管理页「📂 标签文件」可: 扫描导入本文件夹的文件 / "
                "把当前库同步导出到这里。\n"
            )
    return stats


def load_file_text(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _slug_en(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", (text or "").lower()).strip("-")[:40]
    return slug or fallback


def merge_tree_by_name(base: dict, new_tree: dict) -> dict:
    """把导入树按【名称】合并进 base (完整库快照, 就地修改并返回)。

    中文分类名的 slug 会退化 ("质量与技术" -> "cat"), 旧版按生成的
    imported.<slug> id 匹配必然产生同名重复分类。这里改为:
      - 大类/子分类: 先按名称在 base 里找现有结构, 命中则并入;
        未命中才新建 (id 唯一性对 base 全量查重)。
      - 标签: 调用方已做过跨库 en 去重, 这里对同子分类内再兜底去重。
    """
    def _tag_id_taken(tree: dict) -> set[str]:
        taken = set()
        for c in tree.get("categories", []):
            for s in c.get("subcategories", []):
                for t in s.get("tags", []):
                    if t.get("id"):
                        taken.add(t["id"])
        return taken

    used_tag_ids = _tag_id_taken(base)

    def _uniq_id(taken: set[str], cand: str) -> str:
        n = 2
        while cand in taken:
            cand = f"{cand}-{n}"
            n += 1
        taken.add(cand)
        return cand

    base.setdefault("categories", [])
    cat_index = {c.get("name", "").strip().lower(): c for c in base["categories"]}
    used_cat_ids = {c.get("id") for c in base["categories"]}

    def _new_cat_id(cname: str) -> str:
        # ASCII 名用 slug; 中文名 slug 退化 -> 用计数器, 绝不产生相互覆盖的固定 id
        slug = _slug_en(cname, "")
        if slug:
            cand = f"imported.{slug}"
            if cand not in used_cat_ids:
                used_cat_ids.add(cand)
                return cand
        n = 1
        while f"imported.c{n}" in used_cat_ids:
            n += 1
        used_cat_ids.add(f"imported.c{n}")
        return f"imported.c{n}"

    for ncat in new_tree.get("categories", []):
        cname = (ncat.get("name") or "").strip() or "导入标签"
        cat = cat_index.get(cname.lower())
        if cat is None:
            cat = {"id": _new_cat_id(cname), "name": cname,
                   "icon": ncat.get("icon", "📦"), "color": ncat.get("color", "#888888"),
                   "subcategories": []}
            base["categories"].append(cat)
            cat_index[cname.lower()] = cat
        used_sub_ids = {s.get("id") for s in cat.get("subcategories", [])}
        sub_index = {s.get("name", "").strip().lower(): s for s in cat.get("subcategories", [])}
        for nsub in ncat.get("subcategories", []):
            sname = (nsub.get("name") or "").strip() or "未分类"
            sub = sub_index.get(sname.lower())
            if sub is None:
                sid = _uniq_id(used_sub_ids, f"{cat['id']}.{_slug_en(sname, 'sub')}")
                sub = {"id": sid, "name": sname, "tags": []}
                cat.setdefault("subcategories", []).append(sub)
                sub_index[sname.lower()] = sub
            have = {(t.get("en") or "").strip().lower() for t in sub.get("tags", [])}
            for t in nsub.get("tags", []):
                en_l = (t.get("en") or "").strip().lower()
                if not en_l or en_l in have:
                    continue
                t["id"] = _uniq_id(used_tag_ids, f"{sub['id']}.{_slug_en(t.get('en') or '', 'tag')}")
                sub.setdefault("tags", []).append(t)
                have.add(en_l)
    return base


BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tagfiles")
LIBRARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "标签库")


def default_external_dir() -> str:
    return BUILTIN_DIR
