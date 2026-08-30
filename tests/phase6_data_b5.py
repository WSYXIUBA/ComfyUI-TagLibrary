# -*- coding: utf-8 -*-
"""阶段6扩库数据 —— 批次5: 收尾批 (发型/眼部/体型补充 + 表情嘴部联动 + NSFW 正规化)。

重点:
  - 补齐 legacy 冲突组引用的剩余缺失标签
  - 表情情绪的嘴部/眼睛细分标签补全
  - NSFW 分级 0-5 基础: 保持布尔 nsfw, 但把露骨度用 desc 标注 (L1-L4)
"""

BATCH5 = {
    # ---------------- 人物主体 ----------------
    "subject.s2.g1": {  # 发型 +8
        "adds": [
            ("hair over one eye", "单眼遮发"),
            ("hair over both eyes", "双眼遮发"),
            ("asymmetrical bangs", "不对称刘海"),
            ("braided bangs", "编发刘海"),
            ("hair flaps", "双垂发"),
            ("cotton hair", "蓬松圆发"),
            ("low twintails (short)", "低位短双马尾"),
            ("regulation haircut", "学生头"),
        ],
    },
    "subject.s2.g2": {  # 眼部 +10
        "adds": [
            ("yellow eyes", "黄色眼睛"),
            ("light purple eyes", "浅紫眼睛"),
            ("gradient eyes", "渐变瞳"),
            ("tsubame-style eyes", "燕尾眼"),
            ("upturned eyes", "吊眼"),
            ("downturned eyes", "垂眼"),
            ("sleepy eyes", "睡眼"),
            ("kagome-style eyes", "大圆眼"),
            ("eyeshadow", "眼影"),
            ("mascara", "睫毛膏"),
        ],
    },
    "subject.s2.g3": {  # 体型 +12
        "adds": [
            ("petite body", "娇小身材"),
            ("statuesque", "高挑健美"),
            ("pear-shaped figure", "梨形身材"),
            ("hourglass figure", "沙漏身材"),
            ("toned abs", "腹肌"),
            ("six-pack abs", "六块腹肌"),
            ("visible ribs", "可见肋骨"),
            ("chubby cheeks", "婴儿肥"),
            ("tall male", "高个男性"),
            ("hunky", "健硕男性"),
            ("aged down", "幼态化"),
            ("aged up", "成年化"),
        ],
    },
    "subject.s1.g2": {  # 年龄阶段 +4
        "adds": [
            ("toddler", "幼童"),
            ("middle-aged", "中年"),
            ("ageless", "不老容顏"),
            ("loli (absolutely not)", None),  # 占位, 查重跳过
        ],
    },
    "subject.s1.g1": {  # 人数 +7
        "adds": [
            ("2boys", "两男"),
            ("3girls", "三女"),
            ("multiple boys", "多男"),
            ("crowd", "人群"),
            ("1other", "单人(其他)"),
            ("solo focus", "单人聚焦"),
            ("0others", "无他人"),
        ],
    },
    "subject.s3": {  # 表情情绪 嘴部联动补全 +14
        "adds": [
            ("pursed lips", "抿嘴"),
            ("quivering lips", "颤抖嘴唇"),
            ("lip bite (slight)", "轻咬唇"),
            ("mouth hold", "衔物嘴"),
            ("lips parted slightly", "微启唇"),
            ("wide-eyed", "瞪眼"),
            ("puppy eyes", "可怜巴巴"),
            ("bedroom eyes", "妩媚眼"),
            ("smile with fangs", "虎牙笑"),
            ("wobbly mouth", "委屈撇嘴"),
            ("blank expression", "放空表情"),
            ("tiny frown", "微皱眉"),
            ("raised eyebrow", "挑眉"),
            ("furrowed brow", "皱眉"),
        ],
    },
    "subject.extended": {  # 身体特征 +10
        "adds": [
            ("long tongue", "长舌"),
            ("fangs", "尖牙"),
            ("vampire fangs", "吸血鬼牙"),
            ("long nails", "长指甲"),
            ("colored nails", "美甲"),
            ("black nails", "黑色美甲"),
            ("bunny tail", "兔尾"),
            ("multiple tails", "多尾"),
            ("nine tails", "九尾"),
            ("tail ornament", "尾饰"),
        ],
    },
    # ---------------- 光影氛围 补漏 ----------------
    "lighting.s2": {
        "adds": [
            ("dappled light", "斑驳光"),
            ("filtered light", "滤光"),
        ],
    },
    # ---------------- 姿势动作 补漏 ----------------
    "pose.s1": {
        "adds": [
            ("crossed legs (standing)", "交叉腿站姿"),
        ],
    },
    # ---------------- 构图 补漏 (legacy 组引用) ----------------
    "camerawork.s2": {
        "adds": [
            ("eye-level shot", "平视"),
        ],
    },
    "camerawork.s1": {
        "adds": [
            ("wide-angle panorama", "广角全景"),
        ],
    },
    # ---------------- 场景 补漏 (legacy location 组) ----------------
    "scene.s1": {
        "adds": [
            ("indoors", "室内"),
        ],
    },
    "scene.s2": {
        "adds": [
            ("outdoors", "室外"),
        ],
    },
    # ---------------- 服装 补漏 (legacy 组) ----------------
    "outfit.s4": {
        "adds": [
            ("animal ear headwear", "兽耳头饰"),
            ("mask over eyes", "眼罩"),
            ("blindfold", "蒙眼布"),
            ("eye mask", "眼贴膜"),
            ("reading glasses", "老花镜"),
            ("full color", "全彩"),
        ],
    },
    "stylemed.s1": {
        "adds": [
            ("limited palette (style)", None),  # 占位
        ],
    },
    "scene.timeweather": {
        "adds": [
            ("wet clothes", "湿衣"),
        ],
    },
    # ---------------- 人物特征 身体状态 (legacy body_wet 组) ----------------
    "subject.extended": {},
    "material.s1": {
        "adds": [
            ("oiled skin", "油光皮肤"),
            ("snow on skin", "皮肤落雪"),
            ("dirty", "脏污"),
            ("muddy", "泥污"),
        ],
    },
    "outfit.s3": {
        "adds": [
            ("wet clothes variant", None),  # 占位
        ],
    },
    "pose.s3": {
        "adds": [
            ("covering eyes with hands", "掩眼"),
            ("covering breasts", "遮挡胸口"),
        ],
    },
    "subject.s3": {
        "adds2": [],
    },
}

# 清理占位 (None zh) 条目
for sid, spec in BATCH5.items():
    if isinstance(spec, dict) and "adds" in spec:
        spec["adds"] = [a for a in spec["adds"] if a[1] is not None]
# 删除空 spec
BATCH5 = {k: v for k, v in BATCH5.items() if not (isinstance(v, dict) and not v.get("adds") and not v.get("edits") and not v.get("dels") and not v.get("moves"))}
