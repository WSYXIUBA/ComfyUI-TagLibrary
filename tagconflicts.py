"""反冲突规则引擎 —— data/taglib/conflicts.json。

规则模型 (双向互斥: 随机抽取时抽到 left 一侧, right 一侧全部让位; 手动点选不拦):

    {
      "id": "nude-vs-clothes",
      "note": "可选备注",
      "left":  {"kind": "tag|tags|sub|cat", "value": "..."},
      "right": [ {"kind": "tag|sub|cat", "value": "..."}, ... ]
    }

kind 取值:
  tag  = 单个标签 (value=标签英文)
  tags = 多个标签 (value=[英文, ...], 仅 left 使用)
  sub  = 二级分类 (value="一级分类名/二级分类名")
  cat  = 一级分类 (value="一级分类名")

语义: left/right 各解析成标签集合; 已抽中的标签命中一侧 → 另一侧进入禁选集。
文件缺失时用 DEFAULT_RULES 生成 (裸露/泳装 ↔ 服装子分类; 配饰不冲突)。
旧版互斥组 (data/conflicts.json groups) 自动迁移为 tags 组规则。
"""

from __future__ import annotations

import json
import os
import re
import threading

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import library
    from . import tagfiles
except ImportError:  # pragma: no cover
    import library
    import tagfiles

CONFLICTS_PATH = os.path.join(tagfiles.LIBRARY_DIR, "conflicts.json")
LEGACY_GROUPS_PATH = os.path.join(os.path.dirname(tagfiles.LIBRARY_DIR), "conflicts.json")

_DOC_TEXT = (
    "这是 ComfyUI-TagLibrary 的反冲突文件 (conflicts.json)。"
    "把本文件和「全量模板 taglib_模板_全量.md」一起发给 AI, AI 即可认识库中全部标签,"
    "按下面的规则格式生成新的反冲突文件; 拿回来在管理页「📥 导入」预览确认即可。\n"
    "规则 = left 与 right 双向互斥: 随机填充/自动模式抽到 left 一侧时, right 一侧的标签自动让位"
    " (手动点选不受影响)。\n"
    "left/right 的 kind 取值:\n"
    '  tag  = 单个标签, value 填标签英文 (如 "nude")\n'
    "  tags = 多个标签, value 填英文数组 (仅 left 使用)\n"
    '  sub  = 二级分类, value 填 "一级分类名/二级分类名" (如 "服装系统/上装")\n'
    '  cat  = 一级分类, value 填一级分类名 (如 "光影氛围")\n'
    "每条规则必须有唯一 id; note 为可选备注。完成后输出整个 JSON 文件内容。"
)

_NSFW_NUDE = ["nude", "topless", "completely nude", "partially nude", "bottomless",
              "naked towel", "naked ribbon", "naked apron",
              "covered nipples", "hair over breasts"]
DEFAULT_RULES = [
    {"id": "nude-vs-clothes",
     "note": "裸露类 ↔ 上装/下装/套装 (配饰不冲突, 项链等可保留)",
     "left": {"kind": "tags", "value": _NSFW_NUDE},
     "right": [{"kind": "sub", "value": "服装系统/上装"},
               {"kind": "sub", "value": "服装系统/下装"},
               {"kind": "sub", "value": "服装系统/套装与制服"}]},
    {"id": "swimsuit-vs-top",
     "note": "普通泳装 ↔ 上装",
     "left": {"kind": "tags", "value": ["swimsuit", "competition swimsuit"]},
     "right": [{"kind": "sub", "value": "服装系统/上装"}]},
    {"id": "bikini-vs-clothes",
     "note": "比基尼 ↔ 上装+下装",
     "left": {"kind": "tags", "value": ["micro bikini", "string bikini"]},
     "right": [{"kind": "sub", "value": "服装系统/上装"},
               {"kind": "sub", "value": "服装系统/下装"}]},
    {"id": "suit-vs-tops",
     "note": "连体套装(连衣裙/旗袍/制服) ↔ 分体上下装",
     "left": {"kind": "sub", "value": "服装系统/套装与制服"},
     "right": [{"kind": "sub", "value": "服装系统/上装"},
               {"kind": "sub", "value": "服装系统/下装"}]},
    {"id": "realism-vs-anime",
     "note": "写实向 ↔ 二次元向",
     "left": {"kind": "sub", "value": "风格媒介/写实向"},
     "right": [{"kind": "sub", "value": "风格媒介/二次元向"}]},
    {"id": "nipple-vs-top",
     "note": "露点类 ↔ 上装",
     "left": {"kind": "tags", "value": ["nipples", "puffy nipples", "underboob", "sideboob"]},
     "right": [{"kind": "sub", "value": "服装系统/上装"}]},
]

