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
    from . import tagfiles
except ImportError:  # pragma: no cover
    import tagfiles

FLAVORS_PATH = os.path.join(tagfiles.LIBRARY_DIR, "nl_flavors.json")

_lock = None
_cache: dict | None = None
_cache_mtime: float = -1.0


def _mtime() -> float:
    try:
        return os.stat(FLAVORS_PATH).st_mtime
    except OSError:
        return 0.0


def load_flavors() -> dict:
    global _cache, _cache_mtime
    m = _mtime()
    if _cache is not None and _cache_mtime == m:
        return _cache
    try:
        with open(FLAVORS_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        _cache = {}
    _cache_mtime = m
    return _cache or {}


# count 词 → (主格, 所有格)
_PRONOUN = {
    "1girl": ("She", "her"), "1other": ("She", "their"),
    "solo": ("She", "her"),
    "1boy": ("He", "his"),
    "2girls": ("They", "their"), "3girls": ("They", "their"),
    "2boys": ("They", "their"), "3boys": ("They", "their"),
    "multiple girls": ("They", "their"), "multiple boys": ("They", "their"),
    "1girl and 1boy": ("They", "their"), "couple": ("They", "their"),
    "group": ("They", "their"), "crowd": ("They", "their"),
}
_INTRO_KEYS = ("1girl", "1boy", "2girls", "3girls", "2boys", "3boys",
               "multiple girls", "multiple boys", "1girl and 1boy", "couple",
               "group", "crowd", "solo")
# 环境词优先级 (越靠前越"有画面"), 取第一个命中的
ENV_PRIORITY = ["rain", "snowing", "thunderstorm", "cherry blossoms",
                "starry sky", "sunset", "night", "fog", "wind", "daytime",
                "rooftop", "classroom", "bedroom", "library", "beach",
                "forest", "city street"]
LIGHT_PRIORITY = ["neon", "candle", "moonlight", "window light",
                  "backlighting", "rim lighting"]
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
    out: list[str] = []

    def fill(t: str) -> str:
        t = _render_subject(t, S, not plural)
        return t.replace("{POS}", POS)

    def take(family: str, avoid_start: str = "") -> str | None:
        vs = fam.get(family)
        if not vs:
            return None
        cands = [fill(v) for v in vs]
        if avoid_start:
            alt = [c for c in cands if not c.startswith(avoid_start)]
            if alt:
                cands = alt
        return rng.choice(cands)

    # 1. 引入句 (人数词命中且有句式)
    intro = F.get("intro") or {}
    for k in _INTRO_KEYS:
        if k in ens:
            vs = intro.get(k)
            if vs:
                out.append(rng.choice(vs))
            break

    # 2. 动作句: 第一个武器束 (sub_family 表 → family)
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

    out = out[:max_sentences]
    # 句首强制大写
    out = [s[:1].upper() + s[1:] if s else s for s in out]
    return " ".join(out)
