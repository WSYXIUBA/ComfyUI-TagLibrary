"""1.8.0 路由: 场景预设 / 批量抽取探索器 / 分轴重摇 / Prompt 吸收器。

设计要点:
  - 预设 = 命名的「半状态」(钉选词 + 排除 + 槽位配额 + 随机配置), 约束不锁死;
    出厂示例存 taglib/presets.json (SFW), 用户预设存用户库 settings.presets。
  - draw_batch 与节点执行同一 run_auto 路径, 确定性一致 (同 seed 同文)。
  - draw_reroll 语义: 保留词转钉选 (pin_ignore_exclude 豁免排除), 其余轴全部排除,
    只让目标轴重新出生 —— 引擎零改动的"局部重摇"。
  - absorb 纯查表: 分词 → en/alias/归一化匹配, 不猜。
"""

from __future__ import annotations

import json
import os
import re

from aiohttp import web

from .. import library
from .. import runtime_snapshot
from .. import nl as _nl
from .. import engine as _engine
from .. import axes as _axes
from ._common import _json_response

PRESETS_PATH = os.path.join(library.DEFAULT_DATA_DIR, "taglib", "presets.json")

_WEIGHT_RE = re.compile(r"^\((.+):[0-9.]+\)$")


def _norm_token(tok: str) -> str:
    """单词条归一化: 去权重语法 / 下划线转空格 / 压空白。"""
    t = str(tok or "").strip()
    t = _WEIGHT_RE.match(t).group(1) if _WEIGHT_RE.match(t) else t
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip().lower().lstrip("@")
    return t


def _assemble_text(snap, res, seed: int, state: dict) -> str:
    """与 nodes._build_auto 同口径的文本拼装 (批量预览 = 排队实出)。"""
    sep = ", " if state.get("separator", "comma") != "space" else " "
    use_w = bool(state.get("use_weights_syntax", False))
    tags: list[str] = []
    for p in res.picks:
        t = _engine._artist_text(p.en, p.axis) if hasattr(_engine, "_artist_text") else p.en
        w = float(p.weight or 1.0)
        if use_w and abs(w - 1.0) > 1e-6:
            t = f"({t}:{w:g})"
        tags.append(t)
    if state.get("dedupe", True) is not False:
        seen: set[str] = set()
        uniq = []
        for t in tags:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        tags = uniq
    text = sep.join(tags)
    if state.get("nl_tail", True):
        tail = _nl.compile_tail(snap, res.picks, seed)
        if tail:
            if text and not text.endswith((".", "!", "?")):
                text = text + ". " + tail
            elif text:
                text = text + " " + tail
            else:
                text = tail
    return text


def _run_draw(snap, state: dict, seed: int):
    nsfw_on = bool(state.get("nsfw", False))
    lib = library.get_merged()
    cfg = _engine.resolve_config(state, lib.get("settings") or {})
    try:
        cw = json.loads(state.get("category_weights") or "{}")
    except Exception:  # noqa: BLE001
        cw = None
    return _engine.run_auto(snap, state, seed, nsfw_on=nsfw_on,
                            avoid_conflicts=bool(state.get("avoid_conflicts", True)),
                            search_text=str(state.get("search_text") or ""),
                            cat_weights=cw if isinstance(cw, dict) else None,
                            config=cfg)


def _picks_payload(snap, res) -> list[dict]:
    return [{"en": p.en, "zh": p.zh, "cat": p.cat, "axis": p.axis,
             "src": p.source, "nsfw": p.nsfw, "gender": p.gender}
            for p in res.picks]


# ---------------------------------------------------------------- presets

async def get_presets(_request: web.Request) -> web.Response:
    """GET /taglib/api/presets -> {factory: [...], user: [...]}。"""
    factory: list = []
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            factory = json.load(f).get("presets") or []
    except (OSError, ValueError):
        factory = []
    user = (library.get_merged().get("settings") or {}).get("presets") or []
    return _json_response({"ok": True, "factory": factory, "user": user})


# ---------------------------------------------------------------- draw batch

