# -*- coding: utf-8 -*-
"""阶段6扩库数据 —— 批次6: 收尾扩 (角色定位/亲属关系/职业性别域 + 各类补充)。

gender 字段: ("en","zh","female"/"male"/None)
只打绝对性别专属词。
"""

BATCH6 = {
    # ---------------- 人物主体/年龄阶段 (性别基础词) ----------------
    "subject.s1.g2": {
        "adds": [
            ("middle-aged woman", "中年女性", "female"),
            ("middle-aged man", "中年男性", "male"),
            ("elderly man", "老年男性", "male"),
            ("granny", "老奶奶", "female"),
            ("grandfather", "祖父", "male"),
            ("grandmother", "祖母", "female"),
            (" idols", None, None),
        ],
    },
    # ---------------- 人物主体/人数 ----------------
    "subject.s1.g1": {
        "adds": [
            ("1girl solo", None, None),  # 占位 (查重跳过)
            ("multiple women", "多女", "female"),
            ("multiple men", "多男", "male"),
        ],
    },
    # ---------------- 人物主体/体型 ----------------
    "subject.s2.g3": {
        "adds": [
            ("beard", "胡须", "male"),
            ("mustache", "小胡子", "male"),
            ("goatee", "山羊胡", "male"),
            ("stubble", "胡茬", "male"),
            ("deep voice vibes", None, None),
        ],
    },
    # ---------------- 服装 (性别专属类) ----------------
    "outfit.s3": {
        "adds": [
            ("prince outfit", "王子装", "male"),
            ("butler outfit", "执事装", "male"),
            ("businesswoman attire", "职业女性套装", "female"),
            ("bride outfit", "新娘婚纱", "female"),
            ("groom outfit", "新郎礼服", "male"),
            ("ball gown", "舞会礼服", "female"),
        ],
    },
    "outfit.s1": {
        "adds": [
            ("henley shirt", "亨利衫", None),
            ("sailor top", "水手服上衣", None),
        ],
    },
    # ---------------- 姿势补充 ----------------
    "pose.s1": {
        "adds": [
            ("leg lock", "锁腿坐"),
            ("leg hug", "抱腿"),
            ("head in lap", "枕膝"),
            ("lap pillow", "膝枕(被枕)"),
            ("arm over shoulder", "搭肩"),
            ("embrace", "相拥"),
            ("back to back", "背靠背"),
            ("forehead touch", "额头相抵"),
            ("nose to nose", "鼻尖相触"),
            ("hand on own stomach", "手抚腹"),
            ("sleeping upright", "坐着睡"),
            ("cat pose", "猫式伸展"),
        ],
    },
    # ---------------- 表情补充 ----------------
    "subject.s3": {
        "adds": [
            ("half-open mouth", "半张嘴"),
            ("agape", "张嘴惊愕"),
            ("content smile", "满足的笑"),
            ("beaming", "眉开眼笑"),
            ("sneer", "冷笑"),
            ("gloomy face", "阴沉脸"),
            ("scowl", "怒容"),
            ("wide smile", "大笑颜"),
            ("small smile", "浅笑"),
            ("flat gaze", "无神凝视"),
            ("sparkle eyes smile", "亮眼笑容"),
            ("looking very happy", None),  # 占位
        ],
    },
    # ---------------- 场景补充 (职业/学校类) ----------------
    "scene.s1": {
        "adds": [
            ("infirmary", "医务室"),
            ("principal office", "校长室"),
            ("art room", "美术教室"),
            ("chemistry lab", "化学实验室"),
            ("music room", "音乐教室"),
            ("cafeteria", "食堂"),
            ("gym storage room", "器材室"),
            ("rooftop fence", "天台围栏"),
            ("shrine office", "社务所"),
            ("bathhouse", "澡堂"),
        ],
    },
    # ---------------- 光影/氛围补充 ----------------
    "lighting.s3": {
        "adds": [
            ("healing atmosphere", "治愈感"),
            ("gentle atmosphere", "温柔氛围"),
            ("wild atmosphere", "狂野氛围"),
            ("royal atmosphere", "华丽感"),
            ("minimalist mood", "极简感"),
        ],
    },
    "lighting.s1": {
        "adds": [
            ("car headlights", "车头灯"),
            ("screen glow", "屏幕光"),
            ("phone screen light", "手机屏光"),
            ("fireworks glow", "烟花光"),
            ("aurora light", "极光"),
        ],
    },
    # ---------------- 材质补充 ----------------
    "material.s1": {
        "adds": [
            ("neon material", "霓虹材质"),
            ("hologram", "全息投影"),
            ("smoke texture", "烟雾质感"),
            ("liquid gold", "液态黄金"),
            ("black silk", "黑丝绸"),
            ("white lace", "白色蕾丝"),
        ],
    },
}

# 清理 None 占位
for sid, spec in BATCH6.items():
    if "adds" in spec:
        spec["adds"] = [a for a in spec["adds"] if a[1] is not None]
BATCH6 = {k: v for k, v in BATCH6.items() if v.get("adds") or v.get("edits") or v.get("dels") or v.get("moves")}