_KINDS_REF = {"tag", "tags", "sub", "cat"}
_strip = re.compile(r"\s+")

_lock = threading.Lock()
_cache: dict | None = None
_cache_key: tuple | None = None


def _norm_en(x) -> str:
    return _strip.sub(" ", str(x or "")).strip().lower()


def _mtime_c() -> float:
    try:
        return os.stat(CONFLICTS_PATH).st_mtime
    except OSError:
        return 0.0


def _lib_key() -> tuple:
    return (library._mtime(library.DEFAULT_PATH), library._mtime(library.USER_PATH))


def _write_file(payload: dict) -> None:
    os.makedirs(tagfiles.LIBRARY_DIR, exist_ok=True)
    tmp = CONFLICTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFLICTS_PATH)


def _migrate_legacy_groups() -> list[dict]:
    try:
        with open(LEGACY_GROUPS_PATH, "r", encoding="utf-8-sig") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return []
    rules = []
    for i, g in enumerate(old.get("groups", []) or []):
        tags = [str(t).strip() for t in (g.get("tags") or []) if str(t).strip()]
        if len(tags) < 2:
            continue
        rules.append({
            "id": f"legacy.{g.get('id') or i}",
            "note": f"旧互斥组: {g.get('name') or g.get('id') or i}",
            "left": {"kind": "tags", "value": tags},
            "right": [{"kind": "tag", "value": t} for t in tags],
        })
    return rules


def _fresh_payload() -> dict:
    rules = list(DEFAULT_RULES)
    have = {r["id"] for r in rules}
    for r in _migrate_legacy_groups():
        if r["id"] not in have:
            rules.append(r)
            have.add(r["id"])
    return {"_说明": _DOC_TEXT, "version": 1, "rules": rules}


def _ensure_file() -> None:
    if not os.path.isfile(CONFLICTS_PATH):
        try:
            _write_file(_fresh_payload())
        except OSError:
            pass


def _valid_shape(r) -> bool:
    if not isinstance(r, dict) or not str(r.get("id") or "").strip():
        return False
    lft = r.get("left")
    if not isinstance(lft, dict) or lft.get("kind") not in _KINDS_REF:
        return False
    if lft["kind"] == "tags":
        if not isinstance(lft.get("value"), list) or not lft["value"]:
            return False
    elif not str(lft.get("value") or "").strip():
        return False
    rights = r.get("right")
    if not isinstance(rights, list) or not rights:
        return False
    for ref in rights:
        if not isinstance(ref, dict) or ref.get("kind") not in (_KINDS_REF - {"tags"}):
            return False
        if not str(ref.get("value") or "").strip():
            return False
    return True


