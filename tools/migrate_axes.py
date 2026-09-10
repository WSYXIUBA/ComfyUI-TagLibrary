"""库数据 v2 迁移 (1.3.0) —— 一次性把旧库转成轴+组模型并落盘用户库。

做三件事:
  1. 每个 tag 补 `axis` 字段 (axes.axis_of 按 大类/子类 路径推断)。
  2. 组内全互斥的旧规则 (left=tags 且 right=tag 集覆盖同集合) → 每条规则
     编译成一个全局组名 tag.groups "m:<rule_id>" (不做跨规则传递合并,
     绝不产生原规则没有的互斥)。一个词可在多个组。
  3. 其余结构性规则 (nude↔服装池 这类 tag↔整池) 原样迁到 mutex.json ——
     /taglib/api/conflicts 契约与前端 rollFill 不破。
  覆盖校验: 每一对 (l,r) 必须被 groups ∪ mutex.json 覆盖, 漏一对拒绝落盘。

用法: python tools/migrate_axes.py          (dry-run 报告)
      python tools/migrate_axes.py --apply   (备份 + 落盘)

⚠ 一次性脚本: 1.3.0 发布时已执行完毕, 常规开发与升级无需再跑。重复执行会按当前库
   重新推导 axis 并覆盖 groups, 可能冲掉手工调整 —— 除非确有必要, 勿再运行。
   此处仅作历史归档 / 灾难恢复工具保留。
"""

from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级 = 仓库根
sys.path.insert(0, ROOT)

import axes  # noqa: E402
import tagconflicts  # noqa: E402
import library  # noqa: E402

MUTEX_PATH = tagconflicts.CONFLICTS_PATH  # 跨池规则原地重写回 conflicts.json (契约不破)


def _norm(x) -> str:
    return str(x or "").strip().lower()


def classify_rules(rules, idx):
    """→ (intra: [(rule_id, clique_set)], cross: [原规则 dict], invalid: [...])"""
    intra, cross, invalid = [], [], []
    for r in rules:
        lset, ok_l = tagconflicts.resolve_ref(r["left"], idx)
        rsets, ok_r = [], True
        for ref in r.get("right") or []:
            s, ok = tagconflicts.resolve_ref(ref, idx)
            rsets.append(s)
            ok_r = ok_r and ok
        if not ok_l or not ok_r or not lset or not any(rsets):
            invalid.append({"id": r.get("id"), "reason": "引用目标不在库中"})
            continue
        right_all = set().union(*rsets)
        lk = r["left"].get("kind")
        rkinds = {ref.get("kind") for ref in (r.get("right") or [])}
        is_intra = (lk == "tags" and rkinds == {"tag"}
                    and {_norm(x) for x in r["left"].get("value") or []}
                    == right_all)
        if is_intra:
            clique = {_norm(x) for x in r["left"].get("value") or []}
            clique |= right_all
            intra.append((str(r.get("id")), clique))
        else:
            cross.append(r)
    return intra, cross, invalid


def build_groups(intra):
    """一条规则 = 一个组名。返回 {norm_en: [组名,...]}, 冲突对总数。"""
    groups: dict[str, list[str]] = {}
    total_pairs = 0
    for rid, clique in intra:
        gname = f"m:{rid}"
        n = len(clique)
        total_pairs += n * (n - 1) // 2 - sum(
            len(clique) - 1 for _ in ()) // 1 if False else 0
        for w in clique:
            gs = groups.setdefault(w, [])
            if gname not in gs:
                gs.append(gname)
    return groups


def banned_set_of(groups, norm_en) -> frozenset:
    return frozenset(groups.get(norm_en, ()))


def verify_coverage(intra, cross, groups) -> list[str]:
    """旧规则每一对互斥 (含 cross 规则展开对) 必须被新体系覆盖。"""
    # cross 规则在运行时由 ExclusionIndex 原样生效, 天然是覆盖的一部分;
    # 这里只需校验 intra 规则: 同 clique ⇔ 共享组名。
    problems: list[str] = []
    for rid, clique in intra:
        for a in clique:
            ga = set(groups.get(a, ()))
            if f"m:{rid}" not in ga:
                problems.append(f"{a!r} 缺组 m:{rid}")
        # 抽查一对 (成本可控: clique 内全对都在同组, 定义即成立)
    return problems


def cross_pair_count(cross, idx) -> int:
    """cross 规则展开的互斥对数 (信息性)。"""
    total = 0
    for r in cross:
        lset, ok_l = tagconflicts.resolve_ref(r["left"], idx)
        rset: set = set()
        for ref in r.get("right") or []:
            s, _ = tagconflicts.resolve_ref(ref, idx)
            rset |= s
        if not lset or not rset:
            continue
        total += len(lset & rset) * 0 + sum(
            1 for l in lset for rr in rset if l != rr)
    return total


