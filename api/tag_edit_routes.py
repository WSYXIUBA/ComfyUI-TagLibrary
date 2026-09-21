"""标签就地编辑路由 (2026-09-19 编辑体验改造)。

## 三个端点对应三件事

  GET  /taglib/api/axes-overview   流水线首页的数据 (按 Anima 官方六段分组的 13 条轴)
  POST /taglib/api/tag/derive      只给 en/中文/轴/槽位 → 预览推导出的完整标签 + 侧表建议
  POST /taglib/api/tag/create      新增 (同上, 但落盘)
  POST /taglib/api/tag/update      按 id 就地改单个标签的字段
  GET  /taglib/api/tag/incomplete  "行为属性还没登记"的汇总 (前端收成一个角标)

## ⚠ 落盘口径: 必须整树提交

不能"只写改动的那个槽位"。两个原因都在 `library.py`:

  1. `_merge_level` 是**按 id 浅覆盖** —— 用户库里同 id 的子分类会**整体顶掉**
     默认库的那份, 于是 `name` / `random_quota` / `min_count` / `max_count` /
     `priority_boost` 全部丢失 (只剩你写进去的那几个键)。
  2. `save_user_library` 的墓碑逻辑会把**提交树里没有的 id** 全部记成"已删除" ——
     只提交一个槽位 = 把全库其余 4000+ 词全部标记删除, 下次合并库直接变空。

整树提交是唯一安全的写法, 管理页 (`POST /taglib/api/library`) 本来就是这么做的。
本模块复用同一条路径: 读合并库 → 改内存树 → `save_user_library` → 镜像 → 失效缓存。
"""

from __future__ import annotations

import json

from aiohttp import web

from .. import axes
from .. import derive
from .. import library
from .. import profiles as _profiles
from .. import runtime_snapshot
from .. import schema
from ._common import _json_response


# 可就地编辑的字段白名单。`id` 与 `axis` 不在内:
# id 是合并主键 (改了等于换一条标签), axis 由槽位归属决定 (改轴 = 搬槽位)。
EDITABLE_FIELDS = frozenset({
    "en", "zh", "weight", "enabled", "type", "priority", "rarity", "groups",
    "aliases", "desc", "gender", "requires", "mutex_with", "nsfw", "minor_block",
})

_LIST_FIELDS = ("groups", "aliases", "requires", "mutex_with")
_BOOL_FIELDS = ("enabled", "nsfw", "minor_block")
_STR_FIELDS = ("en", "zh", "desc")


def _coerce_fields(fields: dict) -> tuple[dict, list[str]]:
    """按字段类型校验并归一。**非法值直接拒, 不静默改成别的值。**

    为什么不在写库后靠 `schema.migrate_tag` 兜底: 它用的是 `setdefault`,
    只在字段**缺失**时补默认 —— 已经存在的非法值 (如 rarity="bogus") 原样穿过,
    于是库里会沉淀出引擎不认识的值。校验必须发生在入口。
    """
    out: dict = {}
    errs: list[str] = []
    for k, v in fields.items():
        if k in _STR_FIELDS:
            out[k] = str(v or "").strip()
            if k == "en" and not out[k]:
                errs.append("en 不能为空")
        elif k in _BOOL_FIELDS:
            if isinstance(v, bool):
                out[k] = v
            else:
                errs.append(f"{k} 必须是 true/false")
        elif k == "weight":
            # 上界与 library._validate_tags 的 (0, 3] 对齐 —— 超出会被它判非法,
            # 那时代码已经走到 save_user_library, 用户只会看到一句 500 而不是原因。
            try:
                out[k] = max(0.05, min(3.0, float(v)))
            except (TypeError, ValueError):
                errs.append("weight 必须是数字")
        elif k == "priority":
            try:
                out[k] = max(0, min(200, int(v)))
            except (TypeError, ValueError):
                errs.append("priority 必须是整数")
        elif k == "rarity":
            if str(v) in schema.RARITY_SPAWN_RATE:
                out[k] = str(v)
            else:
                errs.append(f"rarity 只能是 {sorted(schema.RARITY_SPAWN_RATE)}")
        elif k == "type":
            if str(v) in schema.TAG_TYPES:
                out[k] = str(v)
            else:
                errs.append(f"type 只能是 {list(schema.TAG_TYPES)}")
        elif k == "gender":
            g = str(v or "").strip().lower()
            if g in ("", "female", "male"):
                out[k] = g
            else:
                errs.append("gender 只能是 ''/female/male")
        elif k in _LIST_FIELDS:
            if isinstance(v, list):
                out[k] = [str(x).strip() for x in v if str(x).strip()]
            else:
                errs.append(f"{k} 必须是数组")
        else:
            errs.append(f"{k} 不支持编辑")
    return out, errs