def load_rules() -> list[dict]:
    global _cache, _cache_key
    key = (_lib_key(), _mtime_c())
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache["rules"]
        _ensure_file()
        rules: list[dict] = []
        try:
            with open(CONFLICTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r in data.get("rules", []) or []:
                if _valid_shape(r):
                    rules.append(r)
        except (OSError, ValueError):
            rules = [dict(r) for r in DEFAULT_RULES]
        _cache, _cache_key = {"rules": rules}, key
        return rules


def save_rules(rules: list[dict], doc: str | None = None) -> dict:
    global _cache, _cache_key
    clean, seen = [], set()
    for r in rules or []:
        if not _valid_shape(r):
            continue
        rid = str(r["id"]).strip()
        n = 2
        while rid in seen:
            rid = f"{r['id']}-{n}"
            n += 1
        seen.add(rid)
        clean.append({**r, "id": rid})
    payload = {"_说明": doc or _DOC_TEXT, "version": 1, "rules": clean}
    with _lock:
        _write_file(payload)
        _cache, _cache_key = {"rules": clean}, (_lib_key(), _mtime_c())
    return {"ok": True, "count": len(clean)}


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


# ---------------------------------------------------------------- 解析与校验

def _lib_index(lib: dict) -> dict:
    idx: dict[str, dict[str, set]] = {}
    for c in lib.get("categories", []):
        subs = idx.setdefault(str(c.get("name", "")), {})
        for s in c.get("subcategories", []):
            subs[str(s.get("name", ""))] = {
                _norm_en(t.get("en")) for t in (s.get("tags") or []) if t.get("en")
            }
    return idx


_ALL_ENS_CACHE: dict = {}


def _all_ens(idx: dict) -> set:
    out: set = set()
    for subs in idx.values():
        for tags in subs.values():
            out |= tags
    return out


def _all_ens_cached(idx: dict) -> set:
    key = id(idx)
    if key not in _ALL_ENS_CACHE:
        if len(_ALL_ENS_CACHE) > 4:
            _ALL_ENS_CACHE.clear()
        _ALL_ENS_CACHE[key] = _all_ens(idx)
    return _ALL_ENS_CACHE[key]


def resolve_ref(ref: dict, idx: dict) -> tuple[set, bool]:
    """引用 -> (标签 en_lower 集合, 是否有效)。指向库中不存在的目标视为无效。"""
    kind, value = ref.get("kind"), ref.get("value")
    if kind == "tag":
        v = _norm_en(value)
        return ({v}, bool(v)) if v and v in _all_ens_cached(idx) else (set(), False)
    if kind == "tags":
        ens = _all_ens_cached(idx)
        got = ({_norm_en(v) for v in (value or [])} & ens) - {""}
        return (got, bool(got))
    if kind == "cat":
        subs = idx.get(str(value).strip())
        if not subs:
            return set(), False
        return {e for tags in subs.values() for e in tags}, True
    if kind == "sub":
        raw = str(value).strip()
        if "/" not in raw:
            return set(), False
        cname, sname = raw.split("/", 1)
        tags = idx.get(cname.strip(), {}).get(sname.strip())
        if tags is None:
            return set(), False
        return set(tags), True
    return set(), False


def get_state(lib: dict | None = None) -> dict:
    """规则 + 失效清单 + 说明 (供 API/前端/导出)。"""
    rules = load_rules()
    invalid: list[dict] = []
    if lib is not None:
        idx = _lib_index(lib)
        for i, r in enumerate(rules):
            _, ok_l = resolve_ref(r["left"], idx)
            if not ok_l:
                invalid.append({"index": i, "id": r.get("id"), "side": "left",
                                "value": r["left"].get("value")})
            for ref in r.get("right", []):
                _, ok_r = resolve_ref(ref, idx)
                if not ok_r:
                    invalid.append({"index": i, "id": r.get("id"), "side": "right",
                                    "value": ref.get("value")})
    return {"ok": True, "rules": rules, "invalid": invalid, "doc": _DOC_TEXT}


# ---------------------------------------------------------------- 引擎

class ExclusionIndex:
    """规则解析后的对称互斥索引: en -> 与其互斥的 en 集合。构建一次, 查询极快。"""

    def __init__(self, lib: dict):
        idx = _lib_index(lib)
        self.map: dict[str, set] = {}
        for r in load_rules():
            lset, _ = resolve_ref(r["left"], idx)
            rset: set = set()
            for ref in r.get("right", []):
                s, _ = resolve_ref(ref, idx)
                rset |= s
            if not lset or not rset:
                continue
            for e in lset:
                self.map.setdefault(e, set()).update(rset)
            for e in rset:
                self.map.setdefault(e, set()).update(lset)

    def banned_for(self, picked_lowers) -> set:
        banned: set = set()
        for e in picked_lowers:
            banned.update(self.map.get(e, ()))
        return banned


# ---------------------------------------------------------------- 旧接口兼容

def get_groups() -> list[dict]:
    """旧接口: tags 组规则还原成组形式 (组内互斥语义由调用方触发式使用)。"""
    out = []
    for r in load_rules():
        if r["left"].get("kind") == "tags" and all(
                ref.get("kind") == "tag" for ref in r.get("right", [])):
            members = [str(v) for v in r["left"]["value"]]
            if {str(ref["value"]) for ref in r["right"]} >= set(members):
                out.append({"id": r["id"], "name": r.get("note", ""), "tags": members})
    return out


def save_groups(groups: list[dict]) -> None:
    """旧接口: 组列表追加迁移进新规则文件。"""
    rules = load_rules()
    have = {r.get("id") for r in rules}
    for i, g in enumerate(groups or []):
        tags = [str(t).strip() for t in (g.get("tags") or []) if str(t).strip()]
        if len(tags) < 2:
            continue
        rid = f"legacy.{g.get('id') or i}"
        if rid in have:
            continue
        rules.append({"id": rid, "note": f"旧互斥组: {g.get('name') or rid}",
                      "left": {"kind": "tags", "value": tags},
                      "right": [{"kind": "tag", "value": t} for t in tags]})
    save_rules(rules)


def conflicts_for(tag_names: list[str], lib: dict | None = None) -> dict[str, list[dict]]:
    """给定标签 -> 各自命中的规则引用 (展示用)。"""
    rules = load_rules()
    idx = _lib_index(lib) if lib is not None else None
    wanted = {_norm_en(t) for t in tag_names}
    out: dict[str, list[dict]] = {}
    for r in rules:
        lset, _ = resolve_ref(r["left"], idx) if idx else (set(), True)
        for ref in r.get("right", []):
            rset, _ = resolve_ref(ref, idx) if idx else (set(), True)
            for w in wanted & lset:
                out.setdefault(w, []).append({"rule": r.get("id"), "ref": ref})
            for w in wanted & rset:
                out.setdefault(w, []).append({"rule": r.get("id"), "ref": r["left"]})
    return out


def filter_conflicts(candidates: list[dict], already_chosen: list[str],
                     lib: dict | None = None) -> tuple[list[dict], int]:
    """随机池静态过滤: 与已选标签互斥的候选剔除。"""
    lib = lib if lib is not None else library.get_merged()
    ex = ExclusionIndex(lib)
    banned = ex.banned_for(_norm_en(c) for c in already_chosen)
    if not banned:
        return candidates, 0
    out, blocked = [], 0
    for c in candidates:
        if _norm_en(c.get("en")) in banned:
            blocked += 1
            continue
        out.append(c)
    return out, blocked


def check_selection(en_list: list[str], lib: dict | None = None) -> dict[str, list[str]]:
    """勾选集冲突体检: {标签: 与之互斥的其他已选标签}。"""
    lib = lib if lib is not None else library.get_merged()
    ex = ExclusionIndex(lib)
    lowers = [_norm_en(e) for e in en_list]
    out: dict[str, list[str]] = {}
    for e in lowers:
        bad = [x for x in lowers if x != e and x in ex.map.get(e, ())]
        if bad:
            out[e] = bad
    return out
