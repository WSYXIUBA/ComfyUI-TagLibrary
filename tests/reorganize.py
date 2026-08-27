"""终版迁移: 现库(被污染的'表情'大杂烩 + NSFW) -> 13 个语义清晰的分类。

分类规则两层:
  1. 子分类名映射 (互动动作->动作姿势 等, 修复塞错位置的)
  2. 标签级内容识别兜底: 按英文关键词判定真实归属 (场景词/天气词/镜头词...)
NSFW 口径: 只有性暴露/色情词保留 nsfw; 环境(bath/bed/room)一律平反。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library

# ---------------- 子分类级映射 (优先) ----------------
SUB_MAP = {
    ("表情", "基础"):        ("expressions", "表情", "基础"),
    ("表情", "复合"):        ("expressions", "表情", "复合"),
    ("表情", "眼部"):        ("expressions", "表情", "眼部"),
    ("表情", "嘴部"):        ("expressions", "表情", "嘴部"),
    ("表情", "基础表情"):    ("expressions", "表情", "基础"),
    ("表情", "复杂表情"):    ("expressions", "表情", "复合"),
    ("表情", "脸部特征"):    ("expressions", "表情", "嘴部"),
    ("表情", "眼部表现"):    ("expressions", "表情", "眼部"),
    ("表情", "嘴部细节"):    ("expressions", "表情", "嘴部"),
    ("表情", "互动动作"):    ("pose", "动作姿势", "互动"),
    ("表情", "身体语言"):    ("pose", "动作姿势", "身体动态"),
    ("表情", "自然现象"):    ("weather", "天气·时间", "自然现象"),
    ("表情", "角度"):        ("camera2", "镜头构图", "角度"),
    ("表情", "构图法则"):    ("camera2", "镜头构图", "构图法则"),

    ("NSFW", "身体部位"):    ("nsfwcat", "NSFW", "身体暴露"),
    ("NSFW", "泳装贴身"):    ("nsfwcat", "NSFW", "性感着装"),
    ("NSFW", "姿势"):        ("nsfwcat", "NSFW", "色情姿态"),
    ("NSFW", "身体反应"):    ("nsfwcat", "NSFW", "淫荡表情反应"),
    ("NSFW", "互动动作"):    None,   # 需逐条判: 人物属性平反, 其余留 NSFW
    ("NSFW", "身体语言"):    None,
    ("NSFW", "自然现象"):    None,
    ("NSFW·身体", "场景道具"): None,  # 环境类大多平反
}

# ---------------- NSFW 平反名单 (环境/日常/人物属性) ----------------
FORGIVE_EN = {
    # 场景道具类
    "bed sheet", "on bed", "bathtub", "shower", "towel", "soap lather",
    "office chair", "camera", "mirror", "bedroom",
    # 泳装日常
    "swimsuit", "school swimsuit",
    # 服装饰品
    "pantyhose", "garter straps", "corset",
    # 人物属性 (身体现状不算色情)
    "loli", "mature female", "milf", "curvy",
}
# 含子串匹配的平反
FORGIVE_SUBSTR = ["swimsuit", "bikini"]

# ---------------- 标签级内容识别 (兜底分流) ----------------
RULES = [
    # (关键词列表 en小写子串, 目标(分类id, 分类名, 子分类))
    (["from above", "from below", "dutch angle", "pov", "eye-level", "bird's-eye",
      "worm's eye", "fisheye"], ("camera2", "镜头构图", "角度")),
    (["rule of thirds", "centered composition", "symmetrical composition",
      "dynamic angle composition", "negative space", "diagonal composition",
      "framing composition", "leading lines", "triangular composition",
      "golden ratio", "frame within frame"], ("camera2", "镜头构图", "构图法则")),
    (["close-up", "upper body", "cowboy shot", "full body", "wide shot",
      "panoramic view", "establishing shot", "macro shot", "two-shot",
      "portrait", "extreme close"], ("camera2", "镜头构图", "景别")),
    (["falling petals", "wind lift", "drifting clouds", "fireflies",
      "falling leaves", "water splash", "bubbles", "smoke", "embers",
      "pollen", "lightning bolt", "rainbow", "aurora"], ("weather", "天气·时间", "自然现象")),
    (["night", "midnight", "noon", "daytime", "sunset", "sunrise", "golden hour",
      "blue hour", "starry sky", "milky way", "full moon", "crescent moon",
      "blood moon", "rain ", "heavy rain", "drizzle", "thunderstorm", "snowing",
      "blizzard", "snowflakes", "fog", "morning mist", "overcast", "cloudy",
      "clear sky"], ("weather", "天气·时间", "天气天象")),
    (["hugging", "carrying", "high five", "hand holding", "leaning on person",
      "whispering", "piggyback", "dancing", "sparring", "playing instrument"],
     ("pose", "动作姿势", "互动")),
    (["stretching", "yawning", "shivering", "sneezing", "saluting", "bowing",
      "curtsy", "crawling", "swimming", "flying", "spinning", "tiptoes",
      "arch ", "arching"], ("pose", "动作姿势", "身体动态")),
]


def content_route(en_l: str):
    """标签级兜底: 返回 (cat_id, cat_name, sub_name) 或 None。"""
    for keys, tgt in RULES:
        if any(k in en_l for k in keys):
            return tgt
    return None


CAT_META = {
    "expressions": {"name": "表情", "icon": "😊", "color": "#ff9ff3"},
    "pose":        {"name": "动作姿势", "icon": "🏃", "color": "#54a0ff"},
    "clothing":    {"name": "服装", "icon": "👗", "color": "#a29bfe"},
    "accessory":   {"name": "配饰·道具", "icon": "🎩", "color": "#ffb84d"},
    "hair":        {"name": "头发", "icon": "💇", "color": "#f8a5c2"},
    "traits":      {"name": "人物特征", "icon": "🧬", "color": "#63cdda"},
    "scene":       {"name": "场景", "icon": "🏙️", "color": "#2ecc71"},
    "weather":     {"name": "天气·时间", "icon": "🌙", "color": "#778beb"},
    "lighting":    {"name": "光影", "icon": "💡", "color": "#f39c12"},
    "styleq":      {"name": "画风质量", "icon": "🎨", "color": "#9b59b6"},
    "fx":          {"name": "画面特效", "icon": "✨", "color": "#ffd166"},
    "cameracomp":  {"name": "镜头构图", "icon": "📷", "color": "#e74c3c"},
    # 旧别名兼容
    "camera2":     {"name": "镜头构图", "icon": "📷", "color": "#e74c3c"},
    "lighting2":   {"name": "光影", "icon": "💡", "color": "#f39c12"},
    "nsfwcat":     {"name": "NSFW", "icon": "🔞", "color": "#ff4757"},
}


def main() -> None:
    lib = library.get_merged()
    cats: dict[str, dict] = {}

    def ensure(cat_id: str) -> dict:
        if cat_id not in cats:
            meta = CAT_META[cat_id]
            cats[cat_id] = {
                "id": cat_id, "name": meta["name"],
                "icon": meta["icon"], "color": meta["color"],
                "subcategories": [],
            }
        return cats[cat_id]

    def add(cat_id: str, sub_name: str, tag: dict, used: set) -> None:
        c = ensure(cat_id)
        slug = re.sub(r"[^a-z0-9-]+", "-", sub_name.lower()).strip("-")[:30] or f"s{len(c['subcategories'])}"
        sid = f"{cat_id}.{slug}"
        n = 2
        while sid in {s.get("id") for s in c["subcategories"]}:
            sid = f"{cat_id}.{slug}-{n}"
            n += 1
        sl = next((s for s in c["subcategories"] if s["name"] == sub_name), None)
        if sl is None:
            sl = {"id": sid, "name": sub_name, "tags": []}
            c["subcategories"].append(sl)
        base = re.sub(r"[^a-z0-9-]+", "-", tag.get("en", "").lower())[:40] or "tag"
        tid = f"{sl['id']}.{base}"
        m = 2
        while tid in used:
            tid = f"{sl['id']}.{base}-{m}"
            m += 1
        used.add(tid)
        t["id"] = tid
        sl["tags"].append(t)

    moved = forgiven = dup = 0
    seen: set[str] = set()
    used_ids: set[str] = set()

    for cat in lib["categories"]:
        cname = cat.get("name", "")
        for sub in cat.get("subcategories", []):
            sname = sub.get("name", "")
            mapped = SUB_MAP.get((cname, sname), "__keep__")

            for t in sub.get("tags", []):
                raw_en = t.get("en", "").strip()
                en_l = raw_en.lower()
                if en_l in seen:
                    dup += 1
                    continue
                seen.add(en_l)
                t = json.loads(json.dumps(t))

                dest = mapped if isinstance(mapped, tuple) else None

                # NSFW 组或未知位置 -> 逐条判断
                if mapped is None or mapped == "__keep__" and cname in ("NSFW", "NSFW·身体"):
                    if en_l in FORGIVE_EN or any(s in en_l for s in FORGIVE_SUBSTR):
                        # 平反: 按内容再分流
                        dest = content_route(en_l) or (
                            ("clothing", "服装", "泳装贴身") if any(s in en_l for s in FORGIVE_SUBSTR)
                            else ("scene", "场景", "生活场景"))
                        t.pop("nsfw", None)
                        forgiven += 1
                    else:
                        keep_nsfw = is_nsfw_strict(en_l)
                        if not keep_nsfw:
                            dest = content_route(en_l) or ("traits", "人物特征", "年龄体型")
                            t.pop("nsfw", None)
                            forgiven += 1
                        else:
                            t["nsfw"] = True
                            sub_map_ns = SUB_MAP.get((cname, sname))
                            if isinstance(sub_map_ns, tuple):
                                dest = sub_map_ns
                            else:
                                # 按原子分类名归入 NSFW 对应子层
                                dest = ("nsfwcat", "NSFW", _nsfw_sub(sname))
                        if was_flag(t) and not keep_nsfw and False:
                            pass
                elif mapped == "__keep__":
                    dest = None  # 保持原分类原子分类

                if dest is None:
                    # 保持原位
                    tcid = next((k for k, v in CAT_META.items() if v["name"] == cname), None)
                    if tcid is None:
                        # 原分类名不在元表 (如 '表情·扩展') -> 内容识别兜底
                        d2 = content_route(en_l)
                        if d2 is None:
                            continue
                        add(d2[0], d2[2], t, used_ids)
                        moved += 1
                        continue
                    ensure(tcid)
                    d2 = None
                    add(tcid, sname, t, used_ids)
                    moved += 1
                    continue

                add(dest[0], dest[2], t, used_ids)
                moved += 1

    out = {"version": 1, "categories": [c for c in cats.values() if c["subcategories"]]}
    r = library.save_user_library(out, merge_base=lib)
    print(f"moved={moved} dup={dup} forgiven={forgiven} saved={r['ok']}")
    merged = library.get_merged()
    total = 0
    for c in merged["categories"]:
        n = sum(len(s['tags']) for s in c['subcategories'])
        ns = sum(1 for s in c['subcategories'] for x in s['tags'] if x.get('nsfw'))
        total += n
        subs = ' / '.join(f"{s['name']}{len(s['tags'])}" for s in c['subcategories'])
        print(f"{c['icon']} {c['name']}({n}): {subs[:90]}")
    print("TOTAL:", total)


def was_flag(_t):  # 兼容占位
    return False


def _nsfw_sub(old_sub_name: str) -> str:
    return {
        "身体部位": "身体暴露", "泳装贴身": "性感着装",
        "姿势": "色情姿态", "身体反应": "淫荡表情反应",
    }.get(old_sub_name, "其他")


def is_nsfw_strict(en_l: str) -> bool:
    hints = ["nude", "naked", "topless", "bottomless", "nipple", "areola", "breast",
             "pussy", "penis", "cum", "sex", "mating", "orgasm", "ahegao", "erect",
             "masturb", "bondage", "bdsm", "rape", "crotch", "no bra", "exposed",
             "lewd", "horny", "lust", "seductive", "all fours", "spread legs",
             "legs up", "bent over", "on lap", "underboob", "sideboob", "cleavage"]
    return any(h in en_l for h in hints)


if __name__ == "__main__":
    main()
