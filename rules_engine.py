"""规则引擎 v2 (方案 V2.1 阶段 2) —— 规则编译, 纯逻辑, 冷路径。

规则类型:
  mutex     双向互斥 (v1 兼容; 抽到一侧另一侧让位)
  requires  left 抽中时自动并入 right 标签 (受 mutex/NSFW/排除约束); 冷路径求闭包+环检测
  suppress  left 抽中时 right 权重 ×(1-suppress_rate)
  boost     无条件: right 标签基础权重 ×boost_factor (预编译进 boost_map)
  replace   预留 (v2.2)

编译产物 CompiledRules:
  mutex_pairs   [(frozenset(ids))]            互斥对闭包展开前的原始对
  conflict_map  {id: set(ids)}                对称互斥索引 (喂 RuntimeSnapshot)
  require_edges [(left_id, right_ids tuple)]  已求闭包的依赖边 (环检测后)
  boost_map     {id: float}                   无条件权重乘数
  cond_effects  [(left_ids frozenset, right_ids tuple, factor)]  条件效果 (suppress)
  invalid       [{id, reason}]                失效规则清单

所有 id 为 int (RuntimeSnapshot 的 tag index)。引用解析由调用方注入 resolver。
"""

from __future__ import annotations

import schema


def _resolve_ref(ref: dict, index) -> tuple[set, bool]:
    """引用 → (id 集合, 是否有效)。index 需提供: cat_index/cat_subs/tag_ens。"""
    kind, value = ref.get("kind"), ref.get("value")
    if kind == "tag":
        tid = index.tag_id(str(value))
        return ({tid}, tid is not None) if tid is not None else (set(), False)
    if kind == "tags":
        out = set()
        for v in value or []:
            tid = index.tag_id(str(v))
            if tid is not None:
                out.add(tid)
        return (out, bool(out))
    if kind == "cat":
        ci = index.cat_index(str(value).strip())
        if ci is None:
            return set(), False
        return set(index.cat_tag_ids[ci]), True
    if kind == "sub":
        si = index.sub_index(str(value).strip())
        if si is None:
            return set(), False
        return set(index.sub_tag_ids[si]), True
    return set(), False


def compile_rules(raw_rules: list[dict], index) -> "CompiledRules":
    """把规则文件编译为运行时结构 (冷路径)。

    - v1 规则 (无 type) 自动视为 mutex
    - requires: 冷路径邻接表 → DFS 闭包, 环边标红跳过
    - suppress: 编译为 (left_set, right_ids, factor) 条件效果
    - boost:    无条件乘数直接进 boost_map
    - 引用失效的规则标红保留在 invalid, 不参与编译
    """
    rules = schema.migrate_rules(raw_rules or [])
    cr = CompiledRules()

    for r in rules:
        if not r.get("enabled", True):
            continue
        rtype = r.get("type", "mutex")
        lref = r.get("left") or {}
        lset, ok_l = _resolve_ref(lref, index)
        rsets, ok_r = [], True
        for ref in r.get("right") or []:
            s, ok = _resolve_ref(ref, index)
            rsets.append(s)
            ok_r = ok_r and ok
        if not ok_l or not ok_r or not lset or not any(rsets):
            cr.invalid.append({"id": r.get("id"), "type": rtype,
                               "reason": "引用目标在库中不存在"})
            continue

        if rtype == "mutex":
            for l in lset:
                for rs in rsets:
                    for rr in rs:
                        if l != rr:
                            cr.conflict_map.setdefault(l, set()).add(rr)
                            cr.conflict_map.setdefault(rr, set()).add(l)
            cr.mutex_rules.append(r)

        elif rtype == "requires":
            # left 每个标签 requires right 全体 (闭包在 _require_closure 中展开)
            params = r.get("params") or {}
            for l in lset:
                for rs in rsets:
                    cr.require_edges.append((l, tuple(sorted(rs))))
            _ = params

        elif rtype == "suppress":
            rate = float((r.get("params") or {}).get("suppress_rate", 0.8))
            factor = max(0.0, min(1.0, 1.0 - rate))
            for rs in rsets:
                cr.cond_effects.append((frozenset(lset), tuple(sorted(rs)), factor))

        elif rtype == "boost":
            factor = float((r.get("params") or {}).get("boost_factor", 1.5))
            for rs in rsets:
                for rr in rs:
                    cr.boost_map[rr] = cr.boost_map.get(rr, 1.0) * factor

        elif rtype == "replace":
            cr.invalid.append({"id": r.get("id"), "type": rtype,
                               "reason": "replace 规则 v2.1 尚未支持"})

        else:
            cr.invalid.append({"id": r.get("id"), "type": rtype,
                               "reason": f"未知规则类型 {rtype}"})

    _require_closure(cr)
    return cr


def _require_closure(cr: "CompiledRules") -> None:
    """requires 闭包: 邻接表 → 每 id 完整传递依赖 (DFS, 环检测)。"""
    adj: dict[int, set] = {}
    for l, rs in cr.require_edges:
        adj.setdefault(l, set()).update(rs)

    done: dict[int, tuple] = {}
    visiting: set = set()
    cycles: list[tuple] = []

    def dfs(node: int, path: list) -> tuple:
        if node in done:
            return done[node]
        if node in visiting:
            cycles.append(tuple(path + [node]))
            return ()
        visiting.add(node)
        acc: set = set()
        for nxt in adj.get(node, ()):
            acc.add(nxt)
            acc.update(dfs(nxt, path + [node]))
        visiting.discard(node)
        result = tuple(sorted(acc))
        done[node] = result
        return result

    for node in list(adj.keys()):
        dfs(node, [])

    if cycles:
        for cyc in cycles:
            cr.invalid.append({"id": "requires", "type": "requires",
                               "reason": f"环依赖已失效: {' -> '.join(map(str, cyc))}"})

    # 只保留闭包非空的节点
    for node, closure in done.items():
        if closure:
            cr.require_closure[node] = tuple(sorted(closure))


class CompiledRules:
    __slots__ = ("mutex_rules", "conflict_map", "require_edges", "require_closure",
                 "boost_map", "cond_effects", "invalid")

    def __init__(self):
        self.mutex_rules: list[dict] = []
        self.conflict_map: dict[int, set] = {}
        self.require_edges: list[tuple[int, tuple]] = []
        self.require_closure: dict[int, tuple] = {}
        self.boost_map: dict[int, float] = {}
        self.cond_effects: list[tuple[frozenset, tuple, float]] = []
        self.invalid: list[dict] = []
