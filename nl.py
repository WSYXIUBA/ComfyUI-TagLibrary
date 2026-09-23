"""NL 尾段编译器 (1.3.0-M3) —— 查表填空 + 反拼接三律, 热路径零 LLM。

反拼接律 (任务书 §2.5):
  1. 人称回指: 句子里用 She/Her (count 词推导), 连续句子不重念完整主语;
  2. 句式轮换: 每族 2~3 个变体, 按 seed 派生 rng 选, 换 seed 换写法;
  3. 叙事顺序: 引入(人数) → 动作(束) → 环境感知, 2~4 句收束。

数据: data/default/taglib/nl_flavors.json (管理页可编辑)
确定性: rng = Random(seed ^ 0x5EED) —— 与 tag 抽取流独立, 同 seed 同文。
"""

from __future__ import annotations

import json
import os
import random as _random

try:
    from . import datapaths, slotpolicy
except ImportError:  # pragma: no cover
    import datapaths
    import slotpolicy

FLAVORS_PATH = os.path.join(datapaths.LIBRARY_DIR, "nl_flavors.json")
# 1.8.0: NSFW flavor 扩展包 (ext 配套, 不入 git/发布)。
# families/env/light/words 同名键 → 列表拼接 (素材池扩容), 其余键 → 覆盖。
NSFW_FLAVORS_PATH = os.path.join(datapaths.LIBRARY_DIR, "nsfw_nl.json")

_cache: dict | None = None
_cache_mtime: float = -1.0


def _mtime() -> float:
    m1 = m2 = 0.0
    try:
        m1 = os.stat(FLAVORS_PATH).st_mtime
    except OSError:
        pass
    try:
        m2 = os.stat(NSFW_FLAVORS_PATH).st_mtime
    except OSError:
        pass
    return max(m1, m2)


