"""槽位抽取策略 —— 每个槽位该出几个词，哪些槽位互斥。

## 为什么需要这个模块

原先 `fill_master_min/max` 的语义是「**每个**槽位抽 N 个」，63 个槽位相乘
直接爆到 200+ 词（实测 200~213 词，而群里在用的基准提示词是 62 词）。
更糟的是**年龄 / 表情 / 天气 / 时间 / 鞋类 / 场景地点**这些天然只能选一个的维度
被抽成 3~5 个，产出大量自相矛盾的 prompt：

    实测 seed101: daytime + starry night sky + eclipse night   ← 白天与夜晚同现
                  toddler + middle-aged man + elderly man       ← 三个年龄段
                  snow flurry + light snow + heat haze + fog bank ← 四种天气
                  espadrilles + slides + high-top sneakers + soccer cleats ← 四双鞋

本模块把「抽多少」从**一个全局数字**改为**逐槽位配额 + 互斥槽位组**。

## 两张表

- `SLOT_MAX`   : 槽位 → (最多出几个, 至少出几个)。0 = 可选，配额不足时可不出。
- `EXCLUSIVE`  : 若干槽位构成"至多一个贡献词"的组（场景地点四选一、光源二选一…）。

键用的是 `snap.sub_keys[si]`（"大类/子类"）。S4 分类重构后需要同步更新本表 ——
届时会改为按「主题组 + 段位」表达（见 docs/UI-REDESIGN-PLAN.md §2）。
"""

from __future__ import annotations

# ------------------------------------------------------------------ 逐槽位配额
# (max_n, min_n)
SLOT_MAX: dict[str, tuple[int, int]] = {
    # ---- 第 1 段: 质量 / 元信息 (对齐 Anima 推荐前缀 + 群内提示词的实际用量) ----
    # 参考提示词的质量/细节块有约 16 个词 (score_9/8/7 + masterpiece + best quality
    # + amazing quality + very aesthetic + absurdres + newest + highres + ultra-detailed
    # + huge filesize + detailed eyes + detailed pupils + sharp focus …),
    # 所以这两槽的配额要比其它槽宽。
    "画质规格/画质增强": (5, 3),
    "画质规格/细节强化": (4, 2),

    # ---- 第 2 段: 人数 (单选 + 必出) ----
    "人数/人数": (1, 1),

    # ---- 第 3 段: 角色身份 (单选) ----
    "角色身份/年龄阶段": (1, 0),
    "角色身份/种族与幻想身份": (1, 0),

    # ---- 第 5 段: 画师 (留空, 且默认关闭 → 只有你手动启用才会抽) ----
    # 画师是"选定"而不是"随机"的维度; 槽位留空是为了让你自己往里填 @画师名。
    "画师/画师名": (1, 0),

    # ---- 第 6 段: general ----
    "外貌特征/发型": (2, 1),
    "外貌特征/发色": (1, 0),
    "外貌特征/眼部": (2, 0),
    "外貌特征/妆容与胡须": (1, 0),
    "外貌特征/体型": (1, 0),
    "外貌特征/表情": (1, 0),
    "外貌特征/嘴部动作": (1, 0),
    "外貌特征/情绪与状态": (1, 0),
    "外貌特征/皮肤与印记": (1, 0),
    "外貌特征/非人特征": (1, 0),
    "外貌特征/身体细节": (2, 0),     # ext: 解剖细节, 可出 2 个 (如 puffy nipples + pubic hair)
    "服装/服装状态": (2, 0),         # ext: 半脱机制 (clothes lift + panties aside 可同现)
    "服装/裸露与暴露": (1, 0),
    "道具武器/武器装备": (2, 0),
    "道具武器/日用道具": (2, 0),
    "道具武器/乐器与运动": (1, 0),
    "道具武器/食物饮品": (1, 0),
    "道具武器/动物伙伴": (1, 0),
    "道具武器/束缚道具": (1, 0),     # ext: 成人玩具/拘束具

    "服装/上装": (2, 1),
    "服装/下装": (1, 0),
    "服装/裙装与礼服": (1, 0),
    "服装/职业与制服": (1, 0),
    "服装/传统与民族": (1, 0),
    "服装/特色与运动装": (1, 0),
    "服装/腿袜与内衣": (2, 0),
    "服装/鞋子": (1, 0),
    "服装/头部配饰": (1, 0),
    "服装/首饰珠宝": (3, 0),
    "服装/手套围巾与包袋": (1, 0),
    "服装/服装细节": (2, 0),

    "动作姿态/站走与动态": (1, 0),
    "动作姿态/坐姿": (1, 0),
    "动作姿态/躺跪与趴伏": (1, 0),
    "动作姿态/体位": (1, 0),         # ext: 性体位; 与站/坐/躺同属 posture_base 组
    "动作姿态/互动与双人": (1, 0),
    "动作姿态/头颈与倚靠": (1, 0),
    "动作姿态/手部动作": (2, 0),
    "动作姿态/视线": (1, 0),
    "动作姿态/性行为": (2, 0),       # ext: 行为动词 (oral+vaginal 类可同现)
    "动作姿态/束缚与调教": (1, 0),   # ext
    "动作姿态/高潮与体液": (2, 0),   # ext

    "场景环境/室内": (1, 0),
    "场景环境/自然景观": (1, 0),
    "场景环境/城镇人文": (1, 0),
    "场景环境/幻想科幻": (1, 0),
    "场景环境/时间时段": (1, 0),
    "场景环境/天气现象": (1, 0),
    "场景环境/月与星空": (1, 0),
    "场景环境/节日与季节": (1, 0),
    "场景环境/氛围粒子": (1, 0),
    "场景环境/背景处理": (1, 1),

    "光影氛围/自然光": (1, 0),
    "光影氛围/人工光": (1, 0),
    "光影氛围/光影手法与效果": (1, 0),
    "光影氛围/氛围情绪": (1, 0),

    "构图镜头/取景范围": (1, 0),
    "构图镜头/视角": (1, 0),
    "构图镜头/镜头语言": (1, 0),
    "构图镜头/构图": (1, 0),

    "风格媒介/写实摄影": (1, 0),
    "风格媒介/二次元向": (1, 0),
    "风格媒介/艺术媒介": (1, 0),
    "风格媒介/题材风格": (1, 0),
    "风格媒介/色彩调配": (1, 0),

    "材质特效/材质": (1, 0),
    "材质特效/视觉特效": (1, 0),
}

