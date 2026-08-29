"""全库错位标签大迁移: 表情情绪里的姿势/服装/场景/光线/发型等归位到正确分类。

未列出的标签留在表情情绪 (纯表情/情绪/嘴部/眼部神态)。
用法: "D:/aiv4/python_embeded/python.exe" tests/reorganize_library.py
"""

import json
import os
import re
import sys

M = {
 ("姿势动作","姿势"): ["falling","floating","lying on bed","lying on stomach","lying on side",
  "standing on one leg","crossed legs standing","leaning forward","leaning back","squatting","crouching",
  "seiza","wariza","yokozuwari","indian style","hugging own legs","stretching","crawling","swimming","flying",
  "spinning","tiptoes","hugging","carrying","high five","hand holding","leaning on person","whispering",
  "piggyback","sparring","playing instrument","bowing","curtsy","selfie pose","head tilt","head rest",
  "chin rest","neck stretch","from behind"],
 ("姿势动作","手部动作"): ["arms behind back","hands on hips","arms up","stretching arm","waving","peace sign",
  "thumbs up","pointing","covering mouth","covering face","hiding behind own arms","hand on own cheek",
  "hand in own hair","adjusting hair","adjusting glasses","holding phone","holding umbrella","holding bag",
  "holding book","holding cup","holding sword","holding staff","holding flower","clapping","finger to mouth",
  "fist raised","praying","writing","facepalm","saluting","shushing"],
 ("姿势动作","视线"): ["looking back","looking afar","over shoulder"],
 ("服装系统","上装"): ["zip hoodie","sweater","cardigan","t-shirt","tank top","crop top","off shoulder",
  "white shirt","dress shirt","leather jacket","denim jacket","trench coat","parka","cape coat","blazer",
  "puffy short sleeves","sleeveless","strapless","maid apron","labcoat"],
 ("服装系统","下装"): ["denim shorts","pleated skirt","miniskirt","long skirt","overalls","suspender skirt",
  "sweatpants"],
 ("服装系统","套装与制服"): ["sundress","summer dress","floral print dress","gown","evening gown","wedding dress",
  "gothic dress","lolita fashion","princess dress","mermaid dress","tracksuit","serafuku","gakuran","maid outfit",
  "nurse","police uniform","military uniform","chef uniform","office lady","business suit","witch costume","miko",
  "nun","cheerleader","racing uniform","idol costume","pilot suit","astronaut suit","knight armor","furisode",
  "yukata","hanfu","cheongsam","sari","elf outfit","mage robe","nun habit","vampire cloak","fairy dress",
  "shrine maiden outfit"],
 ("服装系统","鞋袜"): ["thighhighs","zettai ryouiki","knee highs","lace-trimmed socks","loose socks","stockings",
  "ankle boots","knee boots","thigh boots","mary janes","loafers","sneakers","high heels","platform footwear",
  "barefoot","sandals","geta","slippers"],
 ("服装系统","配饰"): ["witch hat","straw hat","beret","baseball cap","top hat","maid headdress","flower crown",
  "hair ribbon","hair bow","hairband","headband","hairclip","hair ornament","hair flower","cat ear headwear",
  "bunny ears headwear","fox ears headwear","halo","crown","tiara","headphones on head","goggles on head","veil",
  "mask on head","sunglasses","round eyewear","half glasses","choker","pendant","bracelet","wrist cuffs","ring",
  "watch","arm warmers","fingerless gloves","scarf","shawl","cape","cloak","belt","waist apron"],
 ("人物主体","发型发色"): ["very long hair","absurdly long hair","medium hair","bob cut","hime cut","pixie cut",
  "buzz cut","low twintails","side ponytail","high ponytail","one-side up","braid","twin braids","french braid",
  "crown braid","hair bun","double bun","messy bun","ahoge","drill hair","curly hair","wavy hair","ringlets",
  "straight hair","spiky hair","messenhairstyle","flipped bangs","swept bangs","blunt bangs","parted bangs",
  "curtain bangs","sidelocks","hair spread out","floating hair","light blue hair","dark blue hair","white hair",
  "grey hair","light brown hair","brown hair","red hair","purple hair","green hair","orange hair",
  "multicolored hair","two-tone hair","gradient hair","streaked hair","rainbow hair"],
 ("人物主体","眼部"): ["green eyes","golden eyes","purple eyes","brown eyes","amber eyes","silver eyes",
  "black eyes","pink eyes","orange eyes","half-closed eyes","hidden eyes","empty eyes","heart-shaped pupils",
  "star-shaped pupils","spiral eyes","shaded eyes","taremme","tsurime","sanpaku","eyes visible through hair"],
 ("人物主体","体型"): ["mature female","milf","tall female","plump","muscular female","medium breasts",
  "large breasts","wide hips","long legs","slender waist","broad shoulders"],
 ("人物主体","年龄阶段"): ["old woman"],
 ("人物主体","身体特征"): ["pale skin","fair skin","tan skin","dark skin","freckles","mole under eye",
  "beauty mark","doll-like joints","tail","animal tail","fox tail","cat tail","wings","angel wings",
  "demon wings","butterfly wings"],
 ("场景环境","室内"): ["library","gym","kitchen","attic","basement","cafe interior","restaurant","hospital room",
  "laboratory","hotel room","temple interior","church","castle interior","tavern","dojo","shrine interior",
  "elevator","train interior","airplane cabin","spaceship interior"],
 ("场景环境","室外"): ["bamboo forest","flower field","grassland","meadow","mountain scenery","volcano","desert",
  "ocean","underwater","riverbank","lake","waterfall","cave","crystal cave","jungle","tundra","rice field",
  "sunflower field","lavender field","cherry blossom trees","autumn leaves","pine forest","birch forest","swamp",
  "canyon","city street","alley","rooftop","bridge","park bench","playground","amusement park","shopping street",
  "market stall","parking lot","train station","bus stop","subway station","harbor","lighthouse","village",
  "farmland","castle town","medieval street","neon city","post-apocalyptic ruins"],
 ("场景环境","时间天气"): ["night","midnight","noon","daytime","sunset","sunrise","blue hour","starry sky",
  "milky way","full moon","crescent moon","blood moon","aurora","shooting stars","clear sky","overcast","cloudy",
  "rain","heavy rain","drizzle","thunderstorm","lightning bolt","snowing","blizzard","snowflakes falling",
  "morning mist","rainbow","typhoon","sandstorm","heat haze"],
 ("场景环境","幻想科幻"): ["magic circle","floating islands","ancient ruins","another world","fairy forest",
  "dragon lair","haunted mansion","forbidden library","pocket dimension","dreamscape","heaven","underworld",
  "spirit realm","wizard tower","enchanted lake","portal gate"],
 ("场景环境","氛围粒子"): ["falling petals","wind lift","drifting clouds","fireflies","falling leaves",
  "water splash","bubbles","embers","pollen"],
 ("场景环境","背景处理"): ["pitch black background","transparent background","long shadows","shadow play",
  "silhouette","reflection on water","mirror reflection"],
 ("光影氛围","光源类型"): ["rim lighting","backlighting","front lighting","side lighting","sunlight","spotlight",
  "stage lighting","softbox lighting","ring light","lamp light","streetlight","lantern light","firelight",
  "fairy lights","bioluminescence","lightning flash","dim light"],
 ("光影氛围","特殊光线"): ["dispersion","subsurface scattering","dappled sunlight","god rays",
  "crepuscular rays","glowing mushrooms","hazy glow"],
 ("光影氛围","氛围情绪"): ["strong contrast","dreamy atmosphere","eerie atmosphere","serene atmosphere",
  "ominous","cozy atmosphere","melancholic mood","epic scale"],
 ("风格媒介","二次元向"): ["anime coloring","anime screencap style","cell shading","retro anime style",
  "manga panel","webtoon","chibi","semi-realistic","pixiv id reference"],
 ("风格媒介","艺术媒介"): ["painterly","gouache","impasto","sketch","lineart","monochrome","greyscale","sepia",
  "retro artstyle"],
 ("风格媒介","色彩调配"): ["pastel colors","muted colors","vivid colors","contrast colors","dark palette"],
 ("构图镜头","取景范围"): ["extreme close-up","face focus","wide shot","panoramic view","establishing shot",
  "macro shot","two-shot","ground-level shot"],
 ("构图镜头","视角"): ["bird's-eye view","worm's-eye view","pov"],
 ("构图镜头","镜头语言"): ["fisheye"],
 ("构图镜头","构图"): ["rule of thirds composition","centered composition","symmetrical composition",
  "dynamic angle composition","negative space","diagonal composition","framing composition","leading lines",
  "triangular composition","golden ratio","depth of field background","blurry foreground","layered depth",
  "vignetting","frame within frame"],
 ("材质特效","视觉特效"): ["speed lines","motion lines","impact frame","action lines","sparkle effects",
  "sparkles","sweatdrop","anger vein","emotion lines","flower effects","bubble effects","night sky effect",
  "aura burst","afterimage","particle trail","light leaks","chromatic aberration","glowing particles"],
 ("人物补充","持有物"): ["umbrella","paper umbrella","katana","rapier","staff","magic wand","spellbook","book",
  "teacup","coffee cup","ice cream","lollipop","pocky","apple","strawberry","bento","smartphone",
  "game controller","pen","camera","teddy bear","plush toy","balloon","bicycle","motorcycle","skateboard",
  "violin","guitar","microphone","basketball","tennis racket","gun"],
}


