"""库 -> 文件夹 的镜像写出 (严格一致)。

- 写出/更新 `<大类>/<子分类>/<子分类>.md`, 内容未变则跳过 (避免 mtime 抖动)
- 大类文件夹下不在期望集合里的 .md/.txt 删除; 根目录散文件与 `_` 开头文件不动
- 空文件夹向上清理; 更新 _sync_state.json 指纹基线, 防止刚写的文件被回吸
- 顺带写出编辑层 sidecar (见 tagmeta.py) 与 `_说明.md`

从 tagfiles.py 按职责拆出的四个模块之一 (1.8.3, 纯搬移零逻辑改动)。
"""

from __future__ import annotations

import os
import re

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from .tagmeta import _write_tag_meta
    from .tagparse import LIBRARY_DIR
    from .tagsync import _save_sync_state
except ImportError:  # pragma: no cover
    from tagmeta import _write_tag_meta
    from tagparse import LIBRARY_DIR
    from tagsync import _save_sync_state


_ILLEGAL_FS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def sanitize_fsname(name: str, fallback: str = "未命名") -> str:
    """把分类名转成合法的文件夹/文件名 (Windows 保留字符剔除)。"""
    clean = _ILLEGAL_FS.sub("_", (name or "").strip()).strip(" .")
    return clean[:60] or fallback


def _desired_files(lib: dict, folder: str, skip_ens=None,
                   skip_sub_ids=None) -> dict[str, str]:
    """库 -> {相对路径: 文件内容}。路径形如 <大类>/<子分类>/<子分类>.md。

    1.8.0: skip_ens / skip_sub_ids —— 扩展包 (ext) 词与扩展槽位不进镜像,
    文件夹镜像只反映出厂库视图, 露骨词不落被 git 跟踪的 .md。
    """
    out: dict[str, str] = {}
    skip_ens = skip_ens or set()
    skip_sub_ids = skip_sub_ids or set()

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
        zh = t.get("zh") or ""
        # zh 无 CJK (如 'HDR') 时丢弃 — 解析端无法区分括号归属
        if zh and any("\u4e00" <= ch <= "\u9fff" for ch in zh):
            s += f"({zh})"
        w = float(t.get("weight") or 1.0)
        if abs(w - 1.0) > 1e-6:
            s += f"{{{w:g}}}"
        if t.get("nsfw"):
            s += "[nsfw]"
        if t.get("gender") == "female":
            s += "[♀]"
        elif t.get("gender") == "male":
            s += "[♂]"
        return s

    used_cats: set[str] = set()
    for cat in lib.get("categories", []):
        cat_name = cat.get("name") or cat.get("id") or "未命名"
        cdir_name = _uniq(used_cats, sanitize_fsname(cat_name))
        used_subs: set[str] = set()
        for sub in cat.get("subcategories", []):
            sub_name = sub.get("name") or "未命名"
            if str(sub.get("id") or "") in skip_sub_ids:
                continue
            tags = [t for t in (sub.get("tags") or [])
                    if str(t.get("en") or "").strip().lower() not in skip_ens]
            for g in sub.get("groups") or []:
                tags.extend(g.get("tags") or [])
            sdir_name = _uniq(used_subs, sanitize_fsname(sub_name))
            lines = [f"# {cat_name}", f"## {sub_name}", ""]
            pieces = [p for p in (_tag_piece(t) for t in tags) if p]
            if pieces:
                for i in range(0, len(pieces), 6):
                    lines.append(", ".join(pieces[i:i + 6]))
            else:
                lines.append("<!-- (此子分类暂无标签) -->")
            rel = os.path.join(cdir_name, sdir_name, f"{sdir_name}.md")
            out[rel] = "\n".join(lines) + "\n"
    return out