# 未列出的槽位按轴给默认 (取该轴已列槽位的最大值, 兜底 1)
AXIS_DEFAULT_MAX = 1


def caps_for(sub_key: str, axis: str = "") -> tuple[int, int]:
    """取槽位配额, 返回 **(min_n, max_n)** —— 注意与 SLOT_MAX 表里的 (max, min) 顺序相反。

    表里按 (max, min) 写是为了读表时"上限"在前更直观; 对外统一成 (min, max),
    与 engine 里 mn/mx 的用法一致。历史上这里顺序不一致导致过
    "所有 min_n=0 的槽位被整池跳过"的回归, 故在此显式声明。
    """
    hit = SLOT_MAX.get(sub_key)
    if hit is None:
        return (0, AXIS_DEFAULT_MAX)
    mx, mn = hit
    return (mn, mx)


# ------------------------------------------------------- 互斥槽位组 (至多一个贡献)
# 组内**只允许一个槽位出词**。这与 grouprules 的"标签级互斥"互补:
# grouprules 管"这两个词不能同时出现", 这里管"这两个槽位不该同时出词"。
EXCLUSIVE: list[tuple[str, tuple[str, ...]]] = [
    # 场景地点: 一个画面不可能既在室内又在自然景观又在城镇
    ("scene_place", ("场景环境/室内", "场景环境/自然景观",
                     "场景环境/城镇人文", "场景环境/幻想科幻")),
    # 风格基线: 写实与二次元是两条互斥主线
    ("style_base", ("风格媒介/写实摄影", "风格媒介/二次元向")),
    # 摄影与手绘媒介互斥 (真机实测: "product photography + shin-hanga") —
    # 二次元向不参与: "anime style + oil painting" 是常见组合, 不能并入
    ("style_photo_art", ("风格媒介/写实摄影", "风格媒介/艺术媒介")),
    # 主光源: 自然光与人工光互斥
    ("light_type", ("光影氛围/自然光", "光影氛围/人工光")),
    # 姿态基线: 站 / 坐 / 躺 / 性体位 只能一种
    # (体位槽是 ext 扩展包 NSFW 槽位, SFW 模式下空池不影响)
    ("posture_base", ("动作姿态/站走与动态", "动作姿态/坐姿",
                      "动作姿态/躺跪与趴伏", "动作姿态/体位")),
    # 时段与星空: 白天不该配星空
    ("day_night", ("场景环境/时间时段", "场景环境/月与星空")),
]

