"""标签派生与就地编辑支持 (2026-09-19 编辑体验改造)。

## 为什么有这个模块

每条标签带 **19 个字段**，而真正需要人工判断的"行为属性"（手数 / 视线 / 状态槽 /
穿戴词 / 互斥域 / 句式族）**不存在标签上**，而是散落在 4 个独立侧表:

    tag_library.json      标签本体 (en/zh/weight/type/priority/rarity/...)
    profiles.json         武器/物品档案 → 每条含 tags[] + poses[] + extras[],
                          条目上挂 hands / gaze / state_slot / implies / nl
    grouprules.json       互斥域 (同域成员互斥)
    nl_flavors.json       句式族 + pose_map (动作词 → 族)

于是"加一个标签"要跨 4 个页面登记 4 次 —— 这是编辑体验差的根因。

本模块把这件事收敛成 **一次推导**:

  - `derive_tag()`      只给 (en, zh, 槽位) → 一条完整标签 + 该补的侧表建议
  - `suggest_profile()` 词形 → 该归入哪个档案 (以 profiles.json 实际成员为准)
  - `incomplete_report()` 反查"哪些标签的行为属性还没登记", 让前端能汇成一个角标

⚠ 本模块**只推导与报告, 不改引擎行为**。推导出的标签一律经 `schema.migrate_tag`
   归一, 保证与既有数据字段口径完全一致 (19 字段的默认值本来就在 migrate 里)。

## 两个数据来源的优先级

1. **profiles.json 的实际成员** —— 真源。已登记的词一律以此为准 (零重复维护)。
2. **`FALLBACK_KEYWORDS`** —— 只兜"库里还没登记、但一眼能归类"的常见词形。
   命中即给建议, 不命中就不猜 (宁可留空也不猜错)。
"""

from __future__ import annotations

import os
import re

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import axes
    from . import schema
except ImportError:  # pragma: no cover
    import axes
    import schema


# ---------------------------------------------------------------- 词形关键词

# 兜底归类表: 命中 → 建议归入该档案 id。
# 已登记在 profiles.json 里的词**不走这里** (见 suggest_profile 的先后顺序)。
FALLBACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "weapon.katana":    ("wakizashi", "tachi", "nodachi", "katana sheath"),
    "weapon.sword":     ("knife", "blade", "longsword", "short sword", "broadsword",
                         "fencing sword", "cleaver", "shiv", "kukri", "machete"),
    "weapon.greatsword": ("zweihander", "maul", "poleaxe"),
    "weapon.gun":       ("handgun", "smg", "carbine", "machine gun", "flamethrower",
                         "sniper scope", "laser pistol", "energy gun"),
    "weapon.bow":       ("longbow", "recurve bow", "arrow", "quiver"),
    "weapon.staff":     ("wand", "scepter", "censer"),
    "weapon.polearm":   ("glaive", "lance", "pike", "war scythe"),
    "weapon.shield":    ("shield", "buckler", "tower shield", "riot shield", "shield bash"),
    "obj.umbrella":     ("parasol",),
    "obj.book":         ("tome", "ledger", "diary"),
    "obj.cup":          ("mug", "tumbler", "goblet", "flask"),
    "obj.phone":        ("tablet", "flip phone"),
    "obj.camera":       ("camcorder", "webcam"),
    "obj.optics":       ("monocular", "periscope", "magnifying glass"),
    "obj.flower":       ("tulip", "sunflower", "carnation"),
    "obj.guitar":       ("ukulele", "lute", "banjo"),
}

# 手持动词 → 状态槽建议值。状态槽名由档案 id 推出 (weapon_state / obj_state)。
HOLD_VERBS: dict[str, str] = {
    "holding": "held",
    "wielding": "held",
    "gripping": "held",
    "carrying": "held",
    "drawing": "drawn",
    "unsheathing": "drawn",
    "sheathing": "sheathed",
    "sheathed": "sheathed",
    "aiming": "aimed",
    "raised": "raised",
}

# 双手占用的词形 (资源账本 hands 上限 2, 见 profiles.BODY_RESOURCES)
TWO_HANDED_HINTS: frozenset[str] = frozenset({
    "greatsword", "claymore", "war hammer", "battle axe", "axe", "mace", "flail",
    "chainsaw", "rifle", "assault rifle", "shotgun", "submachine gun", "sniper rifle",
    "plasma rifle", "rocket launcher", "spear", "naginata", "halberd", "trident",
    "bow (weapon)", "compound bow", "crossbow", "scythe", "two-handed sword",
})

