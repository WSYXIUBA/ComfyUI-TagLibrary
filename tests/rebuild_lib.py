"""按用户骨架重建默认库: 9 大类 / 真三级 (大类>子类>孙类)。

* 骨架完全来自用户提供的 JSON (质量与技术/人物主体/服装系统/姿势动作/
  构图镜头/光影氛围/场景环境/风格媒介/材质特效/负面标签库)
* 骨架标签全部入新库, 并从旧库继承 zh 翻译/aliases/weight/nsfw
* 旧库标签映射不进骨架的 (如大量 Danbooru 风格标签) 全部归入
  对应大类的「扩展」子分类, 一条不丢
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library

# ---------------------------------------------------------------- 骨架

SKELETON = {
    "质量与技术": {
        "画质强化": ["masterpiece", "best quality", "ultra detailed", "highres", "8k", "extremely detailed"],
        "真实感": ["photorealistic", "realistic", "hyperrealistic", "raw photo"],
        "锐度与清晰": ["sharp focus", "crisp details", "intricate details"],
        "负面质量": ["lowres", "worst quality", "low quality", "blurry", "jpeg artifacts", "noise"],
    },
    "人物主体": {
        "基础描述": {
            "人数": ["1girl", "1boy", "2girls", "solo", "multiple girls"],
            "年龄阶段": ["child", "teen", "young adult", "mature", "elderly"],
        },
        "外貌": {
            "发型发色": ["long hair", "short hair", "ponytail", "twin tails", "black hair", "blonde hair", "silver hair", "pink hair"],
            "五官": ["blue eyes", "red eyes", "heterochromia", "beautiful detailed eyes", "glowing eyes"],
            "体型": ["slim", "petite", "curvy", "athletic", "muscular"],
        },
        "表情情绪": ["smile", "gentle smile", "serious", "angry", "sad", "blush", "surprised", "confident"],
    },
    "服装系统": {
        "上装": ["shirt", "blouse", "hoodie", "jacket", "coat", "armor", "kimono"],
        "下装": ["skirt", "pants", "shorts", "jeans"],
        "套装与制服": ["dress", "school uniform", "maid outfit", "suit", "swimsuit", "qipao"],
        "配饰": ["hat", "glasses", "earrings", "necklace", "gloves", "ribbon", "bag"],
    },
    "姿势动作": {
        "静态姿势": ["standing", "sitting", "lying", "kneeling", "leaning"],
        "动态动作": ["walking", "running", "jumping", "dancing", "reaching out"],
        "手部动作": ["hand on hip", "arms crossed", "hands in pockets", "holding object"],
        "视线": ["looking at viewer", "looking away", "looking up", "looking down"],
    },
    "构图镜头": {
        "取景范围": ["close-up", "portrait", "upper body", "cowboy shot", "full body"],
        "视角": ["from above", "from below", "from side", "front view", "back view"],
        "镜头语言": ["depth of field", "bokeh", "wide angle", "telephoto", "dutch angle"],
    },
    "光影氛围": {
        "光源类型": ["natural lighting", "studio lighting", "cinematic lighting", "rim light", "backlight"],
        "特殊光线": ["neon lights", "moonlight", "candlelight", "golden hour", "volumetric lighting"],
        "氛围情绪": ["moody", "dramatic", "soft lighting", "high contrast", "dark atmosphere"],
    },
    "场景环境": {
        "室内": ["bedroom", "living room", "classroom", "office", "cafe"],
        "室外": ["street", "park", "beach", "forest", "cityscape", "mountain"],
        "幻想科幻": ["cyberpunk city", "fantasy landscape", "ruins", "space station", "castle"],
        "背景处理": ["simple background", "white background", "detailed background", "blurry background"],
    },
    "风格媒介": {
        "写实向": ["photorealistic", "realistic", "cinematic"],
        "二次元向": ["anime style", "manga style", "cel shading", "illustration"],
        "艺术媒介": ["oil painting", "watercolor", "ink drawing", "digital art"],
        "题材风格": ["cyberpunk", "steampunk", "fantasy", "sci-fi", "horror"],
    },
    "材质特效": {
        "材质": ["metallic", "glass", "fabric", "leather", "wet skin", "skin texture"],
        "视觉特效": ["glowing", "particles", "lens flare", "light rays", "smoke", "fog"],
        "服装细节": ["lace", "frills", "embroidery", "transparent", "ripped"],
    },
    "负面标签库": {
        "解剖问题": ["bad anatomy", "deformed", "extra limbs", "mutated hands", "poorly drawn hands", "extra fingers"],
        "面部问题": ["ugly face", "deformed face", "bad eyes", "cross-eyed"],
        "其他常见": ["watermark", "text", "signature", "cropped", "out of frame"],
    },
}

CAT_META = {
    "质量与技术": {"id": "quality",   "icon": "🏆", "color": "#f39c12"},
    "人物主体":   {"id": "subject",   "icon": "🧑", "color": "#54a0ff"},
    "服装系统":   {"id": "outfit",    "icon": "👗", "color": "#a29bfe"},
    "姿势动作":   {"id": "pose",      "icon": "🏃", "color": "#2ecc71"},
    "构图镜头":   {"id": "camerawork","icon": "📷", "color": "#e74c3c"},
    "光影氛围":   {"id": "lighting",  "icon": "💡", "color": "#f1c40f"},
    "场景环境":   {"id": "scene",     "icon": "🏙️", "color": "#1abc9c"},
    "风格媒介":   {"id": "stylemed",  "icon": "🎨", "color": "#9b59b6"},
    "材质特效":   {"id": "material",  "icon": "✨", "color": "#ffd166"},
    "负面标签库": {"id": "negative",  "icon": "🚫", "color": "#7f8c8d"},
}

# 旧标签 -> 新大类 的映射 (用于把旧库 760 条塞进骨架大类)
LEGACY_MAP = {
    "质量与技术": ["表情"],                      # 表情大类整体映射见下, 此处做兜底
}

# 更精确: 按旧分类名 -> 新大类
OLD_CAT_TO_NEW = {
    "表情":       ("subject",  "表情情绪"),
    "动作姿势":   ("pose",     None),
    "服装":       ("outfit",   None),
    "场景":       ("scene",    None),
    "天气·时间":  ("scene",    None),
    "镜头构图":   ("camerawork", None),
    "光影":       ("lighting", None),
    "人物特征":   ("subject",  "外貌"),
    "头发":       ("subject",  "外貌"),
    "配饰·道具":  ("outfit",   "配饰"),
    "画风质量":   ("stylemed", None),
    "画面特效":   ("material", "视觉特效"),
    "NSFW":       (None,       None),  # NSFW 单独处理
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")[:40] or "misc"


def main() -> None:
    old = library.get_merged()

    # 旧库索引: en -> tag (取最全信息)
    old_by_en: dict[str, dict] = {}
    for cat in old["categories"]:
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []):
                en_l = t.get("en", "").strip().lower()
                if en_l and en_l not in old_by_en:
                    old_by_en[en_l] = t
                elif en_l in old_by_en:
                    # 合并别名
                    for a in t.get("aliases", []):
                        if a not in old_by_en[en_l].get("aliases", []):
                            old_by_en[en_l].setdefault("aliases", []).append(a)

    new_lib = {"version": 1, "categories": []}
    used_en: set[str] = set()

    def enrich(en: str, zh_hint: str = "") -> dict:
        """从旧库继承 zh/aliases/weight, 否则用 hint。"""
        t_old = old_by_en.get(en.lower())
        tag = {"en": en, "weight": 1.0, "aliases": []}
        if t_old:
            tag["zh"] = t_old.get("zh", "")
            tag["weight"] = t_old.get("weight", 1.0)
            tag["aliases"] = list(t_old.get("aliases", []))
            if t_old.get("nsfw"):
                tag["nsfw"] = True
        if not tag.get("zh"):
            tag["zh"] = zh_hint
        used_en.add(en.lower())
        return tag

    for cat_name, subdefs in SKELETON.items():
        meta = CAT_META[cat_name]
        cat = {"id": meta["id"], "name": cat_name, "icon": meta["icon"],
               "color": meta["color"], "subcategories": []}
        for sub_name, val in subdefs.items():
            # 子分类名是中文 -> id 用 pinyin 不可行, 用序号 id + name 保存中文
            n_idx = len(cat["subcategories"]) + 1
            sid = f"{meta['id']}.s{n_idx}"
            sub = {"id": sid, "name": sub_name, "tags": []}
            if isinstance(val, dict):
                # 三级: groups
                sub["groups"] = []
                for g_name, ens in val.items():
                    g_idx = len(sub["groups"]) + 1
                    g = {"id": f"{sid}.g{g_idx}", "name": g_name, "tags": []}
                    for en in ens:
                        g["tags"].append(enrich(en, zh_hint=""))
                    sub["groups"].append(g)
                sub["tags"] = [t for g in sub["groups"] for t in g["tags"]]
            else:
                for en in val:
                    sub["tags"].append(enrich(en, zh_hint=""))
            cat["subcategories"].append(sub)
        new_lib["categories"].append(cat)

    # ---- 旧库剩余标签 (骨架没覆盖的) -> 归入对应新大类的「扩展」子分类
    cat_by_name = {c["name"]: c for c in new_lib["categories"]}
    placed = 0
    for old_cat in old["categories"]:
        old_cname = old_cat.get("name", "")
        # NSFW 类: nsfw 标记的标签已带 nsfw 字段, 归入新大类后会保留过滤链路
        target = OLD_CAT_TO_NEW.get(old_cname)
        if target is None:
            # NSFW 或未知分类: 按标签自身的常用程度挑大类, 兜底放 subject.扩展
            for sub in old_cat.get("subcategories", []):
                for t in sub.get("tags", []):
                    en = t.get("en", "").strip()
                    if not en or en.lower() in used_en:
                        continue
                    cat = cat_by_name["人物主体"]
                    ext = next((s for s in cat["subcategories"] if s["name"] == "扩展"), None)
                    if ext is None:
                        ext = {"id": "subject.extended", "name": "扩展", "tags": []}
                        cat["subcategories"].append(ext)
                    nt = dict(t)
                    nt["id"] = f"subject.extended.{slug(en)}"
                    ext["tags"].append(nt)
                    used_en.add(en.lower())
                    placed += 1
            continue
        new_cat_id, fixed_sub = target
        cat = next((c for c in new_lib["categories"] if c["id"] == new_cat_id), None)
        if cat is None:
            continue
        for sub in old_cat.get("subcategories", []):
            sub_name = sub.get("name", "")
            # 子分类名尽量保留: 骨架已有同名子分类则并入, 否则新建 (id 冲突时加序号)
            dest_sub = next((s for s in cat["subcategories"] if s["name"] == fixed_sub), None) if fixed_sub else \
                       next((s for s in cat["subcategories"] if s["name"] == sub_name), None)
            if dest_sub is None:
                base_sid = f"{cat['id']}.{slug(sub_name)}"
                sid = base_sid
                n = 2
                taken = {s["id"] for s in cat["subcategories"]}
                while sid in taken:
                    sid = f"{base_sid}-{n}"
                    n += 1
                dest_sub = {"id": sid, "name": sub_name, "tags": []}
                cat["subcategories"].append(dest_sub)
            for t in sub.get("tags", []):
                en = t.get("en", "").strip()
                if not en or en.lower() in used_en:
                    continue
                nt = dict(t)
                nt["id"] = f"{dest_sub['id']}.{slug(en)}"
                # 清掉旧 id 痕迹
                dest_sub["tags"].append(nt)
                used_en.add(en.lower())
                placed += 1

    # NSFW 大类保留为独立分类 (nsfw_mode 链路依赖 nsfw 标记字段, 分类位置不影响)
    nsfw_old = next((c for c in old["categories"] if c.get("name") == "NSFW"), None)
    if nsfw_old:
        nsfw_cat = {"id": "nsfwcat", "name": "NSFW", "icon": "🔞", "color": "#ff4757",
                    "subcategories": []}
        for sub in nsfw_old.get("subcategories", []):
            ntags = [dict(t) for t in sub.get("tags", []) if t.get("en", "").strip()]
            for t in ntags:
                t["id"] = f"nsfwcat.{slug(t['en'])}"
                t.setdefault("nsfw", True)
            if ntags:
                nsfw_cat["subcategories"].append({
                    "id": f"nsfwcat.{slug(sub.get('name','misc'))}",
                    "name": sub.get("name", "杂项"), "tags": ntags})
        if nsfw_cat["subcategories"]:
            new_lib["categories"].append(nsfw_cat)

    # 质量校验 + 写入
    out = library.validate(new_lib)
    total = sum(len(s["tags"]) for c in out["categories"] for s in c["subcategories"])
    r = library.save_user_library(out, merge_base=library.get_merged())
    print(f"骨架标签 + 旧库迁移 placed={placed}, TOTAL={total}, saved={r['ok']}")
    for c in out["categories"]:
        n = sum(len(s["tags"]) for s in c["subcategories"])
        nsub = len(c["subcategories"])
        ngrp = sum(len(s.get("groups", [])) for s in c["subcategories"])
        print(f"  {c['icon']} {c['name']}: {n} 标签 / {nsub} 子分类 / {ngrp} 孙分类")


if __name__ == "__main__":
    main()
