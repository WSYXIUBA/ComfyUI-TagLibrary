"""1.3.0 路由: 武器档案 / 互斥域 / NL 句式 / 服务端抽取。"""

from __future__ import annotations

import json
import os
import time

from aiohttp import web

from .. import library
from .. import tagfiles
from .. import tagconflicts
from .. import runtime_snapshot
from .. import profiles as _profiles
from .. import grouprules as _grouprules
from .. import nl as _nl
from .. import engine as _engine
from ._common import (
    _WEB_DIR, BACKUP_DIR, FACTORY_BACKUP_PATH, USER_BACKUP_PATH,
    UPGRADE_PROMPT_PATH, LEGACY_BACKUP_PATH, _json_response, _mirror_folder,
)


async def get_profiles(_request: web.Request) -> web.Response:
    """GET /taglib/api/profiles -> profiles.json 原文 + 校验/挂载诊断 + 词中文对照。"""
    data = _profiles.load_profiles()
    valid, errs = _profiles.validate_profiles(data)
    snap = runtime_snapshot.get_snapshot(library.get_merged())
    diag = []
    langmap = {}
    for p in data.get("profiles") or []:
        tags = [str(t).strip() for t in (p.get("tags") or [])]
        miss = [t for t in tags if snap.tag_id(t) is None]
        n_pose = sum(1 for x in tags if snap.tag_id(x) is not None)
        diag.append({"id": p.get("id"), "zh": p.get("zh", ""), "mount_ok": n_pose,
                     "mount_total": len(tags), "missing": miss,
                     "poses": len(p.get("poses") or []),
                     "extras": len(p.get("extras") or [])})
        for x in (p.get("poses") or []) + (p.get("extras") or []):
            xzh = str(x.get("zh") or "")
            for t in (x.get("tags") or []):
                tl = str(t).strip().lower()
                if tl not in langmap:
                    tid = snap.tag_id(tl)
                    langmap[tl] = (snap.tag_zh[tid] if tid is not None else "") or xzh
        for t in tags:
            tl = t.lower()
            if tl not in langmap:
                tid = snap.tag_id(tl)
                if tid is not None:
                    langmap[tl] = snap.tag_zh[tid]
    return _json_response({"ok": True, "data": data, "errors": errs, "diag": diag,
                           "weapon_poses": sorted(snap.tag_text[i] for i in snap.bundled_only),
                           "lang": langmap})


async def save_profiles(request: web.Request) -> web.Response:
    """POST /taglib/api/profiles {data} -> 校验后落盘 (先备份)。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        return _json_response({"ok": False, "error": "data.profiles 必须是数组"}, 400)
    valid, errs = _profiles.validate_profiles(data)
    if errs:
        return _json_response({"ok": False, "error": "存在非法档案", "errors": errs}, 400)
    if os.path.exists(_profiles.PROFILES_PATH):
        import shutil
        shutil.copy2(_profiles.PROFILES_PATH, _profiles.PROFILES_PATH + ".bak")
    _profiles.save_profiles(data)
    runtime_snapshot.invalidate_snapshot()
    return _json_response({"ok": True, "count": len(valid)})


async def get_grouprules(_request: web.Request) -> web.Response:
    """GET /taglib/api/grouprules -> 互斥域 (组名+成员) + 覆盖统计。"""
    groups = _grouprules.load_grouprules()
    return _json_response({"ok": True,
                           "groups": [{"id": g["id"], "members": sorted(g["members"])}
                                      for g in groups]})


async def save_grouprules(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return _json_response({"ok": False, "error": "groups 必须是数组"}, 400)
    clean = [{"id": str(g.get("id")), "members": sorted({str(m).lower() for m in
                                                         (g.get("members") or []) if str(m).strip()})}
             for g in groups if str(g.get("id") or "").strip()]
    _grouprules.save_grouprules(clean)
    runtime_snapshot.invalidate_snapshot()
    return _json_response({"ok": True, "count": len(clean)})


async def get_nl(_request: web.Request) -> web.Response:
    """GET /taglib/api/nl -> nl_flavors.json + 武器姿势覆盖缺口。"""
    data = _nl.load_flavors()
    pose_words = set()
    for p in _profiles.load_profiles().get("profiles") or []:
        for e in (p.get("poses") or []) + (p.get("extras") or []):
            pose_words.update(str(t).lower() for t in (e.get("tags") or []))
    covered = set((data.get("pose_map") or {}).keys())
    return _json_response({"ok": True, "data": data,
                           "uncovered": sorted(pose_words - covered)})


async def save_nl(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    data = payload.get("data")
    if not isinstance(data, dict):
        return _json_response({"ok": False, "error": "data 必须是对象"}, 400)
    if os.path.exists(_nl.FLAVORS_PATH):
        import shutil
        shutil.copy2(_nl.FLAVORS_PATH, _nl.FLAVORS_PATH + ".bak")
    tmp = _nl.FLAVORS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _nl.FLAVORS_PATH)
    _nl._cache = None
    return _json_response({"ok": True})


async def draw_tags(request: web.Request) -> web.Response:
    """POST /taglib/api/draw {state, seed} -> 服务端引擎真抽一次 (面板 🎲 的唯一真源)。

    与节点执行完全同一代码路径: 面板预览 = 排队实出, 不再有前端复刻引擎的漂移。
    """
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    state = payload.get("state")
    if not isinstance(state, dict):
        state = {}
    try:
        seed = int(payload.get("seed", 0))
    except (TypeError, ValueError):
        seed = 0
    nsfw_on = bool(state.get("nsfw", False))
    lib = library.get_merged()
    snap = runtime_snapshot.get_snapshot(lib)
    cfg = _engine.resolve_config(state, lib.get("settings") or {})
    try:
        cw = json.loads(state.get("category_weights") or "{}")
    except Exception:
        cw = None
    res = _engine.run_auto(snap, state, seed, nsfw_on=nsfw_on,
                        avoid_conflicts=bool(state.get("avoid_conflicts", True)),
                        search_text=str(state.get("search_text") or ""),
                        cat_weights=cw if isinstance(cw, dict) else None, config=cfg)
    picks = [{"en": p.en, "zh": p.zh, "cat": p.cat, "src": p.source,
              "bundle": p.bundle, "ext": p.kind == "ext", "nsfw": p.nsfw,
              "gender": p.gender, "hands": p.hands} for p in res.picks]
    return _json_response({"ok": True, "picks": picks, "seed": seed,
                           "stats": res.stats,
                           "dropped": [snap.tag_text[i] for i in res.dropped_ids]})


# ------------------------------------------------------------ conflicts
