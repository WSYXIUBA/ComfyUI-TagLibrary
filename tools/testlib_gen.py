"""多词库矩阵生成器 —— 从分类产物产出多个**符合插件规范**的独立词库。

原料  D:\\code开发共享\\comfyui_tags\\out\\tags_classified.tsv  (47.8 万条, 已 NSFW 分级 + 两级分类)
规范  现行库 JSON: categories[].subcategories[].tags[]; 标签字段
       en/zh/weight/enabled/priority/rarity/aliases/groups/requires/mutex_with/nsfw/minor_block
       (1.12.0 起 .md 标签文件层已删除, 导入导出只走 JSON)

为什么这么做: 功能必须**对任何符合规范的词库都有效**, 只为当前 4458 条库调好是敷衍。
产出的库都只使用**插件已注册的轴/槽位名**(axes.SUB_TO_AXIS_V2), 否则词会全落 misc。
"""
from __future__ import annotations

import collections
import csv
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根 (本文件在 tools/ 下)
SRC = r"D:\code开发共享\comfyui_tags\out\tags_classified.tsv"  # 本机分类原料 (缺失时本脚本无法重跑)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testlibs")

sys.path.insert(0, REPO)
import axes  # noqa: E402

# ---------------------------------------------------------------- 映射: 分类器一级 → 插件轴
L1_AXIS = {
    "质量与画面属性": "meta", "构图与镜头": "camera", "光影": "lighting", "色彩": "style",
    "氛围与情绪": "lighting", "人物基础": "character", "头部与面容": "appearance",
    "身体": "appearance", "姿势": "action", "服装": "clothing", "生物与奇幻": "character",
    "场景与环境": "environment", "物品": "prop", "食物": "prop", "文字与符号": "meta",
    "艺术风格": "style", "画师风格": "artist", "角色与作品": "character",
    "NSFW·裸露": "clothing", "NSFW·性征": "appearance", "NSFW·性行为": "action",
    "NSFW·体液": "action", "NSFW·性玩具与道具": "prop", "重口·束缚调教": "action",
    "重口·极端性癖": "action", "重口·血腥暴力": "action", "重口·异化与恐怖": "appearance",
}
SKIP_L1 = {"其他描述"}

# 轴 → 已注册槽位 [(槽全名, 关键词)]
SLOTS = collections.defaultdict(list)
for _k, (_ax, _o) in axes.SUB_TO_AXIS_V2.items():
    SLOTS[_ax].append((_o, _k))
for _ax in SLOTS:
    SLOTS[_ax].sort()

NSFW_L2 = ("性行为", "体液", "性玩具", "束缚", "极端", "异化", "裸露", "性征", "血腥")


def pick_slot(axis: str, l2: str) -> str:
    """二级名 → 该轴下已注册的槽位名。关键词命中优先, 否则用该轴第一个槽 (仍是规范内)。"""
    cands = SLOTS.get(axis) or []
    if not cands:
        return "misc"
    toks = set(re.findall(r"[\u4e00-\u9fff]{2}", l2))
    best, score = None, 0
    for _, full in cands:
        sub = full.split("/")[-1]
        s = len(toks & set(re.findall(r"[\u4e00-\u9fff]{2}", sub)))
        if sub in l2 or l2 in sub:
            s += 2
        if s > score:
            best, score = full, s
    return best or cands[0][1]


def load_rows():
    rows = []
    with open(SRC, encoding="utf-8") as f:
        for d in csv.DictReader(f, delimiter="\t"):
            ax = L1_AXIS.get(d["level1"])
            if not ax or d["level1"] in SKIP_L1:
                continue
            en = (d["tag_en"] or "").replace("_", " ").strip()
            if not en or len(en) > 60 or en.startswith(("-", "(", ")")):
                continue
            rows.append({"en": en, "zh": d["cn"], "score": int(d["score"] or 0),
                         "l1": d["level1"], "l2": d["level2"], "axis": ax,
                         "slot": pick_slot(ax, d["level2"]),
                         "nsfw": str(d["nsfw"]).strip() not in ("", "0", "L0", "None")})
    return rows