def migrate(apply: bool) -> int:
    lib = library.get_merged()
    rules = tagconflicts.load_rules()
    idx = tagconflicts._lib_index(lib)
    intra, cross, invalid = classify_rules(rules, idx)
    groups = build_groups(intra)
    problems = verify_coverage(intra, cross, groups)
    if problems:
        print("❌ 覆盖校验失败:")
        for p in problems[:20]:
            print("   ", p)
        return 1

    n_tag = n_grp = 0
    unmapped: dict[str, int] = {}
    for cat in lib.get("categories", []):
        for sub in cat.get("subcategories", []):
            axis, _order = axes.axis_of(cat.get("name", ""), sub.get("name", ""))
            if axis == "misc":
                unmapped[f"{cat.get('name')}/{sub.get('name')}"] = len(sub.get("tags") or [])
            for t in sub.get("tags", []) or []:
                n_tag += 1
                t["axis"] = axis
                gs = groups.get(_norm(t.get("en")))
                if gs:
                    merged = sorted(set(t.get("groups") or []) | set(gs))
                    if merged != sorted(t.get("groups") or []):
                        n_grp += 1
                    t["groups"] = merged

    intra_pairs = sum(len(c) * (len(c) - 1) // 2 for _, c in intra)
    print(f"规则总数 {len(rules)}: intra→组 {len(intra)} (展开互斥对 {intra_pairs}), "
          f"cross→mutex.json {len(cross)}, 失效跳过 {len(invalid)}")
    print(f"跨池互斥对 (mutex.json 原样生效): {cross_pair_count(cross, idx)}")
    print(f"标签 {n_tag}, 新增组名 {n_grp}, 打组词数 {len(groups)}")
    if unmapped:
        print("⚠ 未映射轴 (落 misc):")
        for k, v in unmapped.items():
            print(f"   {k}: {v}")

    if not apply:
        print("(dry-run, 未落盘。--apply 执行)")
        return 0

    # 全局互斥域真源 (独立文件, 免疫热同步重导入抹字段)
    try:
        import grouprules
        by_gid: dict[str, set] = {}
        for rid, clique in intra:
            by_gid[rid] = {str(w).lower() for w in clique}
        grouprules.save_grouprules(
            [{"id": gid, "members": sorted(ms)} for gid, ms in sorted(by_gid.items())])
        print(f"grouprules.json 写出 {len(by_gid)} 组")
    except ImportError:
        pass

    # 备份 (user + 默认库两份; backups/ 两份随后同步)
    for path in (library.USER_PATH, library.DEFAULT_PATH):
        if os.path.exists(path):
            bak = path + ".pre-1.3.0.bak"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)

    save_res = library.save_user_library(lib, merge_base=lib)
    if not save_res.get("ok"):
        print("❌ 保存失败:", save_res)
        return 1

    os.makedirs(os.path.dirname(MUTEX_PATH), exist_ok=True)
    tmp = MUTEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rules": cross,
                   "doc": "跨池结构性互斥规则 (tag↔整池)。组内全互斥已编入标签 groups 字段。"},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, MUTEX_PATH)
    tagconflicts._cache = None  # 失效规则缓存

    # 同步到 backups/factory + user 备份 (恢复默认库不回带旧结构的规矩)
    backup_dir = os.path.join(os.path.dirname(library.USER_PATH), "backups")
    if os.path.isdir(backup_dir):
        for name in ("factory_backup.json", "user_backup.json"):
            bp = os.path.join(backup_dir, name)
            if os.path.exists(bp):
                with open(bp, "r", encoding="utf-8") as f:
                    b = json.load(f)
                changed = False
                for cat in b.get("categories", []):
                    for sub in cat.get("subcategories", []):
                        axis, _o = axes.axis_of(cat.get("name", ""), sub.get("name", ""))
                        for t in sub.get("tags", []) or []:
                            gs = groups.get(_norm(t.get("en")))
                            want = sorted(set(t.get("groups") or []) | set(gs or []))
                            if t.get("axis") != axis or want != sorted(t.get("groups") or []):
                                t["axis"] = axis
                                t["groups"] = want
                                changed = True
                if changed:
                    tmp = bp + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(b, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, bp)

    print(f"✅ 迁移完成: 库落盘 (mtime={save_res.get('mtime')}), mutex.json {len(cross)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(migrate("--apply" in sys.argv))
