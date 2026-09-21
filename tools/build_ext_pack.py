# -*- coding: utf-8 -*-
"""扩展包生成器 —— 从 ext_vocab 策展词表构建三个数据文件 (全部 gitignore, 不入发布包):

  data/default/tag_library.ext.json    第三库源 (deep_merge: default ← ext ← user)
  data/default/taglib/nsfw_grouprules.json   NSFW 互斥域 (与出厂域同名并集)
  data/default/taglib/nsfw_conflicts.json    NSFW 跨池规则 (word↔slot)

收录规则:
  1. danbooru post_count >= min (默认 1500) —— 模型没见过的词不收
  2. 与现有库 (default+user) en 重名 → 跳过
  3. nsfw 词自动带 minor_block: true (未成年锁定全链路出口复核)
幂等: 重跑即按最新词表与计数重建。

用法: python tools/build_ext_pack.py [--min-count N] [--dry-run]
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ext_vocab as V  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "data", "default")
TAGLIB_DIR = os.path.join(DEFAULT_DIR, "taglib")
DANBOORU_DIR = os.path.join(ROOT, "data", "packs", "_danbooru")

EXT_PATH = os.path.join(DEFAULT_DIR, "tag_library.ext.json")
NSFW_GROUPS_PATH = os.path.join(TAGLIB_DIR, "nsfw_grouprules.json")
NSFW_CONFLICTS_PATH = os.path.join(TAGLIB_DIR, "nsfw_conflicts.json")
COUNTS_PATH = os.path.join(ROOT, "data", "packs", "danbooru_counts.json")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "tag"


def _en_of(danbooru_name: str) -> str:
    return danbooru_name.replace("_", " ").strip()


def load_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    p1 = os.path.join(DANBOORU_DIR, "general_top.json")
    p2 = os.path.join(DANBOORU_DIR, "nsfw_related.json")
    if os.path.exists(p1):
        for t in json.load(open(p1, encoding="utf-8")):
            counts[str(t["name"])] = int(t.get("post_count") or 0)
    if os.path.exists(p2):
        for name, info in json.load(open(p2, encoding="utf-8")).items():
            counts[name] = max(counts.get(name, 0), int(info.get("post_count") or 0))
    return counts


def existing_ens() -> set[str]:
    out: set[str] = set()
    for fn in ("tag_library.json", "tag_library.user.json"):
        p = os.path.join(DEFAULT_DIR, fn)
        if not os.path.exists(p):
            continue
        try:
            lib = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in lib.get("categories", []) or []:
            for s in c.get("subcategories", []) or []:
                for t in s.get("tags", []) or []:
                    en = str(t.get("en") or "").strip().lower()
                    if en:
                        out.add(en)
    return out


def rarity_of(count: int) -> tuple[str, int]:
    if count >= 1_000_000:
        return "common", 65
    if count >= 200_000:
        return "common", 60
    if count >= 30_000:
        return "common", 55
    if count >= 5_000:
        return "uncommon", 50
    return "rare", 45


def make_tag(sub_id: str, danbooru: str, zh: str, opts: dict, count: int,
             axis: str, facet: str, explicit: bool = False) -> dict:
    en = _en_of(danbooru)
    rarity, priority = rarity_of(count)
    nsfw = bool(opts.get("nsfw", True))
    t = {
        "en": en, "aliases": [], "weight": 1.0, "enabled": True, "zh": zh,
        "id": f"{sub_id}.{_slug(en)}", "type": "content",
        "priority": priority, "rarity": rarity,
        "groups": [], "requires": [], "mutex_with": [],
        "desc": f"danbooru {count} posts",
        "meta": {}, "gender": str(opts.get("g") or ""),
        "axis": axis, "facet": facet, "nsfw": nsfw,
    }
    if nsfw:
        t["minor_block"] = True
    if nsfw and explicit:
        t["explicit"] = True   # 显式档: NSFW 强度旋钮额外加权
    if opts.get("h"):
        t["hands_cost"] = int(opts["h"])
    return t


# 新槽位: (槽位 id, 槽位名, 轴 id, 轴中文名, 词表, 轴注册次序)
NEW_SUBS = [
    ("ext.s1", "服装状态", "axis.clothing", "clothing", "服装", V.CLOTH_STATE, 399, False),
    ("ext.s2", "身体细节", "axis.appearance", "appearance", "外貌特征", V.BODY_DETAIL, 310, True),
    ("ext.s3", "体位", "axis.action", "action", "动作姿态", V.POSITIONS, 599, True),
    ("ext.s4", "性行为", "axis.action", "action", "动作姿态", V.SEX_ACTS, 610, True),
    ("ext.s5", "束缚与调教", "axis.action", "action", "动作姿态", V.BONDAGE_ACTS, 611, True),
    ("ext.s6", "高潮与体液", "axis.action", "action", "动作姿态", V.CLIMAX, 612, True),
    ("ext.s7", "束缚道具", "axis.prop", "prop", "道具武器", V.BDSM_PROPS, 505, True),
]

# 追加到既有槽位: (槽位 id, 轴 id, 轴中文名, 词表)
ADD_SUBS = [
    ("imported.c2.supp19", "axis.character", "角色身份", V.CHARACTER_ADD),
    ("reorg.s3", "axis.appearance", "外貌特征", V.EXPRESSION_ADD),
    ("imported.c2.sub-2-3-4-5", "axis.appearance", "外貌特征", V.EYES_ADD),
    ("reorg.s5", "axis.appearance", "外貌特征", V.MOOD_ADD),
    ("imported.c2.sub-2-3-4-5-6", "axis.appearance", "外貌特征", V.BODY_SHAPE_ADD),
    ("reorg.s12", "axis.prop", "道具武器", V.TOYS_ADD),
    ("imported.c7.sub", "axis.environment", "场景环境", V.INDOOR_ADD),
]


def main() -> None:
    dry = "--dry-run" in sys.argv
    min_count = V.MIN_COUNT
    if "--min-count" in sys.argv:
        min_count = int(sys.argv[sys.argv.index("--min-count") + 1])

    counts = load_counts()
    have = existing_ens()
    factory = json.load(open(os.path.join(DEFAULT_DIR, "tag_library.json"),
                             encoding="utf-8"))
    cat_by_id = {c["id"]: c for c in factory.get("categories", [])}
    sub_by_id = {}
    for c in factory.get("categories", []):
        for s in c.get("subcategories", []):
            sub_by_id[s["id"]] = (c["id"], c["name"], s["name"])

    report = {"added": 0, "dup": 0, "low": [], "per_slot": {}}

    def collect(table, axis, facet, sub_id, explicit=False):
        out, seen_local = [], set()
        for item in table:
            if len(item) == 2:
                danbooru, zh, opts = item[0], item[1], {}
            else:
                danbooru, zh, opts = item
            if zh is None:
                continue
            en = _en_of(danbooru)
            if en.lower() in seen_local:
                continue
            seen_local.add(en.lower())
            if en.lower() in have:
                report["dup"] += 1
                continue
            count = counts.get(danbooru, counts.get(en, 0))
            if count < max(min_count, int(opts.get("min", 0) or 0)):
                report["low"].append(f"{en} ({count})")
                continue
            out.append(make_tag(sub_id, danbooru, zh, opts, count, axis, facet,
                                explicit=explicit))
            have.add(en.lower())   # 全局占位: 同一次构建内不重复收录
        report["added"] += len(out)
        return out

    # ---------- 新槽位 ----------
    ext_cats: dict[str, dict] = {}
    for sub_id, sub_name, cat_id, axis, cat_zh, table, _order, _expl in NEW_SUBS:
        tags = collect(table, axis, cat_zh, sub_id, explicit=_expl)
        report["per_slot"][f"{cat_zh}/{sub_name}"] = len(tags)
        cat = ext_cats.get(cat_id)
        if cat is None:
            src = cat_by_id[cat_id]
            cat = {"id": cat_id, "name": src["name"], "icon": src.get("icon", "🗂"),
                   "color": src.get("color", "#888888"), "subcategories": []}
            ext_cats[cat_id] = cat
        cat["subcategories"].append({
            "id": sub_id, "name": sub_name, "tags": tags,
        })

    # ---------- 既有槽位追加 ----------
    add_subs_by_cat: dict[str, list[dict]] = {}
    for sub_id, cat_id, cat_zh, table in ADD_SUBS:
        _cid, cname, sname = sub_by_id[sub_id]
        tags = collect(table, {"角色身份": "character", "外貌特征": "appearance",
                               "道具武器": "prop", "场景环境": "environment"}[cat_zh],
                       cat_zh, sub_id)
        key = f"{cname}/{sname}"
        report["per_slot"][key + " (+)"] = len(tags)
        add_subs_by_cat.setdefault(cat_id, []).append({
            "id": sub_id, "name": sname, "tags": tags})

    # TOPUP (既有槽位, 3/4 元组: danbooru 名, 槽位键, 中文[, opts])
    topup_by_sub: dict[str, list[dict]] = {}
    for item in V.TOPUP:
        danbooru, slot_key, zh = item[0], item[1], item[2]
        opts = item[3] if len(item) > 3 else {"nsfw": False}
        opts = dict(opts)
        opts.setdefault("nsfw", False)
        en = _en_of(danbooru)
        if en.lower() in have:
            report["dup"] += 1
            continue
        count = counts.get(danbooru, 0)
        if count < max(min_count, int(opts.get("min", 0) or 0)):
            report["low"].append(f"{en} ({count})")
            continue
        hit = None
        for sid, v in sub_by_id.items():
            if f"{v[1]}/{v[2]}" == slot_key:
                hit = (sid, v)
                break
        if not hit:
            report["low"].append(f"{en} (槽位不存在: {slot_key})")
            continue
        sub_id, (cid, cname, sname) = hit
        axis_zh = {"画质规格": "meta", "人数": "count", "角色身份": "character",
                   "画师": "artist", "外貌特征": "appearance", "服装": "clothing",
                   "道具武器": "prop", "动作姿态": "action", "场景环境": "environment",
                   "光影氛围": "lighting", "构图镜头": "camera", "风格媒介": "style",
                   "材质特效": "material"}[cname]
        t = make_tag(sub_id, danbooru, zh, opts, count, axis_zh, cname)
        topup_by_sub.setdefault(sub_id, []).append(t)
        have.add(en.lower())
        report["added"] += 1
    for sub_id, tags in topup_by_sub.items():
        cid, cname, sname = sub_by_id[sub_id]
        add_subs_by_cat.setdefault(cid, []).append({
            "id": sub_id, "name": sname, "tags": tags})
        report["per_slot"][f"{cname}/{sname} (+)"] =             report["per_slot"].get(f"{cname}/{sname} (+)", 0) + len(tags)

    # 合并追加项: 同一 sub 的追加标签并入同一 sub 块
    ext_list: list[dict] = []
    for cat_id, cat in ext_cats.items():
        adds = add_subs_by_cat.get(cat_id, [])
        cat["subcategories"].extend(adds)
        ext_list.append(cat)
    for cat_id, adds in add_subs_by_cat.items():
        if cat_id not in ext_cats and adds:
            src = cat_by_id[cat_id]
            ext_list.append({"id": cat_id, "name": src["name"],
                             "icon": src.get("icon", "🗂"),
                             "color": src.get("color", "#888888"),
                             "subcategories": adds})

    ext_pack = {
        "version": 1,
        "_说明": ("扩展包 (v1.8.0): NSFW 词表体系 + SFW 高频词补齐。"
                  "由 tools/build_ext_pack.py 生成, 加载顺序 default ← ext ← user。"
                  "本文件不入 git / 不入发布包。"),
        "categories": ext_list,
    }

    # ---------- NSFW 互斥域 ----------
    groups = [{"id": gid, "members": sorted(set(members))}
              for gid, members in V._domain_members().items()]

    # ---------- 落盘 ----------
    print(f"新增 {report['added']} 词 | 跳过重名 {report['dup']} | 低于门槛 {len(report['low'])}")
    for k, n in sorted(report["per_slot"].items()):
        print(f"  {n:4d}  {k}")
    if report["low"]:
        print("低于门槛(前 30):", ", ".join(report["low"][:30]))
    if dry:
        print("(dry-run, 未写盘)")
        return
    os.makedirs(TAGLIB_DIR, exist_ok=True)
    json.dump(ext_pack, open(EXT_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"version": 1, "groups": groups},
              open(NSFW_GROUPS_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"_说明": "NSFW 跨池规则 (ext 扩展包配套), 与 conflicts.json 合并生效。",
               "version": 1, "rules": V.CROSS_RULES},
              open(NSFW_CONFLICTS_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(counts, open(COUNTS_PATH, "w", encoding="utf-8"))
    print(f"写出: {EXT_PATH}\n写出: {NSFW_GROUPS_PATH}\n写出: {NSFW_CONFLICTS_PATH}")


if __name__ == "__main__":
    main()
