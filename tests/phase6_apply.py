# -*- coding: utf-8 -*-
"""阶段6扩库应用器 —— 读取 phase6_data_b*.py 数据, 修改默认库, 双写用户库同 id 子分类。

用法: python tests/phase6_apply.py b1

关键语义 (与 library.deep_merge 对齐):
  - 用户库子分类快照会整体遮蔽默认库同 id 子分类 → 每个 touched 的子分类
    都把变更镜像写进用户库 (同 id 标签修改 + 新增标签), 保证合并视图一致。
  - 新 en 查重基准 = 默认库 + 用户库 全部 en (不区分大小写)。
  - 所有写盘只发生在 --commit 时; 默认 dry-run 打印计划。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

LIB_PATH = os.path.join(ROOT, "data", "tag_library.json")
USER_PATH = os.path.join(ROOT, "data", "tag_library.user.json")

sys.path.insert(0, ROOT)
try:
    from . import schema  # noqa: F401
except ImportError:
    import schema


def _norm(x) -> str:
    return " ".join(str(x or "").split()).strip().lower()


def _slug(en: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9\-]+", "-", en.lower()).strip("-")[:40]
    return s or "tag"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def existing_en_map(*libs):
    """en_lower → (lib标签dict, 所在sub_id)。重复 en 的位置都记下来。"""
    m = {}
    for lib in libs:
        for c in lib.get("categories", []):
            for s in c.get("subcategories", []):
                for t in s.get("tags", []):
                    lo = _norm(t.get("en"))
                    m.setdefault(lo, (t, s.get("id"))).append if False else None
    return m


def build_en_index(*libs):
    idx = {}
    for lib in libs:
        for c in lib.get("categories", []):
            for s in c.get("subcategories", []):
                for t in s.get("tags", []):
                    idx.setdefault(_norm(t.get("en")), []).append((lib, c, s, t))
    return idx


def find_cat(lib, cid):
    return next((c for c in lib["categories"] if c["id"] == cid), None)


def find_sub(cat, sid):
    return next((s for s in cat.get("subcategories", []) if s["id"] == sid), None)


def make_tag(sid, en, zh, weight=1.0, nsfw=False):
    t = {
        "en": en, "zh": zh, "id": f"{sid}.{_slug(en)}",
        "weight": float(weight), "aliases": [],
        "type": "other", "priority": 50, "rarity": "common",
        "groups": [], "requires": [], "mutex_with": [],
        "desc": "", "meta": {}, "enabled": True,
    }
    if nsfw:
        t["nsfw"] = True
    return t


def apply_batch(lib_default, lib_user, batch):
    """把一个批次 dict 应用到 (默认库, 用户库)。返回 (added, edited, new_subs) 统计。"""
    added = edited = new_subs = 0
    skipped = []

    en_idx = build_en_index(lib_default, lib_user)

    for sid, spec in batch.items():
        cat_id = sid.rsplit(".", 1)[0] if "." in sid and not spec.get("new") else None
        # 子分类 id 形如 "subject.s3"; 其上级分类 id 是 id 里第一段
        cat_id = sid.split(".")[0]
        cat_d = find_cat(lib_default, cat_id)
        if cat_d is None:
            raise SystemExit(f"[FATAL] 默认库无分类 {cat_id} (子分类 {sid})")
        sub_d = find_sub(cat_d, sid)
        if sub_d is None and not spec.get("new"):
            raise SystemExit(f"[FATAL] 默认库无子分类 {sid}")

        if spec.get("new"):
            if sub_d is None:
                sub_d = {"id": sid, "name": spec.get("name", sid),
                         "tags": [], "icon": spec.get("icon", "📦")}
                cat_d.setdefault("subcategories", []).append(sub_d)
                new_subs += 1
            else:
                # 已存在 (重跑幂等): 补名字
                sub_d.setdefault("name", spec.get("name", sid))

        # ---- 用户库侧定位/创建同 id 子分类 ----
        cat_u = find_cat(lib_user, cat_id)
        if cat_u is None:
            cat_u = {"id": cat_d["id"], "name": cat_d["name"],
                     "icon": cat_d.get("icon", "🏷️"), "color": cat_d.get("color", "#888888"),
                     "subcategories": []}
            lib_user["categories"].append(cat_u)
        sub_u = find_sub(cat_u, sid)
        if sub_u is None:
            # 用户库无此子分类快照 → 默认库的改动本来就透传, 不需要建
            sub_u = None

        adds = spec.get("adds", [])
        edits = spec.get("edits", {})
        moves = spec.get("moves", [])  # (en, from_sid, to_sid)
        dels = spec.get("dels", [])

        # ---- 移动 (en 唯一时) ----
        for en, from_sid, to_sid in moves:
            lo = _norm(en)
            hit = en_idx.get(lo) or []
            hit_in_from = [x for x in hit if x[2]["id"] == from_sid]
            if not hit_in_from:
                skipped.append(f"move {en}: {from_sid} 未找到")
                continue
            src_lib, src_cat, src_sub, tag = hit_in_from[0]
            if len([x for x in hit if x[2]["id"] != from_sid]) > 0:
                skipped.append(f"move {en}: en 多处存在, 跳过防误移")
                continue
            src_sub["tags"].remove(tag)
            dst_cat = find_cat(src_lib, to_sid.split(".")[0])
            dst_sub = find_sub(dst_cat, to_sid)
            if dst_sub is None:
                raise SystemExit(f"[FATAL] 目标子分类不存在 {to_sid}")
            if any(_norm(t.get("en")) == lo for t in dst_sub["tags"]):
                skipped.append(f"move {en}: 目标已存在, 丢弃源副本")
            else:
                tag = dict(tag)
                tag["id"] = f"{to_sid}.{_slug(en)}"
                dst_sub["tags"].append(tag)
            edited += 1

        # ---- 删除 ----
        for en in dels:
            lo = _norm(en)
            for hit_lib, hit_cat, hit_sub, tag in list(en_idx.get(lo) or []):
                hit_sub["tags"].remove(tag)
            en_idx.pop(lo, None)
            edited += 1

        # ---- 编辑 (en → 字段) ----
        for en, fields in edits.items():
            lo = _norm(en)
            for _, _, _, tag in en_idx.get(lo) or []:
                tag.update(fields)
                edited += 1

        # ---- 新增 (查重) ----
        for item in adds:
            en, zh = item[0], item[1]
            weight = item[2] if len(item) > 2 and isinstance(item[2], (int, float)) else 1.0
            nsfw = bool(item[3]) if len(item) > 3 else False
            lo = _norm(en)
            if lo in en_idx:
                hit_lib, hit_cat, hit_sub, hit_tag = en_idx[lo][0]
                if spec.get("adopt") and hit_lib is lib_user:
                    # 迁移模式: 从用户库旧位置搬进本子分类 (新 id), 旧位置删除
                    hit_sub["tags"].remove(hit_tag)
                    tag = make_tag(sid, hit_tag.get("en"), hit_tag.get("zh", zh), weight, nsfw)
                    tag["weight"] = hit_tag.get("weight", weight)
                    sub_d["tags"].append(tag)
                    en_idx[lo] = [(lib_default, cat_d, sub_d, tag)]
                    if sub_u is not None:
                        sub_u["tags"].append(json.loads(json.dumps(tag)))
                    added += 1
                else:
                    skipped.append(f"add {en}: 已存在于 {[x[2]['id'] for x in en_idx[lo]]}")
                continue
            tag = make_tag(sid, en, zh, weight, nsfw)
            sub_d["tags"].append(tag)
            en_idx[lo] = [(lib_default, cat_d, sub_d, tag)]
            added += 1
            # 用户库同 id 子分类快照 → 同步补一份 (字段一致, 防遮蔽)
            if sub_u is not None:
                sub_u["tags"].append(json.loads(json.dumps(tag)))

        # ---- 同步用户库快照中被编辑/移动/删除的标签 ----
        if sub_u is not None:
            # 以默认库子分类为准重建用户库快照的标签列表 (保留用户库独有标签)
            d_ens = {_norm(t.get("en")) for t in sub_d["tags"]}
            kept = [t for t in sub_u["tags"] if _norm(t.get("en")) in d_ens]
            d_map = {_norm(t.get("en")): t for t in sub_d["tags"]}
            for t in kept:
                d = d_map.get(_norm(t.get("en")))
                if d:
                    t.update({k: v for k, v in d.items()})
            sub_u["tags"] = kept

    return added, edited, new_subs, skipped


def main():
    batch_name = sys.argv[1] if len(sys.argv) > 1 else "b1"
    commit = "--commit" in sys.argv
    mod = __import__(f"phase6_data_{batch_name}")
    batch = mod.BATCH1 if batch_name == "b1" else getattr(mod, f"BATCH{batch_name[1:].upper()}", None) or mod.BATCH1

    lib_d = load(LIB_PATH)
    lib_u = load(USER_PATH)
    added, edited, new_subs, skipped = apply_batch(lib_d, lib_u, batch)

    print(f"[{batch_name}] added={added} edited={edited} new_subs={new_subs} skipped={len(skipped)}")
    for s in skipped:
        print("  SKIP:", s)

    if not commit:
        print("(dry-run, 未写盘; 加 --commit 写入)")
        return

    # schema 迁移补齐 v2 字段
    for c in lib_d["categories"]:
        schema.migrate_category(c)
    for c in lib_u["categories"]:
        schema.migrate_category(c)
    lib_d.pop("schema_version", None)
    lib_u.pop("schema_version", None)

    for path, lib in ((LIB_PATH, lib_d), (USER_PATH, lib_u)):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lib, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        print("written:", path)

    # 保持 schema_version 字段在库外迁移 (get_merged 时内存补), 不写盘


if __name__ == "__main__":
    main()
