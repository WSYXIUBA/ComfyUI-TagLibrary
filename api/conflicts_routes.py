"""反冲突规则路由: 读取 / 保存 / 导入预览 / 导入 / 选择体检。"""

from __future__ import annotations

import json

from aiohttp import web

from .. import library
from .. import tagconflicts
from ._common import _json_response


async def get_conflicts(_request: web.Request) -> web.Response:
    """GET /taglib/api/conflicts -> 规则 + 失效清单 + AI 说明。"""
    return _json_response(tagconflicts.get_state(library.get_merged()))


async def save_conflicts(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts {rules} -> 整树保存 (设置弹窗用)。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    result = tagconflicts.save_rules(rules)
    state = tagconflicts.get_state(library.get_merged())
    return _json_response({**result, "invalid": state["invalid"]})


async def preview_conflicts_import(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts/preview-import {rules} -> dry-run 校验 (不落盘)。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    lib = library.get_merged()
    idx = tagconflicts._lib_index(lib)
    invalid = []
    kept = []
    for i, r in enumerate(rules):
        if not tagconflicts._valid_shape(r):
            invalid.append({"index": i, "id": r.get("id") or f"#{i}", "reason": "格式不合法"})
            continue
        kept.append(r)
        _, ok_l = tagconflicts.resolve_ref(r["left"], idx)
        if not ok_l:
            invalid.append({"index": i, "id": r.get("id"), "reason":
                            f"库中不存在: {r['left'].get('value')}"})
        for ref in r.get("right", []):
            _, ok_r = tagconflicts.resolve_ref(ref, idx)
            if not ok_r:
                invalid.append({"index": i, "id": r.get("id"), "reason":
                                f"库中不存在: {ref.get('value')}"})
    return _json_response({"ok": True, "total": len(rules), "valid": len(kept),
                           "invalid": invalid})


async def apply_conflicts_import(request: web.Request) -> web.Response:
    """POST /taglib/api/conflicts/import {rules, mode: replace|merge} -> 落盘。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "请求体不是合法 JSON"}, 400)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return _json_response({"ok": False, "error": "rules 必须是数组"}, 400)
    mode = payload.get("mode") or "replace"
    if mode == "merge":
        existing = tagconflicts.load_rules()
        have = {(str(r.get("id")), json.dumps(r.get("left"), sort_keys=True),
                 json.dumps(r.get("right"), sort_keys=True)) for r in existing}
        for r in rules:
            key = (str(r.get("id")), json.dumps(r.get("left"), sort_keys=True),
                   json.dumps(r.get("right"), sort_keys=True))
            if key not in have:
                existing.append(r)
                have.add(key)
        rules = existing
    result = tagconflicts.save_rules(rules)
    state = tagconflicts.get_state(library.get_merged())
    return _json_response({**result, "mode": mode, "invalid": state["invalid"]})


async def check_conflicts(request: web.Request) -> web.Response:
    """POST {ens: [tag en ...]} -> 冲突体检结果。"""
    try:
        payload = await request.json()
    except Exception:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    ens = [str(e) for e in (payload.get("ens") or [])]
    return _json_response({"ok": True,
                           "conflicts": tagconflicts.check_selection(ens, library.get_merged())})
