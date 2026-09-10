"""轴模型 (1.3.0) —— 分类树降级为 UI 视图, 组合语义由轴+组+资源+状态决定。

三条推导规则取代 81 条中央冲突表:
  R1 同组互斥   : 标签 `groups` 字段 (全局命名空间) —— 任意两词共享同一组值即互斥
                  (跨池也成立: dress 与 shirt 共享 body.cover.upper)。
  R2 跨池集合规则: data/default/mutex.json 少量结构性规则 (nude↔服装池 这类
                  tag↔整池/子池 的批量事实), 由 migrate_rules 一次性从旧
                  conflicts.json 机械迁移而来, 不再是手写维护的中央规则表。
  R3 资源预算   : profiles.json 中每条姿势声明 hands/gaze, 抽取时实时算账,
                  超预算的组合在出生前丢弃 (预防, 不是事后修复)。
  R4 状态槽     : profiles.json 中同一武器同一时刻只能一个 state,
                  sheathed+slash 在编译期不可能构造。

轴本身 (axis_of_sub) 决定输出顺序 (Anima 拼接序) 并作为词条档案的挂载域。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 轴定义

AXIS_ORDER = [
    "meta",            # 画质/通用质量词 (masterpiece…)
    "count",           # 人数
    "character",       # 角色/种族/年龄等身份域
    "appearance",      # 外貌 (发/眼/体型/皮肤/表情…)
    "clothing",        # 服装 (含裸露)
    "prop",            # 道具 (武器/食物/日用/乐器/动物伙伴)
    "action",          # 动作 (姿势/手部/视线/互动; 武器姿势来自档案束)
    "environment",     # 场景环境
    "lighting",        # 光影氛围
    "camera",          # 构图镜头
    "style",           # 风格媒介
    "material",        # 材质特效
]

# ---------------------------------------------------------------- 轴的中文显示名
# S4 重构后, 库里 categories 的第一级**就是轴**, 用中文名做目录名 (md 镜像 = 轴/槽位/槽位.md)。
# 这些名字与前端 AXES_ZH / 迁移前的部分大类名保持一致, 避免用户重新认路。
AXIS_NAME_ZH: dict[str, str] = {
    "meta": "画质规格", "count": "人数", "character": "角色身份",
    "appearance": "外貌特征", "clothing": "服装", "prop": "道具武器",
    "action": "动作姿态", "environment": "场景环境", "lighting": "光影氛围",
    "camera": "构图镜头", "style": "风格媒介", "material": "材质特效",
}
AXIS_ZH_TO_ID: dict[str, str] = {v: k for k, v in AXIS_NAME_ZH.items()}

# 迁移前的 9 个大类名 (仅用于 migrate_to_axes.py 识别旧路径; S4 之后不再出现于数据里)
SUB_TO_AXIS_OLD_CATS: frozenset = frozenset({
    "画质规格", "人物主体", "服装系统", "姿势动作", "构图镜头",
    "光影氛围", "场景环境", "风格媒介", "材质特效",
})

# ---------------------------------------------------------------- 输出段位 (Anima tag order)
# Anima 作者规定的六段拼接序 (三处独立来源一致, 见 docs/UI-REDESIGN-PLAN.md §2.2):
#
#   [quality / meta / year / safety + style slot] [1girl/1boy] [character] [series] [artist @] [general]
#   「每段内部顺序无所谓」
#
# 关键点: **style 必须在第 1 段** (它是"换一个词就换整体观感"的控制点),
# 而原先 AXIS_ORDER 把 style 排在第 11 位 —— 这是与目标模型口径的直接冲突。
#
# ⚠ 段位只决定**输出**次序; **抽取**次序 (pool_order) 仍走下面的轴次序 ——
#   人数词必须先抽到才能锁性别 (见 run_auto 的 led.gender_lock),
#   若让 style 先于 count 出生, 性别锁会失效、重新出现
#   "1boy + faceless female" 这类矛盾。
AXIS_SECTION: dict[str, int] = {
    "meta": 1, "style": 1,            # 质量/元信息 + 风格槽
    "count": 2,                        # 1girl / 1boy / 1other
    "character": 3,                    # 具名角色
    # 4 = series(copyright) / 5 = artist(@) —— 暂无对应轴, 词表补齐后接入
    "appearance": 6, "clothing": 6, "prop": 6, "action": 6,
    "environment": 6, "lighting": 6, "camera": 6, "material": 6,
    "misc": 9,
}

SECTION_NAMES: dict[int, str] = {
    1: "质量·元信息·风格", 2: "人数", 3: "角色",
    4: "作品", 5: "画师", 6: "通用", 9: "未归类",
}


def section_of(axis: str) -> int:
    return AXIS_SECTION.get(axis, 6)


def output_order(axis: str, axis_order: int) -> int:
    """段位优先, 段内沿用轴次序 → Anima 拼接序。"""
    return section_of(axis) * 10000 + int(axis_order)


# 每轴一个百位区间, 轴内按语义排次序 (抽取次序 = 约束生效序)。
# "大类/子类" 路径名 → (轴, 次序)。路径名是稳定键 (同 slots.json 约定,
# 免疫库重建导致的 id 变化); 未命中的子类落入 ("misc", 9900) 排在最后。
SUB_TO_AXIS: dict[str, tuple[str, int]] = {
    # ---- meta: 画质规格 (0-99)
    "画质规格/画质增强":        ("meta", 0),
    "画质规格/细节强化":        ("meta", 1),
    # ---- count: 人数 (100)
    "人物主体/人数":            ("count", 100),
    # ---- character: 身份域 (200-299)
    "人物主体/年龄阶段":        ("character", 200),
    "人物主体/种族与幻想身份":  ("character", 201),
    # ---- appearance: 外貌 (300-399)
    "人物主体/发型":            ("appearance", 300),
    "人物主体/发色":            ("appearance", 301),
    "人物主体/眼部":            ("appearance", 302),
    "人物主体/妆容与胡须":      ("appearance", 303),
    "人物主体/体型":            ("appearance", 304),
    "人物主体/表情":            ("appearance", 305),
    "人物主体/嘴部动作":        ("appearance", 306),
    "人物主体/情绪与状态":      ("appearance", 307),
    "人物主体/皮肤与印记":      ("appearance", 308),
    "人物主体/非人特征":        ("appearance", 309),
    # ---- clothing: 服装 (400-499), 裸露最先 (覆盖组互斥在数据层表达)
    "人物主体/裸露与暴露":      ("clothing", 400),
    "服装系统/上装":            ("clothing", 401),
    "服装系统/下装":            ("clothing", 402),
    "服装系统/裙装与礼服":      ("clothing", 403),
    "服装系统/职业与制服":      ("clothing", 404),
    "服装系统/传统与民族":      ("clothing", 405),
    "服装系统/特色与运动装":    ("clothing", 406),
    "服装系统/腿袜与内衣":      ("clothing", 407),
    "服装系统/鞋子":            ("clothing", 408),
    "服装系统/头部配饰":        ("clothing", 409),
    "服装系统/首饰珠宝":        ("clothing", 410),
    "服装系统/手套围巾与包袋":  ("clothing", 411),
    "服装系统/服装细节":        ("clothing", 412),
    # ---- prop: 道具 (500-599)
    "人物主体/武器装备":        ("prop", 500),
    "人物主体/食物饮品":        ("prop", 501),
    "人物主体/日用道具":        ("prop", 502),
    "人物主体/乐器与运动":      ("prop", 503),
    "人物主体/动物伙伴":        ("prop", 504),
    # ---- action: 动作 (600-699)
    "姿势动作/站走与动态":      ("action", 600),
    "姿势动作/坐姿":            ("action", 601),
    "姿势动作/躺跪与趴伏":      ("action", 602),
    "姿势动作/互动与双人":      ("action", 603),
    "姿势动作/头颈与倚靠":      ("action", 604),
    "姿势动作/手部动作":        ("action", 605),
    "姿势动作/视线":            ("action", 606),
    # ---- environment: 场景 (700-799)
    "场景环境/室内":            ("environment", 700),
    "场景环境/自然景观":        ("environment", 701),
    "场景环境/城镇人文":        ("environment", 702),
    "场景环境/幻想科幻":        ("environment", 703),
    "场景环境/时间时段":        ("environment", 704),
    "场景环境/天气现象":        ("environment", 705),
    "场景环境/月与星空":        ("environment", 706),
    "场景环境/节日与季节":      ("environment", 707),
    "场景环境/氛围粒子":        ("environment", 708),
    "场景环境/背景处理":        ("environment", 709),
    # ---- lighting: 光影 (800-899)
    "光影氛围/自然光":          ("lighting", 800),
    "光影氛围/人工光":          ("lighting", 801),
    "光影氛围/光影手法与效果":  ("lighting", 802),
    "光影氛围/氛围情绪":        ("lighting", 803),
    # ---- camera: 构图镜头 (900-999)
    "构图镜头/取景范围":        ("camera", 900),
    "构图镜头/视角":            ("camera", 901),
    "构图镜头/镜头语言":        ("camera", 902),
    "构图镜头/构图":            ("camera", 903),
    # ---- style: 风格媒介 (1000-1099)
    "风格媒介/写实摄影":        ("style", 1000),
    "风格媒介/二次元向":        ("style", 1001),
    "风格媒介/艺术媒介":        ("style", 1002),
    "风格媒介/题材风格":        ("style", 1003),
    "风格媒介/色彩调配":        ("style", 1004),
    # ---- material: 材质特效 (1100-1199)
    "材质特效/材质":            ("material", 1100),
    "材质特效/视觉特效":        ("material", 1101),
}


# S4 重构后的路径表: "轴中文名/槽位名" → (轴 id, 次序)。
# 由 tools/migrate_to_axes.py 生成 —— 按 SUB_TO_AXIS 把 63 个槽位重挂到 12 条轴。
SUB_TO_AXIS_V2: dict[str, tuple[str, int]] = {
    # ---- 画质规格 (meta) ----
    "画质规格/画质增强": ("meta", 0),
    "画质规格/细节强化": ("meta", 1),
    # ---- 人数 (count) ----
    "人数/人数": ("count", 100),
    # ---- 角色身份 (character) ----
    "角色身份/年龄阶段": ("character", 200),
    "角色身份/种族与幻想身份": ("character", 201),
    # ---- 外貌特征 (appearance) ----
    "外貌特征/发型": ("appearance", 300),
    "外貌特征/发色": ("appearance", 301),
    "外貌特征/眼部": ("appearance", 302),
    "外貌特征/妆容与胡须": ("appearance", 303),
    "外貌特征/体型": ("appearance", 304),
    "外貌特征/表情": ("appearance", 305),
    "外貌特征/嘴部动作": ("appearance", 306),
    "外貌特征/情绪与状态": ("appearance", 307),
    "外貌特征/皮肤与印记": ("appearance", 308),
    "外貌特征/非人特征": ("appearance", 309),
    # ---- 服装 (clothing) ----
    "服装/裸露与暴露": ("clothing", 400),
    "服装/上装": ("clothing", 401),
    "服装/下装": ("clothing", 402),
    "服装/裙装与礼服": ("clothing", 403),
    "服装/职业与制服": ("clothing", 404),
    "服装/传统与民族": ("clothing", 405),
    "服装/特色与运动装": ("clothing", 406),
    "服装/腿袜与内衣": ("clothing", 407),
    "服装/鞋子": ("clothing", 408),
    "服装/头部配饰": ("clothing", 409),
    "服装/首饰珠宝": ("clothing", 410),
    "服装/手套围巾与包袋": ("clothing", 411),
    "服装/服装细节": ("clothing", 412),
    # ---- 道具武器 (prop) ----
    "道具武器/武器装备": ("prop", 500),
    "道具武器/食物饮品": ("prop", 501),
    "道具武器/日用道具": ("prop", 502),
    "道具武器/乐器与运动": ("prop", 503),
    "道具武器/动物伙伴": ("prop", 504),
    # ---- 动作姿态 (action) ----
    "动作姿态/站走与动态": ("action", 600),
    "动作姿态/坐姿": ("action", 601),
    "动作姿态/躺跪与趴伏": ("action", 602),
    "动作姿态/互动与双人": ("action", 603),
    "动作姿态/头颈与倚靠": ("action", 604),
    "动作姿态/手部动作": ("action", 605),
    "动作姿态/视线": ("action", 606),
    # ---- 场景环境 (environment) ----
    "场景环境/室内": ("environment", 700),
    "场景环境/自然景观": ("environment", 701),
    "场景环境/城镇人文": ("environment", 702),
    "场景环境/幻想科幻": ("environment", 703),
    "场景环境/时间时段": ("environment", 704),
    "场景环境/天气现象": ("environment", 705),
    "场景环境/月与星空": ("environment", 706),
    "场景环境/节日与季节": ("environment", 707),
    "场景环境/氛围粒子": ("environment", 708),
    "场景环境/背景处理": ("environment", 709),
    # ---- 光影氛围 (lighting) ----
    "光影氛围/自然光": ("lighting", 800),
    "光影氛围/人工光": ("lighting", 801),
    "光影氛围/光影手法与效果": ("lighting", 802),
    "光影氛围/氛围情绪": ("lighting", 803),
    # ---- 构图镜头 (camera) ----
    "构图镜头/取景范围": ("camera", 900),
    "构图镜头/视角": ("camera", 901),
    "构图镜头/镜头语言": ("camera", 902),
    "构图镜头/构图": ("camera", 903),
    # ---- 风格媒介 (style) ----
    "风格媒介/写实摄影": ("style", 1000),
    "风格媒介/二次元向": ("style", 1001),
    "风格媒介/艺术媒介": ("style", 1002),
    "风格媒介/题材风格": ("style", 1003),
    "风格媒介/色彩调配": ("style", 1004),
    # ---- 材质特效 (material) ----
    "材质特效/材质": ("material", 1100),
    "材质特效/视觉特效": ("material", 1101),
}


def axis_of(cat_name: str, sub_name: str) -> tuple[str, int]:
    """槽位 → (轴 id, 次序)。

    两种结构都要能算:
      · S4 之后: 第一级就是轴的中文名 → 查 SUB_TO_AXIS_V2, 命中即返回;
      · S4 之前: 第一级是旧大类名 → 查 SUB_TO_AXIS (迁移工具依赖这条路径)。
    两者都未命中时落 misc 排最后。
    """
    key = f"{cat_name}/{sub_name}"
    hit = SUB_TO_AXIS_V2.get(key)
    if hit is not None:
        return hit
    if cat_name in AXIS_ZH_TO_ID:          # 是轴名但槽位未登记 → 轴内默认序
        ax = AXIS_ZH_TO_ID[cat_name]
        return ax, AXIS_ORDER.index(ax) * 100 + 90
    return SUB_TO_AXIS.get(key, ("misc", 9900))


def is_action_axis(cat_name: str, sub_name: str) -> bool:
    return axis_of(cat_name, sub_name)[0] == "action"