_GUIDE_TEXT = (
    "# 标签库文件夹\n"
    "<!-- 本文件以 _ 开头, 插件扫描时自动跳过 -->\n\n"
    "本文件夹就是标签库的存储路径, 与管理页实时双向同步:\n"
    "- 第一层子文件夹 = 一级分类 (如 质量与技术)\n"
    "- 第二层子文件夹 = 二级分类 (如 画质强化)\n"
    "- 二级分类文件夹里的 .md = 该子分类的标签\n"
    "- 管理页里增删/改名分类, 这里的文件夹会同步增删/改名\n"
    "- 手动在文件里加标签 (格式: `english(中文翻译){权重}[nsfw][♀|♂]`, 逗号分隔)\n"
    "- [nsfw]=NSFW标记; [♀]=女性专属 [♂]=男性专属 (绝对性别词才标)\n"
    "  保存文件后, 刷新网页即可在插件里看到 (自动按文件夹归类+去重)\n"
    "- 没有标题的文件按所在文件夹名归分类; `_` 开头的文件跳过\n"
)



def sync_to_folder(lib: dict, folder: str = LIBRARY_DIR, *,
                   skip_ens=None, skip_sub_ids=None) -> dict:
    """把库严格镜像到两级文件夹 (库 -> 文件夹方向的实时同步)。

    - 写出/更新 <大类>/<子分类>/<子分类>.md (内容未变则跳过, 避免无效 mtime 抖动)
    - 大类文件夹下不在期望集合里的 .md/.txt 会被删除 (文件夹=库, 严格一致);
      根目录散文件与 `_` 开头文件不动
    - 清空后空文件夹向上清理
    - 更新同步清单 (_sync_state.json: 指纹基线), 防止刚写的文件被回吸
    返回统计。
    """
    os.makedirs(folder, exist_ok=True)
    desired = _desired_files(lib, folder, skip_ens=skip_ens,
                             skip_sub_ids=skip_sub_ids)
    stats = {"categories": 0, "subcategories": len(desired), "files_written": 0,
             "files_removed": 0, "tags": 0, "folder": folder}
    stats["categories"] = len({rel.split(os.sep)[0] for rel in desired})

    def _count_tags(content: str) -> int:
        n = 0
        for line in content.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("<!--"):
                continue
            n += s.count(",") + 1
        return n

    stats["tags"] = sum(_count_tags(c) for c in desired.values())

    # ① 删除大类文件夹下多余的 .md/.txt (严格镜像)
    for entry in sorted(os.listdir(folder)):
        cdir = os.path.join(folder, entry)
        if not os.path.isdir(cdir) or entry.startswith(("_", ".", "~$")):
            continue
        for root, _dirs, files in os.walk(cdir):
            for fn in files:
                if fn.startswith(("_", ".", "~$")) or not fn.lower().endswith((".md", ".txt")):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), folder)
                if rel not in desired:
                    try:
                        os.remove(os.path.join(root, fn))
                        stats["files_removed"] += 1
                    except OSError:
                        pass

    # ② 写出期望文件 (内容相同则跳过)
    for rel, content in desired.items():
        path = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if f.read() == content:
                        continue
            except OSError:
                pass
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        stats["files_written"] += 1

    # ③ 清理空文件夹 (第二层先清, 再看第一层)
    for entry in sorted(os.listdir(folder)):
        cdir = os.path.join(folder, entry)
        if not os.path.isdir(cdir) or entry.startswith(("_", ".", "~$")):
            continue
        for sub in sorted(os.listdir(cdir)):
            sdir = os.path.join(cdir, sub)
            if os.path.isdir(sdir) and not os.listdir(sdir):
                os.rmdir(sdir)
        if not os.listdir(cdir):
            os.rmdir(cdir)

    # ④ 说明文件
    guide = os.path.join(folder, "_说明.md")
    if not os.path.exists(guide):
        with open(guide, "w", encoding="utf-8") as f:
            f.write(_GUIDE_TEXT)

    # ⑤ 编辑层字段 sidecar: .md 只承载输出层字段 (en/zh/weight/nsfw/gender),
    #    aliases/priority/rarity/enabled 走 _tagmeta.json 按 en 查表 ——
    #    "文件夹重建库" (pull/清空重导) 不再静默丢字段 (1.7.0)
    _write_tag_meta(lib, folder, skip_ens=skip_ens)

    _save_sync_state(folder)
    return stats


def export_to_folder(lib: dict, folder: str) -> dict:
    """兼容旧名: 见 sync_to_folder。"""
    return sync_to_folder(lib, folder)