def slug(x):
    return re.sub(r"[^a-z0-9\-]+", "-", x.lower()).strip("-")[:40] or "tag"


def process(path):
    d = json.load(open(path, encoding="utf-8"))
    cats = {c["name"]: c for c in d["categories"]}
    expr_cat = cats["人物主体"]
    expr = next(s for s in expr_cat["subcategories"] if s["name"] == "表情情绪")
    expr_index = {t["en"].strip().lower(): t for t in expr["tags"]}
    moved = dropped = 0
    for (cname, sname), ens in M.items():
        cat = cats.get(cname)
        if cat is None:
            continue
        sub = next((x for x in cat["subcategories"] if x["name"] == sname), None)
        if sub is None:
            sub = {"id": f"{cat['id']}.{slug(sname)}", "name": sname, "tags": []}
            cat["subcategories"].append(sub)
        have = {t["en"].strip().lower() for t in sub["tags"]}
        for en in ens:
            k = en.strip().lower()
            tag = expr_index.get(k)
            if tag is None:
                continue
            expr["tags"].remove(tag)
            if k in have:
                dropped += 1
                continue
            tag["id"] = f"{sub['id']}.{slug(k)}"
            sub["tags"].append(tag)
            have.add(k)
            moved += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return moved, dropped, len(expr["tags"])


def main():
    for path in ["data/tag_library.json", "data/tag_library.user.json"]:
        moved, dropped, remain = process(path)
        print(f"{path}: 移动 {moved}, 目标已有去重 {dropped}, 表情情绪剩余 {remain}")


if __name__ == "__main__":
    main()
