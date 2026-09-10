"""词表补齐: 加入缺失的"基准词"与质量/细节词 (2026-09-10, v1.5.x)。

## 为什么
实测（群内一条真实提示词，62 词）库覆盖率只有 **55%**，且缺的不是生僻词，
而是**最基础的基准词** —— 全库 82 个常见基准名词里缺 **40 个**：

    breasts / thighs / hair / eyes / legs / arms / hands / feet / ears / stomach
    bow / socks / shoes / boots / apron / hood / jewelry
    water / fire / moon / sun / star / sky / cloud / tree / flower / snow / blood
    cup / bottle / chair / window / door / tongue / teeth / lips / nose …

库里有 `small breasts` / `huge breasts` 却**没有 `breasts`**，导致两个问题：
  1. 表达不了"普通"状态（只有修饰版本）；
  2. 大/小、粗/细可能同时被抽中（`large breasts` + `small breasts`）。

同时缺 Anima 与群内提示词在用的质量/细节词：`score_*` 整层、`newest`、
`ultra-detailed`、`huge filesize`、`detailed pupils`、`sharp focus`、`amazing quality` 等。

## 本脚本
按"槽位 → 词表"的显式清单补齐（**只用 Danbooru 真实标签，不生成组合**），
幂等：已存在的词跳过。落盘前自动备份，写完重建 .md 镜像。

同时支持**归位**（`MOVES`）：把放错槽位导致语义失效的词搬到正确槽位。

用法:
    python tools/add_base_vocab.py            # 报告
    python tools/add_base_vocab.py --apply    # 落盘
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library  # noqa: E402
import schema  # noqa: E402

# 槽位键 -> [(en, zh), ...]。槽位键为 "大类/子类"，与 slotpolicy 保持一致。
ADDITIONS: dict[str, list[tuple[str, str]]] = {
    # ---- 基准身体部位 (库内已有 long legs / small hands 等修饰版, 缺基准版) ----
    "人物主体/体型": [
        ("breasts", "胸部"), ("thighs", "大腿"), ("stomach", "腹部"),
        ("legs", "双腿"), ("arms", "手臂"), ("hands", "手"),
        ("feet", "脚"), ("torso", "躯干"), ("hips", "臀部"),
        ("bare legs", "露出双腿"), ("bare arms", "露出双臂"),
        ("bare feet", "赤脚"), ("bare back", "露出后背"), ("bare midriff", "露出腰腹"),
    ],
    "人物主体/发型": [
        ("hair", "头发"), ("short hair", "短发"), ("medium hair", "中长发"),
        ("absurdly long hair", "超长发"), ("wavy hair", "卷发"), ("curly hair", "卷曲发"),
    ],
    "人物主体/眼部": [
        ("eyes", "眼睛"), ("eyelashes", "睫毛"), ("eyebrows", "眉毛"),
        ("thick eyebrows", "浓眉"), ("heterochromia", "异色瞳"), ("eye shadow", "眼影"),
    ],
    "人物主体/嘴部动作": [
        ("lips", "嘴唇"), ("teeth", "牙齿"), ("tongue", "舌头"), ("nose", "鼻子"),
    ],
    "人物主体/表情": [
        ("sweat", "汗"), ("sweatdrop", "汗滴"), ("tears", "眼泪"),
        ("angry", "生气"), ("surprised", "惊讶"), ("serious", "认真"),
    ],
    "人物主体/皮肤与印记": [
        ("skin", "皮肤"), ("pale skin", "白皙皮肤"), ("tan", "晒黑"),
        ("mole", "痣"), ("scar", "伤疤"), ("bandage", "绷带"),
    ],
    "人物主体/非人特征": [
        ("ears", "耳朵"), ("animal ears", "兽耳"), ("pointy ears", "尖耳"),
        ("wings", "翅膀"), ("tail", "尾巴"), ("horns", "角"),
    ],
    # ---- 服装基准词 ----
    "服装系统/腿袜与内衣": [
        ("socks", "袜子"), ("ankle socks", "短袜"), ("thighhighs", "过膝袜"),
        ("pantyhose", "连裤袜"), ("underwear", "内衣"), ("bra", "胸罩"),
    ],
    "服装系统/鞋子": [
        ("shoes", "鞋"), ("boots", "靴子"), ("high heels", "高跟鞋"),
        ("sneakers", "运动鞋"), ("sandals", "凉鞋"), ("barefoot", "赤足"),
    ],
    "服装系统/上装": [
        ("apron", "围裙"), ("sweater", "毛衣"), ("blouse", "女衬衫"),
        ("t-shirt", "T恤"), ("hoodie", "连帽衫"),
    ],
    "服装系统/服装细节": [
        ("bow", "蝴蝶结"), ("hood", "兜帽"), ("frills", "褶边"),
        ("lace", "蕾丝"), ("ribbon", "缎带"), ("zipper", "拉链"),
    ],
    "服装系统/首饰珠宝": [
        ("jewelry", "珠宝"), ("bracelet", "手镯"), ("ring", "戒指"),
        ("pendant", "吊坠"), ("hair ornament", "发饰"),
    ],
    # ---- 场景 / 自然基准词 ----
    "场景环境/自然景观": [
        ("sky", "天空"), ("cloud", "云"), ("tree", "树"), ("flower", "花"),
        ("grass", "草"), ("water", "水"), ("mountain", "山"), ("beach", "沙滩"),
    ],
    "场景环境/月与星空": [
        ("moon", "月亮"), ("sun", "太阳"), ("star", "星星"), ("starry sky", "星空"),
    ],
    "场景环境/天气现象": [
        ("snow", "雪"), ("rain", "雨"), ("fog", "雾"), ("cloudy sky", "多云"),
        ("blue sky", "蓝天"),
    ],
    # ---- 物件基准词 ----
    "人物主体/日用道具": [
        ("cup", "杯子"), ("bottle", "瓶子"), ("chair", "椅子"),
        ("window", "窗户"), ("door", "门"), ("phone", "手机"),
        ("smartphone", "智能手机"), ("book", "书"), ("umbrella", "伞"),
    ],
    "人物主体/食物饮品": [
        ("coffee", "咖啡"), ("tea", "茶"), ("cake", "蛋糕"),
        ("bread", "面包"), ("ice cream", "冰淇淋"),
    ],
    "材质特效/材质": [
        ("blood", "血"), ("fire", "火"), ("metal", "金属"),
        ("glass", "玻璃"), ("wood", "木"), ("fabric", "布料"),
    ],
    # ---- 质量 / 细节 (对齐 Anima 两套体系 + 群内提示词) ----
    "画质规格/画质增强": [
        ("score_9", "评分9"), ("score_8", "评分8"), ("score_7", "评分7"),
        ("score_6", "评分6"), ("score_5", "评分5"), ("score_4", "评分4"),
        ("good quality", "良好质量"), ("normal quality", "普通质量"),
        ("amazing quality", "惊艳质量"), ("very aesthetic", "极佳美学"),
        ("ultra-detailed", "超高细节"), ("huge filesize", "超大文件"),
        ("highres", "高分辨率"), ("absurdres", "极高分辨率"),
        ("newest", "最新作"),
    ],
    "画质规格/细节强化": [
        ("detailed eyes", "精细眼睛"), ("detailed pupils", "精细瞳孔"),
        ("sharp focus", "锐利对焦"), ("detailed skin", "精细皮肤"),
        ("detailed background", "精细背景"), ("intricate details", "繁复细节"),
    ],
    # ---- 第二轮: 全部取自群内那条真实提示词 (即在用的词, 非生成), 以及其同类高频组合 ----
    "画质规格/画质增强": [
        ("very awa", "极佳(社区美学词)"),
    ],
    "服装系统/首饰珠宝": [
        ("black choker", "黑色颈饰"), ("white choker", "白色颈饰"),
    ],
    "服装系统/头部配饰": [
        ("black hairband", "黑色发箍"), ("white hairband", "白色发箍"),
        ("white bow", "白色蝴蝶结"), ("red halo", "红色光环"),
    ],
    "服装系统/腿袜与内衣": [
        ("black pantyhose", "黑色连裤袜"), ("white pantyhose", "白色连裤袜"),
        ("black thighhighs", "黑色过膝袜"), ("white thighhighs", "白色过膝袜"),
    ],
    "服装系统/服装细节": [
        ("black sailor collar", "黑色水手领"), ("white neckerchief", "白色领巾"),
        ("clothes lift", "掀起衣服"), ("clothes pull", "拉拽衣服"),
        ("shirt lift", "掀起衬衫"), ("pantyhose pull", "拉扯连裤袜"),
        ("black ribbon", "黑色缎带"), ("white ribbon", "白色缎带"),
    ],
    "服装系统/上装": [
        ("black shirt", "黑色衬衫"), ("white shirt", "白色衬衫"),
        ("black dress", "黑色连衣裙"), ("white dress", "白色连衣裙"),
    ],
    "人物主体/发型": [
        ("single braid", "单侧麻花辫"),
    ],
    "人物主体/表情": [
        ("nose blush", "鼻尖泛红"),
    ],
    "姿势动作/手部动作": [
        ("implied masturbation", "暗示自慰"),   # nsfw, 由下面的 _NSFW_WORDS 标记
    ],
}

# 需要打 NSFW 标记的词 (否则关了 NSFW 也会被抽出来)
_NSFW_WORDS = {"implied masturbation"}

# ---------------------------------------------------------------- 性别标记 (gender)
# 引擎靠"带性别标记的人数词"置位 led.gender_lock, 之后拦截异性专属词。
# 实测只有 33% 的轮次能锁上 —— 因为 2girls / multiple girls / 2boys 这些
# **本身已声明性别**的人数词全都没有 gender 标记, 于是外貌与服装槽照样混抽,
# 重新出现 "1boy + faceless female" 那类矛盾。
# （`1girl and 1boy` / `couple` 等属混合宣言, 由 engine.MIXED_COUNT_WORDS 处理, 不在此列。）
GENDER_FIXES: dict[str, str] = {
    "1girl": "female", "1other": "female",
    "2girls": "female", "3girls": "female", "4girls": "female",
    "5girls": "female", "6+girls": "female",
    "multiple girls": "female", "group of girls": "female",
    "1boy": "male", "2boys": "male", "3boys": "male",
    "multiple boys": "male", "group of boys": "male",
}

# ---------------------------------------------------------------- 归位 (move)
# 从 (源槽位) 搬到 (目标槽位)。用于修正"放错槽位导致语义失效"的词。
#
# 实测发现「人物主体/人数」槽 36 个词里混了 6 个**非人数词**:
#   faceless / faceless female / faceless male / out of frame /
#   upper body only implied / solo focus
# 人数据配额是 (1,1) —— 全库只出 1 个词, 若被这类词占掉, 就没有
# `1girl`/`1boy` 出场 → 引擎的性别锁 (led.gender_lock) 永远不会置位,
# 于是重新出现 "1boy + faceless female" 这类自相矛盾的输出。
# 它们本质是"主体可见度 / 构图"词, 归到构图镜头。
MOVES: list[tuple[str, str, str]] = [
    ("人物主体/人数", "构图镜头/构图", "faceless"),
    ("人物主体/人数", "构图镜头/构图", "faceless female"),
    ("人物主体/人数", "构图镜头/构图", "faceless male"),
    ("人物主体/人数", "构图镜头/构图", "out of frame"),
    ("人物主体/人数", "构图镜头/构图", "upper body only implied"),
    ("人物主体/人数", "构图镜头/构图", "solo focus"),
]


def _index(lib: dict) -> dict:
    """"大类/子类" -> sub dict (键与 ADDITIONS 保持同一形式, 避免元组/字符串混用)"""
    out = {}
    for c in lib.get("categories", []):
        for s in c.get("subcategories", []):
            out[f'{c.get("name", "")}/{s.get("name", "")}'] = s
    return out


def _plan_one(path: str) -> tuple[list, dict]:
    """返回 (待新增词表, 该文件的槽位索引)。

    ⚠ 必须同时写入出厂库与用户库: `library.get_merged()` 走 deep_merge, 用户库优先,
    只写出厂库时新增词会被用户库的同 id 子分类整个覆盖掉 (实测 merged 只多出 16 词)。
    """
    raw = json.load(open(path, encoding="utf-8"))
    idx = _index(raw)
    planned = []
    for slot, words in ADDITIONS.items():
        sub = idx.get(slot)
        if sub is None:
            continue
        existing = {str(t.get("en", "")).strip().lower() for t in sub.get("tags") or []}
        for en, zh in words:
            if en.strip().lower() in existing:
                continue
            planned.append((slot, en, zh))
            existing.add(en.strip().lower())
    return planned, idx


def main() -> int:
    apply = "--apply" in sys.argv
    targets = [p for p in (library.DEFAULT_PATH, library.USER_PATH) if os.path.isfile(p)]

    total_new = 0
    plans = {}
    for path in targets:
        planned, idx = _plan_one(path)
        plans[path] = (planned, idx)
        total_new += len(planned)
        print(f"{os.path.basename(path)}: 待新增 {len(planned)} 词")

    # MOVES 也计入改动 (否则只剩归位可做时会误判"无改动")
    move_count = 0
    for path in targets:
        raw = json.load(open(path, encoding="utf-8"))
        idxm = _index(raw)
        for src, dst, en in MOVES:
            s_sub = idxm.get(src)
            if s_sub and any(str(t.get("en", "")).strip().lower() == en
                             for t in (s_sub.get("tags") or [])):
                move_count += 1
    if move_count:
        print(f"归位 {move_count} 词 (跨库合计)")
    gfix_count = 0
    for path in targets:
        raw = json.load(open(path, encoding="utf-8"))
        for sub in _index(raw).values():
            for t in sub.get("tags") or []:
                en = str(t.get("en", "")).strip().lower()
                if en in GENDER_FIXES and t.get("gender") != GENDER_FIXES[en]:
                    gfix_count += 1
    if gfix_count:
        print(f"性别标记 {gfix_count} 词 (跨库合计)")
    if total_new == 0 and move_count == 0 and gfix_count == 0:
        print("(无改动; 幂等)")
        return 0
    from collections import Counter
    agg = Counter(s for path in plans for s, _e, _z in plans[path][0])
    for slot, cnt in agg.most_common():
        print(f"   {slot:<24} +{cnt}")
    if not apply:
        print("\n(dry-run; 加 --apply 落盘)")
        return 0

    for path, (planned, idx) in plans.items():
        raw = json.load(open(path, encoding="utf-8"))
        idx2 = _index(raw)
        moved = 0
        for src, dst, en in MOVES:
            s_sub, d_sub = idx2.get(src), idx2.get(dst)
            if s_sub is None or d_sub is None:
                continue
            hit = next((t for t in (s_sub.get("tags") or [])
                        if str(t.get("en", "")).strip().lower() == en), None)
            if hit is None:
                continue
            s_sub["tags"] = [t for t in (s_sub.get("tags") or []) if t is not hit]
            # 换槽位后必须把 id / axis / type 一起清掉: 这三个都是从"大类/子类路径"
            # 推导或分配的, 留着旧值会让 runtime_snapshot 优先用陈旧 axis
            # (实测 "out of frame" 搬到构图槽后 axis 仍是 count, 于是它被当成
            #  第二个人数词写进输出, 段位序也跟着回退)。
            for _k in ("id", "axis", "type"):
                hit.pop(_k, None)
            d_sub.setdefault("tags", []).append(hit)
            moved += 1
        gfixed = 0
        for en, g in GENDER_FIXES.items():
            for sub in idx2.values():
                for t in sub.get("tags") or []:
                    if str(t.get("en", "")).strip().lower() == en and t.get("gender") != g:
                        t["gender"] = g
                        gfixed += 1
        if not planned and not moved and not gfixed:
            continue
        for slot, en, zh in planned:
            entry = {"en": en, "zh": zh, "weight": 1.0}
            if en.strip().lower() in _NSFW_WORDS:
                entry["nsfw"] = True
            idx2[slot].setdefault("tags", []).append(entry)
        raw.pop("schema_version", None)
        schema.migrate_library(raw)
        bak = f"{path}.bak-{datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(path, bak)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(raw, f, ensure_ascii=False, indent=1)
        print(f"✅ {os.path.basename(path)}: +{len(planned)} 词, 归位 {moved} 词, "
              f"性别标记 {gfixed} 词 (备份 {os.path.basename(bak)})")

    library.invalidate_cache()
    try:
        library.sync_to_folder_snapshot()
        print("✅ .md 镜像已重建")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 镜像重建失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