# ---------------------------------------------------------------- 首页数据


async def get_axes_overview(_request: web.Request) -> web.Response:
    """GET /taglib/api/axes-overview -> 按官方六段分组的轴 + 真实标签数/槽位数。

    段位与段名直接取 `axes.AXIS_SECTION` / `axes.SECTION_NAMES` —— 那是 Anima
    官方拼接序在代码里的唯一真源, 前端**不许**自己再抄一份。
    """
    lib = library.get_merged()
    counts: dict[str, int] = {}
    slots: dict[str, int] = {}
    for cat in lib.get("categories", []):
        aid = axes.AXIS_ZH_TO_ID.get(cat.get("name", ""))
        if not aid:
            continue
        counts[aid] = counts.get(aid, 0) + sum(
            len(s.get("tags") or []) for s in cat.get("subcategories", []))
        slots[aid] = slots.get(aid, 0) + len(cat.get("subcategories", []))

    sections = sorted(set(axes.AXIS_SECTION.values()) | {4})   # 4=作品: 库内暂无轴, 占位
    segments = []
    for sec in sections:
        seg_axes = [a for a in axes.AXIS_ORDER if axes.AXIS_SECTION.get(a) == sec]
        segments.append({
            "section": sec,
            "name": axes.SECTION_NAMES.get(sec, f"段{sec}"),
            "placeholder": not seg_axes,
            "axes": [{"id": a, "zh": axes.AXIS_NAME_ZH.get(a, a),
                      "count": counts.get(a, 0), "slots": slots.get(a, 0)}
                     for a in seg_axes],
        })
    return _json_response({"ok": True, "segments": segments,
                           "total": sum(counts.values())})


# ---------------------------------------------------------------- 推导 / 新增


async def _payload(request: web.Request) -> dict | None:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _find_slot(lib: dict, slot_id: str) -> tuple[dict | None, dict | None]:
    """按子分类 id 定位 (分类, 槽位)。"""
    for cat in lib.get("categories", []):
        for sub in cat.get("subcategories", []):
            if str(sub.get("id") or "") == slot_id:
                return cat, sub
    return None, None


def _commit(lib: dict) -> tuple[dict | None, web.Response | None]:
    """整树提交 + 失效快照 + 镜像。

    必须捕获 `library.LibraryError`: 它是"库校验不过 / 乐观锁冲突"的正常业务错误
    (`validate` 会拒非法权重、重复 id 等), 不接住就会以 500 + 堆栈的形式糊到前端,
    用户看不到真正原因。
    """
    try:
        result = library.save_user_library(lib)
    except library.LibraryError as exc:
        return None, _json_response({"ok": False, "error": str(exc)}, 409)
    except Exception as exc:  # noqa: BLE001
        return None, _json_response({"ok": False, "error": f"保存失败: {exc}"}, 500)
    runtime_snapshot.invalidate_snapshot()
    library.mirror_folder_now()
    return result, None


def _find_tag(lib: dict, tag_id: str):
    for cat in lib.get("categories", []):
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []) or []:
                if str(t.get("id") or "") == tag_id:
                    return cat, sub, t
    return None, None, None


async def preview_derive(request: web.Request) -> web.Response:
    """POST /taglib/api/tag/derive -> 只推导不落盘 (前端边打字边看会补什么)。"""
    data = await _payload(request)
    if data is None:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    en = str(data.get("en") or "").strip()
    if not en:
        return _json_response({"ok": False, "error": "en 不能为空"}, 400)
    axis = str(data.get("axis") or "").strip()
    slot_name = str(data.get("slot_name") or "").strip()
    try:
        tag, hints = derive.derive_tag(en, str(data.get("zh") or ""), axis, slot_name,
                                       sub_id=str(data.get("slot_id") or ""))
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 400)
    return _json_response({"ok": True, "tag": tag, "hints": hints})