async def draw_batch(request: web.Request) -> web.Response:
    """POST /taglib/api/draw_batch {state, seed_base, n} -> n 条完整 prompt 网格。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    try:
        seed_base = int(payload.get("seed_base", 0)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        seed_base = 0
    try:
        n = max(1, min(int(payload.get("n", 12)), 40))
    except (TypeError, ValueError):
        n = 12
    lib = library.get_merged()
    snap = runtime_snapshot.get_snapshot(lib)
    out = []
    for i in range(n):
        seed = (seed_base + i) & 0xFFFFFFFF
        res = _run_draw(snap, state, seed)
        out.append({"seed": seed, "text": _assemble_text(snap, res, seed, state),
                    "words": [p.en for p in res.picks]})
    return _json_response({"ok": True, "items": out})


# ---------------------------------------------------------------- reroll axes

async def draw_reroll(request: web.Request) -> web.Response:
    """POST /taglib/api/draw_reroll {state, seed, axes:[轴名], keep_words:[en]}

    保留词转钉选 (pin_ignore_exclude 豁免"排除其余轴"), 其余轴全排除 → 只有
    目标轴重新出生。返回新 picks + 拼好的文本。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    state = dict(payload.get("state") or {})
    axes_want = {str(a) for a in (payload.get("axes") or [])}
    keep = [str(w) for w in (payload.get("keep_words") or []) if str(w).strip()]
    if not axes_want:
        return _json_response({"ok": False, "error": "axes 为空"}, 400)
    try:
        seed = int(payload.get("seed", 0)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        seed = 0
    lib = library.get_merged()
    snap = runtime_snapshot.get_snapshot(lib)
    all_axes = [_axes.AXIS_NAME_ZH[a] for a in _axes.AXIS_ORDER]
    exclude = [a for a in all_axes if a not in axes_want]
    # 用户已有排除只保留与目标轴相关的槽位级条目 (轴级会被上面的全轴排除覆盖)
    for e in (state.get("exclude_categories") or []):
        e = str(e)
        if "/" in e and e.split("/", 1)[0] in axes_want:
            exclude.append(e)
    keep_state = dict(state)
    keep_state["exclude_categories"] = list(dict.fromkeys(exclude))
    keep_state["tags"] = [{"en": w, "pinned": True} for w in keep]
    keep_state.pop("pinned", None)
    keep_state["pin_ignore_exclude"] = True
    res = _run_draw(snap, keep_state, seed)
    return _json_response({"ok": True, "seed": seed,
                           "picks": _picks_payload(snap, res),
                           "text": _assemble_text(snap, res, seed, keep_state)})


# ---------------------------------------------------------------- absorb

async def absorb(request: web.Request) -> web.Response:
    """POST /taglib/api/absorb {text} -> {matched, unmatched}

    matched: [{en, zh, cat, axis, tid, raw}] —— 库内命中 (en / alias / 归一化)
    unmatched: [{raw, norm}] —— 库外词, 前端走收件箱归位
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    text = str(payload.get("text") or "")
    if not text.strip():
        return _json_response({"ok": True, "matched": [], "unmatched": []})
    lib = library.get_merged()
    snap = runtime_snapshot.get_snapshot(lib)

    # 别名索引 (编译一次, 按 snap 身份缓存)
    global _alias_cache
    if _alias_cache is None or _alias_cache[0] is not snap:
        amap: dict[str, int] = {}
        for i, als in enumerate(snap.tag_aliases):
            if als:
                for a in als:
                    amap.setdefault(str(a).strip().lower(), i)
        _alias_cache = (snap, amap)
    amap = _alias_cache[1]

    raw_tokens = [t.strip() for t in re.split(r"[,\n]+", text) if t.strip()]
    matched, unmatched, seen = [], [], set()
    for raw in raw_tokens:
        norm = _norm_token(_WEIGHT_RE.sub(r"\1", raw) if _WEIGHT_RE.match(raw.strip()) else raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        tid = snap.en_to_id.get(norm)
        if tid is None:
            tid = amap.get(norm)
        if tid is not None:
            si = snap.sub_of[tid]
            matched.append({"en": snap.tag_text[tid], "zh": snap.tag_zh[tid],
                            "cat": snap.cat_names[snap.cat_of_sub[si]],
                            "axis": snap.axis_arr[tid], "tid": tid, "raw": raw})
        else:
            unmatched.append({"raw": raw, "norm": norm})
    return _json_response({"ok": True, "matched": matched, "unmatched": unmatched})


_alias_cache: tuple | None = None


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "tag"


async def absorb_add(request: web.Request) -> web.Response:
    """POST /taglib/api/absorb_add {tags:[{en, zh?, cat, sub, nsfw?}]}

    吸收器收件箱 → 归位入库: 在合并库上追加新词后整树保存用户库
    (与管理页保存同语义, payload ⊇ 底座 → 不产生墓碑)。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    items = payload.get("tags")
    if not isinstance(items, list) or not items:
        return _json_response({"ok": False, "error": "tags 必须是非空数组"}, 400)
    merged = json.loads(json.dumps(library.get_merged()))
    merged.pop("_meta", None)
    # 全库 en 索引 (跨库去重)
    all_en = set()
    index: dict[tuple, dict] = {}
    for c in merged.get("categories", []):
        for s in c.get("subcategories", []):
            index[(c.get("name"), s.get("name"))] = s
            for t in s.get("tags", []):
                all_en.add(str(t.get("en") or "").lower())
    from .. import axes as _axes_mod  # noqa: PLC0415 (路由内延迟导入, 与包内约定一致)
    added, skipped = [], []
    for it in items:
        en = str(it.get("en") or "").strip()
        cat, sub = str(it.get("cat") or ""), str(it.get("sub") or "")
        if not en or not cat or not sub:
            skipped.append({"en": en, "why": "缺少词/槽位"})
            continue
        if en.lower() in all_en:
            skipped.append({"en": en, "why": "库内已存在"})
            continue
        target = index.get((cat, sub))
        if target is None:
            skipped.append({"en": en, "why": f"槽位不存在: {cat}/{sub}"})
            continue
        nsfw = bool(it.get("nsfw", False))
        tag = {
            "en": en, "zh": str(it.get("zh") or ""), "aliases": [],
            "weight": 1.0, "enabled": True, "nsfw": nsfw,
            "id": f"{target.get('id')}.{_slug(en)}", "type": "content",
            "priority": 50, "rarity": "common", "groups": [], "requires": [],
            "mutex_with": [], "desc": "absorb 收录", "meta": {}, "gender": "",
            "axis": _axes_mod.axis_of(cat, sub)[0], "facet": cat,
        }
        if nsfw:
            tag["minor_block"] = True
        target.setdefault("tags", []).append(tag)
        all_en.add(en.lower())
        added.append({"en": en, "cat": cat, "sub": sub})
    if added:
        library.save_user_library(merged)
        runtime_snapshot.invalidate_snapshot()
    return _json_response({"ok": True, "added": added, "skipped": skipped})