# slot_key -> 所属互斥组 id (便于 O(1) 查)
_SLOT_TO_EXCL: dict[str, str] = {}
for _gid, _keys in EXCLUSIVE:
    for _k in _keys:
        _SLOT_TO_EXCL[_k] = _gid


# ---------------------------------------------------------------- NSFW 配额加成 (1.8.0)
# NSFW 强度=纯欲 时叠加到槽位 max_n 上的词数 —— 权重乘数(×6)单独只能到配额顶,
# 实测 3.8→5.5 就撞墙; 配额同步放开后纯欲档才能让涩词主导画面。
NSFW_SLOT_BOOST: dict[str, int] = {
    "动作姿态/性行为": 2,
    "动作姿态/体位": 0,        # 体位仍单选 (posture_base 组), 配额不放大
    "服装/服装状态": 2,
    "动作姿态/高潮与体液": 2,
    "外貌特征/身体细节": 2,
    "道具武器/束缚道具": 1,
    "动作姿态/束缚与调教": 1,
    "服装/裸露与暴露": 1,
}


def nsfw_boost(sub_key: str) -> int:
    return NSFW_SLOT_BOOST.get(sub_key, 0)


# 纯欲档保底: 这些 NSFW 槽位至少出 N 词 (叠加到 min_n) —— 保底行为词在场,
# 解决"显式词被 mild 词稀释, ×6 权重也才 0.9 个/条"的实测问题。
NSFW_SLOT_MIN: dict[str, int] = {
    "动作姿态/性行为": 1,
    "服装/服装状态": 1,
}


def nsfw_min_boost(sub_key: str) -> int:
    return NSFW_SLOT_MIN.get(sub_key, 0)


def exclusive_group(sub_key: str) -> str:
    """该槽位所属的互斥组 id；不属于任何组时返回空串。"""
    return _SLOT_TO_EXCL.get(sub_key, "")


def total_max_sum() -> int:
    """按本表各槽位 max 求和 —— 作为总预算的天然上界 (供体检/断言用)。"""
    return sum(mx for mx, _mn in SLOT_MAX.values())


def total_min_sum() -> int:
    return sum(mn for _mx, mn in SLOT_MAX.values())


# ------------------------------------------------------------------ 人数语义
# 单人词: 出现即表示画面只有一个人 -> 互动类槽位不成立
SINGLE_COUNT_WORDS = frozenset({
    "solo", "1girl", "1boy", "1other", "single", "0others",
})

# 多人词: 表示画面有多人 -> 互动类槽位成立
# ⚠ 人数轴**每加一个词都要同步这张表和 nl._PRONOUN**, 否则: NL 尾段人称回落
#   "She" (large group 配 She has 的实测出处)、互动槽位该开不开。
# quality_gate_test Q10 固化了"人数轴词必须全部被分类"这道防线。
MULTI_COUNT_WORDS = frozenset({
    "2girls", "3girls", "4girls", "5girls", "6+girls", "2boys", "3boys",
    "multiple girls", "multiple boys", "multiple others", "group", "crowd",
    "1girl and 1boy", "1boy and 1girl", "couple", "everyone", "ot3",
    # 1.7.0 补齐 (此前漏分类: "large group + She has..." 人称错位实测)
    "group of girls", "group of boys", "trio", "quartet", "ensemble",
    "pair", "large group", "small group",
    # 1.8.0 ext 扩展包新增人数词 (新增人数词必须同步本表与 nl._PRONOUN)
    "4boys", "5boys", "6+boys",
})