async def create_tag(request: web.Request) -> web.Response:
    """POST /taglib/api/tag/create {en, zh, slot_id, apply_profile?} -> 新增并落盘。

    只需 en / 中文 / slot_id 三项。其余字段由 `derive.derive_tag` 推导;
    `apply_profile=true` 时把推导出的档案条目**一并**写进 profiles.json ——
    这就是"不用再跑武器档案页登记"的那一步。
    """
    data = await _payload(request)
    if data is None:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    en = str(data.get("en") or "").strip().lower()
    if not en:
        return _json_response({"ok": False, "error": "en 不能为空"}, 400)
    slot_id = str(data.get("slot_id") or "").strip()
    if not slot_id:
        return _json_response({"ok": False, "error": "必须指定 slot_id"}, 400)

    lib = library.get_merged()
    cat, sub = _find_slot(lib, slot_id)
    if sub is None:
        return _json_response({"ok": False, "error": f"找不到槽位 {slot_id}"}, 404)
    axis = str(sub.get("axis") or axes.axis_of(cat.get("name", ""), sub.get("name", ""))[0])

    dup = next((t for t in sub.get("tags", []) or []
                if str(t.get("en") or "").strip().lower() == en), None)
    if dup is not None:
        return _json_response({"ok": False, "error": f"该槽位已有标签 {en}",
                               "existing_id": dup.get("id")}, 409)

    try:
        tag, hints = derive.derive_tag(en, str(data.get("zh") or ""), axis,
                                       sub.get("name", ""), sub_id=slot_id)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)}, 400)
    sub.setdefault("tags", []).append(tag)

    applied_profile = None
    if data.get("apply_profile") and hints.get("entry") and hints.get("profile"):
        applied_profile = _apply_profile_entry(hints["profile"], hints["entry"])

    result, err = _commit(lib)
    if err is not None:
        return err
    return _json_response({"ok": True, "tag": tag, "hints": hints,
                           "applied_profile": applied_profile, **(result or {})})


def _apply_profile_entry(prof: dict, entry: dict) -> dict | None:
    """把推导出的条目写进 profiles.json (追加, 已存在同 id 则跳过)。

    只做"追加一条姿势/身份词", 不新建档案骨架 —— 新建档案涉及 poses/hands 建模,
    属于需要人判断的事, 由用户在武器档案页确认。
    """
    pid = str(prof.get("id") or "")
    if not pid or prof.get("new"):
        return None
    try:
        data = _profiles.load_profiles()
    except Exception:  # noqa: BLE001
        return None
    for p in data.get("profiles") or []:
        if str(p.get("id") or "") != pid:
            continue
        ent = {k: v for k, v in entry.items() if v not in ("", {}, [], None)}
        if ent.get("id") and any(str(e.get("id")) == ent["id"]
                                 for e in (p.get("poses") or []) + (p.get("extras") or [])):
            return None                      # 同 id 已存在, 幂等跳过
        poses = p.setdefault("poses", [])
        poses.append(ent)
        valid, errs = _profiles.validate_profiles(data)
        if errs:
            return None                      # 校验不过就不写, 保持 profiles.json 干净
        _profiles.save_profiles(data)
        runtime_snapshot.invalidate_snapshot()
        return {"profile": pid, "entry_id": ent.get("id")}
    return None


# ---------------------------------------------------------------- 就地编辑


async def update_tag(request: web.Request) -> web.Response:
    """POST /taglib/api/tag/update {id, fields:{...}} -> 就地改字段, 其余原样保留。"""
    data = await _payload(request)
    if data is None:
        return _json_response({"ok": False, "error": "bad json"}, 400)
    tag_id = str(data.get("id") or "").strip()
    fields = data.get("fields")
    if not tag_id or not isinstance(fields, dict):
        return _json_response({"ok": False, "error": "需要 id 与 fields"}, 400)
    unknown = sorted(set(fields) - EDITABLE_FIELDS)
    if unknown:
        return _json_response({"ok": False, "error": f"字段不可编辑: {unknown}",
                               "editable": sorted(EDITABLE_FIELDS)}, 400)
    clean, errs = _coerce_fields(fields)
    if errs:
        return _json_response({"ok": False, "error": "字段值非法", "errors": errs}, 400)

    lib = library.get_merged()
    cat, sub, tag = _find_tag(lib, tag_id)
    if tag is None:
        return _json_response({"ok": False, "error": f"找不到标签 {tag_id}"}, 404)
    before = {k: json.loads(json.dumps(tag.get(k))) for k in clean}
    tag.update(clean)
    # 归一一次: axis/type 会随槽位重算, 缺失字段补齐 (与全库口径一致)
    schema.migrate_tag(tag, cat.get("name", ""), sub.get("name", ""))

    result, err = _commit(lib)
    if err is not None:
        return err
    return _json_response({"ok": True, "id": tag_id, "before": before,
                           "after": {k: tag.get(k) for k in clean}, **(result or {})})


# ---------------------------------------------------------------- 待完善


async def get_incomplete(_request: web.Request) -> web.Response:
    """GET /taglib/api/tag/incomplete -> 行为属性缺口汇总 (前端角标 + 一键跳转)。"""
    return _json_response(derive.incomplete_report(library.get_merged()))