def load_flavors() -> dict:
    global _cache, _cache_mtime
    m = _mtime()
    if _cache is not None and _cache_mtime == m:
        return _cache
    try:
        with open(FLAVORS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data = dict(data) if isinstance(data, dict) else {}
    # NSFW 扩展包并入 (缺失 = 无扩展)
    try:
        with open(NSFW_FLAVORS_PATH, "r", encoding="utf-8") as f:
            ext = json.load(f)
        if isinstance(ext, dict):
            _MERGE_LIST_KEYS = ("families", "env", "light", "words", "intro")
            for k in _MERGE_LIST_KEYS:
                if isinstance(data.get(k), dict) and isinstance(ext.get(k), dict):
                    merged = dict(data[k])
                    for fk, fv in ext[k].items():
                        if isinstance(fv, list) and isinstance(merged.get(fk), list):
                            merged[fk] = merged[fk] + fv
                        else:
                            merged[fk] = fv
                    data[k] = merged
            for k in ("pose_map", "sub_family", "obj_kind"):
                if isinstance(ext.get(k), dict):
                    data[k] = {**(data.get(k) or {}), **ext[k]}
    except (OSError, json.JSONDecodeError):
        pass
    _cache, _cache_mtime = data, m
    return data


# count 词 → (主格, 所有格)
# ⚠ 与 slotpolicy.SINGLE/MULTI_COUNT_WORDS 同步维护: 人数轴每个词都要有行,
#   否则回落 ("She","her") —— 真机实测 "large group" 群像配 "She has" 的出处。
#   quality_gate_test Q10 固化覆盖检查。
_PRONOUN = {
    "1girl": ("She", "her"), "1other": ("She", "their"),
    "solo": ("She", "her"),
    "1boy": ("He", "his"),
    "2girls": ("They", "their"), "3girls": ("They", "their"),
    "4girls": ("They", "their"), "5girls": ("They", "their"),
    "6+girls": ("They", "their"),
    "2boys": ("They", "their"), "3boys": ("They", "their"),
    "multiple girls": ("They", "their"), "multiple boys": ("They", "their"),
    "multiple others": ("They", "their"),
    "couple": ("They", "their"),
    "crowd": ("They", "their"), "everyone": ("They", "their"),
    "4boys": ("They", "their"), "5boys": ("They", "their"), "6+boys": ("They", "their"),
}
# 判定顺序 = 引入句与人称的优先级 (取第一个命中的词)
_INTRO_KEYS = ("1girl", "1boy", "1other", "solo",
               "2girls", "3girls", "4girls", "5girls",
               "6+girls", "2boys", "3boys",
               "multiple girls", "multiple boys", "multiple others",
               "couple",
               "crowd", "everyone",
               "4boys", "5boys", "6+boys")
# 环境词优先级 (越靠前越"有画面"), 取第一个命中的
ENV_PRIORITY = ["rain", "snowing", "thunderstorm", "cherry blossoms",
                "starry sky", "sunset", "night", "fog", "wind", "daytime",
                "rooftop", "classroom", "bedroom", "library", "beach",
                "forest", "city street"]
LIGHT_PRIORITY = ["neon", "candle", "moonlight", "window light",
                  "backlighting", "rim lighting"]
# 单人场景里禁用的句式关键词 —— 这些句子会把"第二个人"写进正面提示词。
# bodies/shared: "Bodies tangle together ... shared warmth" 这类复数身体句同理。
_PARTNER_HINTS = ("partner", "another", "bodies", "shared")
GAZE_MAP = {
    "looking at viewer": "gaze_front", "looking back": "gaze_back",
    "sideways glance": "gaze_side", "looking away": "gaze_side",
    "looking down": "gaze_down", "looking up": "gaze_side",
    "eye close-up": None,
}


def _pronouns(picked_ens: set) -> tuple[str, str]:
    for k in _INTRO_KEYS:
        if k in picked_ens:
            return _PRONOUN.get(k, ("She", "her"))
    return ("She", "her")


def _v3s(verb: str) -> str:
    v = verb.lower()
    if v in ("are",):
        return "is"
    if v in ("is", "was", "were", "has", "can", "will"):
        return verb
    if v.endswith(("s", "x", "ch", "sh", "o")):
        return v + "es"
    if v.endswith("y") and len(v) > 1 and v[-2] not in "aeiou":
        return v[:-1] + "ies"
    return v + "s"


_SV_RE = None  # 延迟 import 正则


def _render_subject(t: str, S: str, singular: bool) -> str:
    """模板里 {S} {verb}: 单数自动三单; 仅句首大写, 逗号/连词后小写。"""
    import re as _re
    def rep(m):
        verb = m.group(2)
        if singular:
            verb = _v3s(verb)
        start = m.start(1) == 0 or _re.search(r"[.!?]\s*$", t[:m.start(1)]) is not None
        subj = S if start else S.lower()
        return subj + " " + verb
    t = _re.sub(r"(\{S\}) (\w+)", rep, t)
    return t.replace("{S}", S)


def compile_tail(snap, picks, seed: int, *, max_sentences: int = 4,
                 want_gaze: bool = True) -> str:
    """picks (engine.Pick 列表) → 0~N 句连贯英文段落。无素材 = 空串。"""
    F = load_flavors()
    if not F:
        return ""
    fam = F.get("families") or {}
    rng = _random.Random((seed & 0xFFFFFFFF) ^ 0x5EED)
    ens = {p.en.lower() for p in picks}
    S, POS = _pronouns(ens)
    plural = S == "They"
    # 人数轴上没有多人词 = 单人场景 (判据直接来自快照的人数轴分类, 不另立词表)
    single_scene = not any(
        p.id is not None and snap.axis_arr[p.id] == "count"
        and p.en.lower() not in slotpolicy.SINGLE_COUNT_WORDS
        for p in picks)
    out: list[str] = []

    def fill(t: str) -> str:
        t = _render_subject(t, S, not plural).replace("{POS}", POS)
        # {POS}/{O} 开头的句式没有大写来源 (句首大写原来只认 {S}) → 补上, 否则
        # 渲染出 "her breath comes ragged" 这种小写开头的句子进正面提示词。
        return t[:1].upper() + t[1:] if t[:1].islower() else t

    def take(family: str, avoid_start: str = "") -> str | None:
        vs = fam.get(family)
        if not vs:
            return None
        cands = [fill(v) for v in vs]
        # 单人场景里剔掉"提第二个人"的句式 —— 实测 solo 与
        # "as she pulls her partner closer" 同框, NL 自己把第二个人写进正面提示词,
        # 和单人锁直接打架 (真机出 2girls)。判据用最终词表: 人数轴上没有多人词才算单人。
        if single_scene:
            cands = [c for c in cands
                     if not any(h in c.lower() for h in _PARTNER_HINTS)]
        if avoid_start:
            alt = [c for c in cands if not c.startswith(avoid_start)]
            if alt:
                cands = alt
        return rng.choice(cands) if cands else None

    # 1. 引入句 (人数词命中且有句式)
    intro = F.get("intro") or {}
    for k in _INTRO_KEYS:
        if k in ens:
            vs = intro.get(k)
            if vs:
                out.append(rng.choice(vs))
            break

    # 2. NSFW 场景句 (1.8.0): 任一 nsfw 词在场且句式包提供 nsfw_scene 族时插入 ——
    #    没有该族时静默跳过 (回落到下方 describe/wear 兜底, 不硬凑)
    has_nsfw = any(p.nsfw for p in picks)
    last_start = out[-1].split(" ", 1)[0] if out else ""
    if has_nsfw:
        s = take("nsfw_scene", avoid_start=last_start)
        if s:
            out.append(s)

    # 3. 动作句: 第一个武器束 (sub_family 表 → family)
    sub_fam = F.get("sub_family") or {}
    obj_kind = F.get("obj_kind") or {}
    words = F.get("words") or {}
    pose_map = F.get("pose_map") or {}
    seen_bundle: set[str] = set()
    last_start = out[-1].split(" ", 1)[0] if out else ""
    for p in picks:
        if p.kind != "ext" or p.is_extra or not p.bundle:
            continue
        pid, _, pose_id = p.bundle.partition(":")
        if pid in seen_bundle:
            continue
        seen_bundle.add(pid)
        family = (sub_fam.get(pid) or {}).get(pose_id)
        if family is None:  # 表里没有 → 用首个成员词查 pose_map
            family = pose_map.get(p.en.lower())
        if not family:
            continue
        kind = obj_kind.get(pid, "weapon")
        opool = words.get(kind) or words.get("weapon") or ["weapon"]
        O = rng.choice(opool)
        sentence = take(family, avoid_start=last_start)
        if sentence:
            out.append(sentence.replace("{O}", O))
        break  # 一段只描一个动作 (多武器时第二把靠 tag 自己说话)

    # 3. 视线句 (若动作句未含 gaze 族且命中视线词)
    if want_gaze and len(out) < max_sentences:
        last_start = out[-1].split(" ", 1)[0] if out else ""
        for e, g in GAZE_MAP.items():
            if g and e in ens:
                s = take(g, avoid_start=last_start)
                if s:
                    out.append(s)
                break

    # 4. 环境句 (命中即描, 最多一句)
    if len(out) < max_sentences:
        for k in ENV_PRIORITY:
            if k in ens:
                vs = (F.get("env") or {}).get(k)
                if vs:
                    out.append(fill(rng.choice(vs)))
                    break

    # 5. 光线句 (预算还够才加)
    if len(out) < max_sentences - 1:
        for k in LIGHT_PRIORITY:
            if k in ens:
                vs = (F.get("light") or {}).get(k)
                if vs:
                    out.append(fill(rng.choice(vs)))
                    break

    # 6. 兜底: 保证尾段至少 2 句, 且**按有无人物分流**
    #    实测(200 seed)原来 66% 只出 1 句 —— intro 只认 1girl/1boy, 动作句只认武器束,
    #    环境/光线句又只认少数关键词。而 Anima 官方明确"纯自然语言至少 2 句, 太短会
    #    给出意外结果"。另外 "no humans" 时不能再写人 (会产出 "She has ..." 这种矛盾)。
    if len(out) < 2 and fam:
        def _human(w) -> str:
            return str(w).replace("_", " ")

        def _agree(sent: str) -> str:
            """主谓一致: {S} 可能是 She/He(单) 或 They(复)。"""
            if not plural:
                return sent
            return sent.replace(" has ", " have ").replace(" is ", " are ")

        no_human = any(str(p.en).strip().lower() == "no humans" for p in picks)
        app = [_human(p.en) for p in picks
               if p.axis == "appearance" and 0 < len(p.en.split()) <= 4][:2]
        wear = [_human(p.en) for p in picks
                if p.axis == "clothing" and 0 < len(p.en.split()) <= 4][:2]
        env = [_human(p.en) for p in picks
               if p.axis in ("environment", "material") and 0 < len(p.en.split()) <= 4][:2]

        queue: list[tuple] = []
        if no_human or (not app and not wear):
            queue.append(("scene", "E1", env[0] if env else "the whole frame"))
        if app:
            queue.append(("describe", "A", " and ".join(app)))
        if wear:
            queue.append(("wear", "C", " and ".join(wear)))
        if not queue:
            queue.append(("describe", "A", "a striking presence"))
        for family, ph, val in queue:
            if len(out) >= 2:
                break
            tpl = rng.choice(fam.get(family) or ["{S} has {A}."])
            out.append(_agree(fill(tpl).replace("{" + ph + "}", val)))
        # 仍不足 (例如补完一句后素材用尽) -> 再补场景句, 有界
        guard = 0
        while len(out) < 2 and guard < 3:
            guard += 1
            tpl = rng.choice(fam.get("scene") or ["{E1} fills the frame."])
            cand = tpl.replace("{E1}", env[guard % max(len(env), 1)] if env else "the whole frame")
            if cand not in out:
                out.append(cand)

    out = out[:max_sentences]
    # 句首强制大写
    out = [s[:1].upper() + s[1:] if s else s for s in out]
    return " ".join(out)
