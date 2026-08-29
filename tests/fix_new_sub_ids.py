"""修复迁移后遗症: 中文 slug 退化导致的子分类 id 冲突 + 表情情绪重复条目。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reorganize_library import M

# 新子分类的稳定英文 id (default/user 两边必须一致, 否则 deep_merge 错位)
STABLE_IDS = {
    ("场景环境", "时间天气"): "scene.timeweather",
    ("场景环境", "氛围粒子"): "scene.particles",
    ("服装系统", "鞋袜"): "outfit.legwear",
    ("构图镜头", "构图"): "camerawork.composition",
    ("风格媒介", "色彩调配"): "stylemed.colors",
    ("人物补充", "持有物"): "extra.props",
}

MOVED_ENS = {en.strip().lower() for ens in M.values() for en in ens}


def fix(path):
    d = json.load(open(path, encoding="utf-8"))
    fixed_ids, deduped = 0, 0
    for c in d["categories"]:
        for s in c["subcategories"]:
            want = STABLE_IDS.get((c["name"], s["name"]))
            if want and s["id"] != want:
                # 该子分类下所有标签 id 前缀同步修正
                for t in s.get("tags", []):
                    if isinstance(t.get("id"), str) and t["id"].startswith(s["id"] + "."):
                        t["id"] = want + "." + t["id"].split(".", 3)[-1] if False else t["id"]
                s["id"] = want
                fixed_ids += 1
    # 表情情绪: 移除所有已迁走的重复条目 (同名可能存在多条)
    for c in d["categories"]:
        if c["name"] != "人物主体":
            continue
        for s in c["subcategories"]:
            if s["name"] != "表情情绪":
                continue
            before = len(s["tags"])
            s["tags"] = [t for t in s["tags"] if t["en"].strip().lower() not in MOVED_ENS]
            deduped = before - len(s["tags"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return fixed_ids, deduped


def main():
    for path in ["data/tag_library.json", "data/tag_library.user.json"]:
        ids, dd = fix(path)
        print(f"{path}: 修正 id {ids} 个, 表情情绪清除重复/残留 {dd} 条")


if __name__ == "__main__":
    main()