# 仅在多人场景成立的槽位
MULTI_ONLY_SLOTS = frozenset({"动作姿态/互动与双人"})

# --------------------------------------------------- 词 ↔ 槽位 双向屏蔽
# 有些矛盾跨槽位, 配额(每槽上限)与互斥槽位组都拦不住。实测抓到的一例:
#   `bare feet` (裸露与暴露槽) + `boots` (鞋子槽) 同现 —— "赤足" 与 "穿靴" 直接打架。
# 两个方向都要写: 先抽到任一侧, 另一侧就不再出词。
BLOCK_SLOTS_BY_WORD: dict[str, frozenset[str]] = {
    "bare feet": frozenset({"服装/鞋子"}),
    "barefoot": frozenset({"服装/鞋子"}),
}
BLOCK_WORDS_BY_SLOT: dict[str, frozenset[str]] = {
    "服装/鞋子": frozenset({"bare feet", "barefoot"}),
}

# "画面里没有人"的人数词 —— 出现即抑制全部人物相关轴,
# 否则会产出 "no humans + long hair" 这类直接矛盾的组合。
NO_HUMAN_COUNT_WORDS = frozenset({"no humans"})
NO_HUMAN_SKIP_AXES = frozenset({"character", "appearance", "clothing"})

# ------------------------------------------------------------------ 未成年锁定
# 动机 (真机实测): "toddler + side-tie panties" —— 年龄词与成人内容跨 9 个槽位,
# 配额/互斥槽位组/跨池规则都管不到。这里做成**词级黑名单**: 任何未成年年龄词
# 一经出生 (抽取/钉选), 黑名单词在候选级 (engine.tag_ok) 全池屏蔽。
# 词表是人工整理的**成人向子集** —— 裸露/腿袜两槽里的 "bare shoulders"、
# "thighhighs" 等日常词保持可用, 不能整槽屏蔽。
MINOR_AGE_WORDS = frozenset({
    "toddler", "infant", "child", "preteen", "loli", "shota",
    "teen", "teenage girl", "teenage boy", "early teens", "late teens",
    "young girl", "young boy",
})

MINOR_BLOCK_WORDS = frozenset({
    # 裸露与暴露 (成人向子集; bare shoulders/legs/back 等日常词不在内)
    "nude", "topless", "completely nude", "nipples", "puffy nipples",
    "underboob", "sideboob", "cleavage", "deep cleavage", "underboob cleavage",
    "sideboob exposure", "micro bikini", "string bikini", "naked apron",
    "spread legs", "ahegao", "partially nude", "bottomless", "naked towel",
    "naked ribbon", "covered nipples", "hair over breasts",
    "see-through clothing", "cameltoe", "erect nipples", "areolae",
    "pubic hair", "shaved", "visible areola through clothes",
    "micro skirt", "lingerie",
    # 腿袜与内衣 (内衣/裤袜子类; thighhighs/socks 等日常裤袜不在内)
    "thong", "frilled panties", "side-tie panties", "chastity belt",
    "crotchless panties", "sheer panties", "boyshorts panties",
    "high-waisted panties", "thong with garter", "seamless panties",
    "underwear", "bra", "sports bra", "push-up bra", "lace bra",
    "strapless bra", "balconette bra", "boyshorts",
    "garter belt", "garter straps", "garter stockings",
    "stockings with garter",
    # 其他槽位的成人向词 (体型/表情/皮肤/泳装/首饰/手部/氛围情绪)
    "huge breasts", "small breasts", "perky breasts", "medium breasts",
    "large breasts", "breasts", "mole on breast", "nipple piercing",
    "covering breasts", "holding own breast",
    "seductive", "seductive smile", "erotic mood",
    "swimsuit", "competition swimsuit",
    # 1.8.0 补齐: 工厂库带 nsfw 标志但此前未入黑名单的 13 词
    # (门禁 nsfw_pack_test E1 固化: 所有 nsfw 词必须被未成年锁覆盖)
    "heart-shaped pupils", "sucking", "aroused", "post-orgasm", "afterglow",
    "covered chest", "navel piercing",
    "kissing", "deep kiss", "neck kiss", "french kiss",
    "implied masturbation", "sensual atmosphere",
})