def build_lib(name: str, rows: list) -> dict:
    """按规范组装库 JSON: 三级树 + 标签字段。"""
    tree = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        tree[r["axis"]][r["slot"]].append(r)
    cats = []
    for ax in axes.AXIS_ORDER:                      # 按轴次序, 只出有料的轴
        if ax not in tree:
            continue
        subs = []
        for slot in sorted(tree[ax]):
            tags = []
            for r in sorted(tree[ax][slot], key=lambda x: -x["score"]):
                tags.append({
                    "en": r["en"], "zh": r["zh"] or "", "weight": 1.0, "enabled": True,
                    "id": "%s.%s.%s" % (ax, slot.split("/")[-1], re.sub(r"\W+", "_", r["en"])),
                    "type": "quality" if ax == "meta" else "general",
                    "priority": 50, "rarity": "common", "aliases": [],
                    "groups": [], "requires": [], "mutex_with": [],
                    "nsfw": bool(r["nsfw"]), "minor_block": bool(r["nsfw"]),
                    # 性别声明 (规范字段): 引擎的性别锁就靠它 —— 不写, 换任何库都会失效
                    "gender": ("female" if re.search(r"(?<![a-z])(1girl|[2-9]\+?girls|girls?|female|woman|women|lady|multiple girls)(?![a-z])", r["en"]) else
                               "male" if re.search(r"(?<![a-z])(1boy|[2-9]\+?boys|boys?|male|man|men|multiple boys)(?![a-z])", r["en"]) else ""),
                    "desc": "%s / %s" % (r["l1"], r["l2"]),
                })
            subs.append({"id": "testlib.%s.%s" % (ax, slot.split("/")[-1]), "name": slot.split("/")[-1],
                         "tags": tags, "random_quota": None, "min_count": 0, "max_count": 3,
                         "priority_boost": 1.0})
        cats.append({"id": "axis." + ax, "name": axes.AXIS_NAME_ZH.get(ax, ax),
                     "icon": "", "color": "", "subcategories": subs})
    return {"version": 1, "categories": cats, "_tombstones": [], "settings": {},
            "_说明": {"生成器": "tools/testlib_gen.py", "库名": name,
                      "来源": "comfyui_tags/out/tags_classified.tsv",
                      "规范": "categories[].subcategories[].tags[]; 字段见 library_routes._说明"}}


def main():
    allrows = load_rows()
    os.makedirs(OUT, exist_ok=True)
    print("  语料 %d 条可用 (已按轴映射)" % len(allrows))
    nsfw = [r for r in allrows if r["nsfw"]]
    sfw = [r for r in allrows if not r["nsfw"]]

    specs = {
        "tiny_500": allrows[:500],
        "small_5k": allrows[:5000],
        "big_50k": allrows[:50000],
        "char_only": [r for r in allrows if r["axis"] == "character"][:20000],
        "scene_only": [r for r in allrows if r["axis"] in ("environment", "lighting")]
                      + [r for r in allrows if r["axis"] == "camera"][:800],
        "prop_only": [r for r in allrows if r["axis"] in ("prop", "clothing")],
        "sfw_only": sfw[:50000],
        "nsfw_only": nsfw[:30000],
        "no_count": allrows[:50000],   # 空人数轴: 剔掉 count 轴, 专测"缺轴/词少"退化
        "no_scene": allrows[:50000],   # 空场景轴
        "no_char": allrows[:50000],    # 空角色身份轴
    }
    for name, rows in specs.items():
        if name == "no_count":
            rows = [r for r in rows if r["axis"] != "count"]
        if name == "no_scene":
            rows = [r for r in rows if r["axis"] != "environment"]
        if name == "no_char":
            rows = [r for r in rows if r["axis"] != "character"]
        lib = build_lib(name, rows)
        p = os.path.join(OUT, name + ".json")
        json.dump(lib, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n = sum(len(s["tags"]) for c in lib["categories"] for s in c["subcategories"])
        print("  %-11s %7d 标签  %2d 轴  %5.1fMB  -> %s"
              % (name, n, len(lib["categories"]), os.path.getsize(p) / 1e6, os.path.basename(p)))


if __name__ == "__main__":
    main()