# 单手占用的词形 (1 只手)
ONE_HANDED_HINTS: frozenset[str] = frozenset({
    "sword", "rapier", "dagger", "kunai", "pistol", "revolver", "gun", "magic wand",
    "lightsaber", "energy sword", "katana", "odachi", "shuriken", "wand", "smg",
})

# 占视线 (gaze=1) 的动作词形
GAZE_HINTS: frozenset[str] = frozenset({
    "looking at viewer", "looking away", "looking up", "looking down", "looking back",
    "eye contact", "staring", "sideways glance", "over shoulder",
})

_RE_NON_WORD = re.compile(r"[^a-z0-9\- ]+")


def normalize(text: str) -> str:
    """词形归一: 小写 + 去非法字符 + 压空白。用于关键词匹配。"""
    s = _RE_NON_WORD.sub(" ", str(text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _singular(word: str) -> str:
    """轻量单复数还原 (只处理英语最常见的几种规则)。

    -ves 必须单独处理: knives→knife / wolves→wolf / shelves→shelf。
    漏了它会让 `throwing knives` 还原成 `knive` 而匹配不到 `knife`。
    """
    if word.endswith("ves") and len(word) > 4:
        return word[:-3] + "f"          # wolves → wolf
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"          # berries → berry
    if word.endswith(("ses", "xes", "zes", "ches", "shes")) and len(word) > 4:
        return word[:-2]                # boxes → box / dishes → dish
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]                # swords → sword
    return word


def _forms(text: str) -> set[str]:
    """归一后的词 + 单数形式 (词形匹配用它, 避免 `throwing knives` 落空)。

    -ves 类额外补一个 `-fe` 形式 (knives → knife), 因为 `_singular` 只给得出 `-f`。
    """
    out: set[str] = set()
    whole = normalize(text)
    if whole:
        out.add(whole)
        out.add(_singular(whole))
    for w in whole.split() if whole else []:
        out.add(w)
        s = _singular(w)
        if s != w:
            out.add(s)
            if w.endswith("ves"):
                out.add(w[:-3] + "fe")   # knives → knife
    return out


# ---------------------------------------------------------------- 档案建议


_PIDX: tuple[float, list] | None = None
_SUGGEST: dict[str, dict | None] = {}


def _profile_index() -> list[tuple[str, str, list[str]]]:
    """读 profiles.json → [(pid, zh, [成员词...]), ...]。

    ⚠ **必须按 mtime 缓存**。这个函数以前每次调用都读盘 + 解析 JSON, 而
    `suggest_profile` 会为**每个标签**调它一次 —— `incomplete_report` 扫一支
    293 个词的轴就是 293 次读盘。实测这让 `/taglib/api/tag/incomplete` 从
    应有的几毫秒涨到 **697ms**, 而且它在 aiohttp 事件循环里同步跑, 等于把
    整个 ComfyUI 的 HTTP 服务 (含节点 build) 一起堵住。

    缓存键只取 profiles.json 的 mtime —— 它变了就重读。
    """
    global _PIDX
    try:
        try:
            from . import profiles as _profiles
        except ImportError:  # pragma: no cover
            import profiles as _profiles
        try:
            mt = os.path.getmtime(_profiles.PROFILES_PATH)
        except OSError:
            mt = 0.0
        if _PIDX is not None and _PIDX[0] == mt:
            return _PIDX[1]
        out: list[tuple[str, str, list[str]]] = []
        for p in _profiles.load_profiles().get("profiles") or []:
            pid = str(p.get("id") or "").strip()
            if not pid:
                continue
            members = {normalize(t) for t in (p.get("tags") or []) if str(t).strip()}
            out.append((pid, str(p.get("zh") or ""), sorted(members)))
        _PIDX = (mt, out)
        _SUGGEST.clear()
        return out
    except Exception:  # noqa: BLE001
        # 侧表读失败 → 退化为"不猜", 绝不让读表失败挡住主流程
        return []


def suggest_profile(en: str) -> dict | None:
    """词形 → 建议归入的档案。

    返回 {"id", "zh", "registered", "new", "reason"} 或 None (不猜)。
      - `registered=True` 该词**已是**某档案成员 → 无需登记, 前端显示为已就绪
      - `new=True`        建议的档案 id **尚不存在** → 需要一并新建档案
    """
    forms = _forms(en)
    if not forms:
        return None
    index = _profile_index()
    ids = {pid for pid, _, _ in index}

    # 1) 以 profiles.json 实际成员为准 (精确命中优先于包含命中)
    for pid, zh, members in index:
        if forms & set(members):
            return {"id": pid, "zh": zh, "registered": True, "new": False,
                    "reason": f"已是「{zh or pid}」成员"}
    for pid, zh, members in index:
        for m in members:
            if m and any(f == m or f.startswith(m + " ") or f.endswith(" " + m)
                         for f in forms):
                # 词形包含: "dual swords" 含 "sword" / "sniper rifle" 含 "rifle"
                return {"id": pid, "zh": zh, "registered": False, "new": False,
                        "reason": f"词形接近「{zh or pid}」成员 {m}"}

    # 2) 兜底关键词表 (只兜"库里还没登记、但一眼能归类"的常见词形)
    zh_of = {pid: zh for pid, zh, _ in index}
    for pid, kws in FALLBACK_KEYWORDS.items():
        for kw in kws:
            if any(f == kw or f.startswith(kw + " ") or f.endswith(" " + kw) for f in forms):
                exists = pid in ids
                return {"id": pid, "zh": zh_of.get(pid, ""), "registered": False,
                        "new": not exists,
                        "reason": (f"词形命中 {kw}" if exists
                                   else f"词形命中 {kw}, 建议新建档案")}
    return None


def suggest_entry(en: str, zh: str = "", *, profile_id: str = "") -> dict:
    """词形 → 建议的档案条目 (hands / gaze / state_slot / id)。

    只给"不猜也能定"的项: 手数按词形、视线按词形、状态槽按手持动词。
    推不出的项一律留 0 / 空, 由用户在属性卡里补 —— **不编造默认值**。
    """
    forms = _forms(en)
    word = normalize(en)
    hands = 0
    if forms & TWO_HANDED_HINTS:
        hands = 2
    elif forms & ONE_HANDED_HINTS:
        hands = 1
    gaze = 1 if forms & GAZE_HINTS else 0

    state_slot: dict[str, str] = {}
    if profile_id:
        ns = ("weapon_state" if profile_id.startswith("weapon.")
              else "obj_state" if profile_id.startswith("obj.") else "")
        if ns:
            for verb, value in HOLD_VERBS.items():
                if word.startswith(verb + " ") or word == verb:
                    state_slot = {ns: value}
                    break

    eid = schema.slug(f"{profile_id.split('.')[-1] if profile_id else 'entry'}-{word}", "entry")
    return {
        "id": eid,
        "zh": zh or "",
        "tags": [word] if word else [],
        "hands": hands,
        "gaze": gaze,
        "state_slot": state_slot,
    }


# ---------------------------------------------------------------- 标签派生


def derive_tag(en: str, zh: str, axis: str, slot_name: str,
               *, sub_id: str = "") -> tuple[dict, dict]:
    """(en, zh, 轴, 槽位名) → (完整标签, 侧表建议)。

    标签的 19 个字段全部由 `schema.migrate_tag` 归一补齐 (与既有数据同一口径),
    这里只负责 id 与轴/槽位归属。**用户永远只需要填 en / 中文 / 槽位三项。**

    `sub_id` = 槽位的存储 id (形如 `道具武器.武器装备`), 用于生成标签 id;
    留空则交给 `schema.migrate_subcategory` 的兜底规则生成。
    """
    word = normalize(en)
    if not word:
        raise ValueError("en 不能为空")

    tag: dict = {"en": word, "zh": str(zh or "").strip()}
    # id 兜底规则与 schema.migrate_subcategory 完全一致, 避免二次迁移时换 id。
    # 没给 sub_id 时用 `轴.槽位名` 合成一个, 保证预览也总是有 id 可回填。
    key = sub_id or f"{axis}.{schema.slug(slot_name, 'slot')}"
    tag["id"] = f"{key}.{re.sub(r'\s+', '-', word)}"
    # 轴/槽位归属靠"槽位名"表达 —— migrate_tag 是按 分类名/子分类名 路径推 axis 的
    tag = schema.migrate_tag(tag, axes.AXIS_NAME_ZH.get(axis, ""), slot_name)

    prof = suggest_profile(word)
    needs = _needs_of(axis, prof)
    # 只有在"确实需要新登记"时才给条目建议; 已建档的词给了反而是噪音
    entry = None
    if prof and not prof.get("registered"):
        entry = suggest_entry(word, tag.get("zh", ""), profile_id=prof.get("id", ""))
    hints: dict = {
        "profile": prof,
        "entry": entry,
        "axis": axis,
        "slot": slot_name,
        "needs": needs,
    }
    return tag, hints


def _needs_of(axis: str, prof: dict | None) -> list[str]:
    """这条标签"还需要登记什么"的人类可读清单 (前端角标用)。"""
    needs: list[str] = []
    if axis == "prop" and prof and not prof.get("registered"):
        target = prof.get("zh") or prof.get("id")
        needs.append(f"新建武器档案「{target}」" if prof.get("new")
                     else f"登记进武器档案「{target}」")
    if axis == "action":
        needs.append("登记句式族 (NL 句式页)")
    return needs


# ---------------------------------------------------------------- 待完善报告


def incomplete_report(lib: dict, limit: int = 500) -> dict:
    """扫全库, 汇总"行为属性还缺"的登记项 —— 让前端把待办收成一个角标。

    只报三类**可判定**的缺口, 不做模糊猜测:
      1. `weapon_unregistered`  prop 轴、词形能归类、但不在任何档案成员里
                                (这类词抽出来时带不出姿势/手数, 是真实缺口)
      2. `dangling_ref`         档案 / 互斥域 / 句式表里引用了、但库里不存在的词
                                (陈旧登记会让规则静默失效, 最难自查)
      3. `pose_no_family`       档案姿势词没进 nl 的 pose_map
                                (口径与 GET /taglib/api/nl 的 uncovered 一致)
    """
    profiles = _profile_index()
    registered: set[str] = set()
    for _, _, members in profiles:
        registered.update(members)

    def _in_registered(word: str) -> bool:
        return bool(_forms(word) & registered)

    weapon_unregistered: list[dict] = []
    all_words: set[str] = set()
    for cat in lib.get("categories", []):
        aid = axes.AXIS_ZH_TO_ID.get(cat.get("name", ""), "")
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []) or []:
                en = normalize(t.get("en", ""))
                if not en:
                    continue
                all_words |= _forms(t.get("en", ""))
                if aid == "prop" and not _in_registered(en) and suggest_profile(en):
                    weapon_unregistered.append({"id": t.get("id"), "en": t.get("en"),
                                                "zh": t.get("zh", ""),
                                                "slot": sub.get("name", "")})

    # ---- 陈旧引用: 档案成员 / 互斥域成员 / 句式族映射键 → 库里没有 ----
    dangling: list[dict] = []
    for pid, zh, members in profiles:
        for m in members:
            if m and m not in all_words:
                dangling.append({"ref": m, "from": f"武器档案「{zh or pid}」", "kind": "profile"})
    pose_words: set[str] = set()
    try:
        try:
            from . import grouprules as _gr
        except ImportError:  # pragma: no cover
            import grouprules as _gr
        for g in _gr.load_grouprules():
            for m in g.get("members") or []:
                if normalize(m) not in all_words:
                    dangling.append({"ref": str(m), "from": f"互斥域「{g.get('id')}」",
                                     "kind": "grouprules"})
    except Exception:  # noqa: BLE001
        pass
    try:
        try:
            from . import profiles as _profiles
        except ImportError:  # pragma: no cover
            import profiles as _profiles
        for p in _profiles.load_profiles().get("profiles") or []:
            for e in (p.get("poses") or []) + (p.get("extras") or []):
                pose_words |= {normalize(x) for x in (e.get("tags") or [])}
    except Exception:  # noqa: BLE001
        pass

    # ---- 姿势词 vs nl pose_map ----
    no_family: list[dict] = []
    try:
        try:
            from . import nl as _nl
        except ImportError:  # pragma: no cover
            import nl as _nl
        flavors = _nl.load_flavors()
        pose_map = {normalize(k) for k in (flavors.get("pose_map") or {})}
        for k in (flavors.get("pose_map") or {}):
            if normalize(k) not in all_words:
                dangling.append({"ref": str(k), "from": "NL 句式 pose_map", "kind": "nl"})
        for w in sorted(pose_words):
            if w and w not in pose_map:
                no_family.append({"en": w})
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "total": len(weapon_unregistered) + len(dangling) + len(no_family),
        "weapon_unregistered": weapon_unregistered[:limit],
        "dangling_ref": dangling[:limit],
        "pose_no_family": no_family[:limit],
        "counts": {
            "weapon_unregistered": len(weapon_unregistered),
            "dangling_ref": len(dangling),
            "pose_no_family": len(no_family),
        },
    }