# ---------------------------------------------------------------- 场景条白名单 (1.8.1)
# 面板「场景条」三开关 (👤单人锁 / 🖼简洁背景 / 🎯人物特写) 的引擎侧词表。
# 数据源 = 库内实际词 (背景处理 40 词 / 取景范围 44 词), 白名单只收"简洁/特写"语义族。

# bg_mode=simple: 背景处理槽只允许这些词 (简洁/纯色/虚化/棚拍族)
SIMPLE_BG_WORDS = frozenset({
    "simple background", "white background", "pure white background",
    "pure black background", "pitch black background", "black background",
    "grey background", "pink background", "gradient background",
    "abstract background", "minimal backdrop", "cyclorama",
    "studio seamless", "green screen", "transparent background",
    "blurry background", "bokeh background", "bokeh circles background",
    "halftone background", "screentone background",
})

# bg_mode=simple: 整槽排除的具象场景槽 (简洁背景不该出现具体地点/天气/粒子)
# ⚠ 背景处理槽不在禁列 —— 它是 min_n=1 必出槽, simple 模式下按 SIMPLE_BG_WORDS 白名单过滤
SIMPLE_BG_BAN_SLOTS = frozenset({
    "场景环境/室内", "场景环境/自然景观", "场景环境/城镇人文",
    "场景环境/幻想科幻", "场景环境/节日与季节", "场景环境/氛围粒子",
    "场景环境/月与星空", "场景环境/天气现象", "场景环境/时间时段",
})

# focus_mode=portrait: 整槽排除的道具槽 (特写画面里这些是杂物)
PORTRAIT_BAN_SLOTS = frozenset({
    "道具武器/日用道具", "道具武器/食物饮品", "道具武器/乐器与运动",
    "道具武器/动物伙伴", "道具武器/束缚道具",
})

# 模糊年龄词 (teen 系): NSFW 开启时源头排除 —— 未成年锁只挡成人向子集
# (日常词按 v1.7.1 政策豁免), teen 系词本身年龄歧义, 涩涩场景直接不碰最稳。
# toddler/child/loli/shota 等明确词维持原机制 (conflicts 规则 + MINOR_AGE_WORDS)。
TEEN_AGE_WORDS = frozenset({
    "teen", "teenage girl", "teenage boy", "early teens", "late teens",
    "young girl", "young boy",
})

# focus_mode=portrait: 取景范围槽只允许这些词 (人物特写族)
PORTRAIT_FRAMING_WORDS = frozenset({
    "portrait", "close-up", "medium close-up", "medium shot",
    "upper body", "upper body three quarter", "cowboy shot",
    "face focus", "headshot", "bust shot", "intimate close-up",
    "from the chest up", "knee-up shot",
})


# ---------------------------------------------------------------- 单人锁补充 (1.8.1)
# 👤单人锁除人数轴/互动槽外, 还要封"隐含多人的行为词" —— 否则 1other + gangbang 这类
# 组合漏网 (真机审看实测)。武器/道具词不在列。
SOLO_BAN_WORDS = frozenset({
    "gangbang", "group sex", "orgy", "threesome", "ffm threesome", "mmf threesome",
    "foursome", "spitroast", "double penetration", "surrounded by penises",
    "cooperative fellatio", "cooperative paizuri", "teamwork (sexual)",
    "mutual masturbation", "futa with female", "surrounded by penises",
    # 1other = "画面里另有一人" -> 单人锁下语义自相矛盾, 实测 60 seed 里 18 条照出
    # (2026-09-21)。它同时留在 SINGLE_COUNT_WORDS 里: 那是"分类"(Q10 要求人数轴
    # 每个词都被分类), 这里是"单人锁下的禁令", 两件事, 不冲突。
    "1other",
})
