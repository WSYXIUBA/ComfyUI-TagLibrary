"""S4 分类重构: 9 大类 / 63 子类 → 12 轴 / 63 槽位 (大类降级为 facet)。

## 为什么要改
原结构的第一级是"作者视角"的大类 (人物主体 / 服装系统 / …), 而系统真正的骨架是**轴**
(`axes.py` 自己的注释就写着"分类树降级为 UI 视图")。实测 9 个大类里 **8 个恰好等于 1 条轴**
(纯冗余), 唯一例外「人物主体」一个类跨了 **5 条轴** (count 38 / character 106 /
appearance 934 / clothing 38 / prop 265 = 1381 词) —— 大类这一级在最该细分的地方塌成一锅。

改成「轴 → 槽位」后: 轴即输出段位的第一级, 大类降级为标签上的 `facet` 字段 (非结构, 仅搜索用)。

## 迁移是纯机械的
按 `axes.axis_of(大类, 子类)` 把 63 个子类重挂到 12 条轴 —— 该映射表引擎一直在用,
实测**零槽位重名冲突**。子类 id 保持不变 (`fill_sub_ranges` 按 id 存, 不受影响)。

## 本脚本做四件事
1. 生成 `axes.SUB_TO_AXIS_V2` ("轴中文名/槽位名" → (轴 id, 次序)) 并写回 axes.py
2. 重排两个库文件的 categories: 12 轴 × 各自槽位; 每个标签补 `facet` = 原大类名
3. 迁移 `conflicts.json` 里 `kind: cat/sub` 的旧路径引用 → 新路径
4. 重建 .md 镜像 (目录结构随之变成 `轴/槽位/槽位.md`)

用法:
    python tools/migrate_to_axes.py            # dry-run (只报告, 含逐词校验)
    python tools/migrate_to_axes.py --apply    # 落盘 (自动备份)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import axes  # noqa: E402
import library  # noqa: E402
import schema  # noqa: E402


def _sub_words(sub: dict) -> int:
    n = 0
    for g in sub.get("groups") or []:
        n += len(g.get("tags") or [])
    n += len(sub.get("tags") or [])
    return n


def plan_mapping(lib: dict) -> tuple[dict, list]:
    """返回 (新路径表, 新结构)。

    新结构 categories = 轴 (按 AXIS_ORDER), 每个轴下挂原本属于它的槽位。
    """
    v2: dict[str, tuple[str, int]] = {}
    buckets: dict[str, list] = {a: [] for a in axes.AXIS_ORDER}
    seen_slots: dict[str, str] = {}      # 槽位名 -> 所属轴 (重名检查)

    for cat in lib.get("categories", []):
        cname = str(cat.get("name", ""))
        for sub in cat.get("subcategories", []) or []:
            sname = str(sub.get("name", ""))
            ax, order = axes.axis_of(cname, sname)
            if sname in seen_slots and seen_slots[sname] != ax:
                raise SystemExit(f"❌ 槽位重名冲突: {sname} 同时属于 {seen_slots[sname]} 与 {ax}")
            seen_slots[sname] = ax
            zh = axes.AXIS_NAME_ZH.get(ax, ax)
            v2[f"{zh}/{sname}"] = (ax, order)
            buckets[ax].append((order, sub, cname))
    return v2, buckets


def main() -> int:
    apply = "--apply" in sys.argv
    targets = [p for p in (library.DEFAULT_PATH, library.USER_PATH) if os.path.isfile(p)]
    if not targets:
        print("找不到库文件"); return 1

    ref = json.load(open(targets[0], encoding="utf-8"))
    try:
        v2, buckets = plan_mapping(ref)
    except SystemExit as e:
        print(e); return 1

    print("=== 新结构: 轴 → 槽位数 / 词数 ===")
    tot = 0
    for ax in axes.AXIS_ORDER:
        rows = sorted(buckets.get(ax, []), key=lambda r: r[0])
        n = sum(_sub_words(s[1]) for s in rows)
        tot += n
        print(f"  {axes.AXIS_NAME_ZH[ax]:<8} ({ax:<11}) {len(rows):>2} 槽位 / {n:>4} 词")
        for _o, sub, old_cat in rows:
            print(f"      ← {old_cat}/{sub.get('name')}")
    print(f"  合计 {tot} 词 (原 {sum(_sub_words(s) for c in ref.get('categories', []) for s in c.get('subcategories', []))})")

    if not apply:
        print(f"\n新路径表 {len(v2)} 项")
        print("(dry-run; 加 --apply 落盘)")
        return 0

    # ---------- 1) 写回 axes.py 的 SUB_TO_AXIS_V2 ----------
    ax_py = os.path.join(ROOT, "axes.py")
    src = open(ax_py, encoding="utf-8").read()
    lines = ["SUB_TO_AXIS_V2: dict[str, tuple[str, int]] = {"]
    for ax in axes.AXIS_ORDER:
        zh = axes.AXIS_NAME_ZH[ax]
        rows = sorted(buckets.get(ax, []), key=lambda r: r[0])
        if not rows:
            continue
        lines.append(f"    # ---- {zh} ({ax}) ----")
        for order, sub, _old in rows:
            sname = str(sub.get("name", ""))
            lines.append(f'    "{zh}/{sname}": ("{ax}", {order}),')
    lines.append("}")
    block = "\n".join(lines)
    import re
    if "SUB_TO_AXIS_V2" in src:
        src = re.sub(r"SUB_TO_AXIS_V2[^\n]*= \{.*?\n\}", block, src, flags=re.S)
    else:
        src = src.replace("def axis_of(", block + "\n\n\ndef axis_of(", 1)
    open(ax_py, "w", encoding="utf-8", newline="\n").write(src)
    print("✅ axes.py: SUB_TO_AXIS_V2 已写入")

    # ---------- 2) 重排库结构 ----------
    for path in targets:
        raw = json.load(open(path, encoding="utf-8"))
        old_count = sum(_sub_words(s) for c in raw.get("categories", []) for s in c.get("subcategories", []))
        new_cats = []
        for ax in axes.AXIS_ORDER:
            rows = sorted(buckets.get(ax, []), key=lambda r: r[0])
            if not rows:
                continue
            zh = axes.AXIS_NAME_ZH[ax]
            subs = []
            for _o, sub, old_cat in rows:
                sub = json.loads(json.dumps(sub, ensure_ascii=False))
                # 标签补 facet (原大类名, 非结构字段)
                def _stamp(lst):
                    for t in lst:
                        t.setdefault("facet", old_cat)
                _stamp(sub.get("tags") or [])
                for g in sub.get("groups") or []:
                    _stamp(g.get("tags") or [])
                subs.append(sub)
            new_cats.append({
                "id": f"axis.{ax}", "name": zh,
                "icon": {"meta": "💎", "count": "👥", "character": "🧿", "appearance": "🎨",
                         "clothing": "👗", "prop": "🧰", "action": "🤸", "environment": "🏞",
                         "lighting": "💡", "camera": "🎬", "style": "🖌", "material": "✨"}.get(ax, ""),
                "color": "", "subcategories": subs,
            })
        raw["categories"] = new_cats
        raw.pop("schema_version", None)
        schema.migrate_library(raw)
        new_count = sum(_sub_words(s) for c in raw.get("categories", []) for s in c.get("subcategories", []))
        assert new_count == old_count, f"词数变化 {old_count} -> {new_count}"
        # facet 覆盖率
        stamped = sum(1 for c in raw["categories"] for s in c.get("subcategories", [])
                      for t in (s.get("tags") or []) if t.get("facet"))
        bak = f"{path}.bak-{datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(path, bak)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(raw, f, ensure_ascii=False, indent=1)
        print(f"✅ {os.path.basename(path)}: {len(new_cats)} 轴, 词数 {old_count}→{new_count} 不变, "
              f"facet 覆盖 {stamped} (备份 {os.path.basename(bak)})")

    # ---------- 3) 迁移 conflicts.json 的 cat/sub 路径引用 ----------
    cpath = os.path.join(ROOT, "data", "default", "taglib", "conflicts.json")
    if os.path.isfile(cpath):
        raw = json.load(open(cpath, encoding="utf-8"))
        rules = raw.get("rules") if isinstance(raw, dict) else raw
        # 旧大类 → 它覆盖的轴集合。8/9 个旧大类恰好等于 1 条轴, 可直接映射;
        # 唯一例外「人物主体」跨 5 条轴 —— 若真有规则引用它, 只能人工决定, 这里会报出来。
        cat_axes: dict[str, set] = {}
        for c in ref.get("categories", []):
            cn = str(c.get("name", ""))
            for sub in c.get("subcategories", []) or []:
                cat_axes.setdefault(cn, set()).add(axes.axis_of(cn, str(sub.get("name", "")))[0])
        ambiguous: list[str] = []
        changed = 0
        for r in rules or []:
            for side in [r.get("left")] + list(r.get("right") or []):
                if not isinstance(side, dict):
                    continue
                k, v = side.get("kind"), str(side.get("value") or "")
                if k == "cat":
                    if v in axes.AXIS_ZH_TO_ID:
                        continue                      # 已经是轴名
                    axs = cat_axes.get(v) or set()
                    if len(axs) == 1:
                        side["value"] = axes.AXIS_NAME_ZH[next(iter(axs))]
                        changed += 1
                    elif axs:
                        ambiguous.append(f"cat:{v} 跨 {len(axs)} 条轴")
                elif k == "sub" and "/" in v:
                    old_cat, old_sub = v.split("/", 1)
                    ax, _ = axes.axis_of(old_cat, old_sub)
                    if ax in axes.AXIS_NAME_ZH:
                        side["value"] = f"{axes.AXIS_NAME_ZH[ax]}/{old_sub}"
                        changed += 1
        if ambiguous:
            print("⚠ 以下引用跨多条轴, 未自动迁移 (需人工决定): " + "; ".join(ambiguous))
        if changed:
            shutil.copy2(cpath, f"{cpath}.bak-{datetime.now():%Y%m%d%H%M%S}")
            with open(cpath, "w", encoding="utf-8", newline="\n") as f:
                json.dump(raw, f, ensure_ascii=False, indent=1)
        print(f"✅ conflicts.json: 路径引用迁移 {changed} 处")

    # ---------- 4) 改写 slotpolicy.py 的槽位键 (旧"大类/子类" -> 新"轴名/槽位名") ----------
    sp = os.path.join(ROOT, "slotpolicy.py")
    spsrc = open(sp, encoding="utf-8").read()
    renamed = 0
    for old_key, (_ax, _order) in [(k, v) for k, v in v2.items()]:
        pass
    # 旧键 → 新键: 用迁移前的 (大类, 槽位) 关系推导
    key_map = {}
    for cat in ref.get("categories", []):
        cn = str(cat.get("name", ""))
        for sub in cat.get("subcategories", []) or []:
            sn = str(sub.get("name", ""))
            ax, _ = axes.axis_of(cn, sn)
            key_map[f"{cn}/{sn}"] = f"{axes.AXIS_NAME_ZH.get(ax, ax)}/{sn}"
    for old_key, new_key in key_map.items():
        if old_key == new_key:
            continue
        if f'"{old_key}"' in spsrc:
            spsrc = spsrc.replace(f'"{old_key}"', f'"{new_key}"')
            renamed += 1
    open(sp, "w", encoding="utf-8", newline="\n").write(spsrc)
    print(f"✅ slotpolicy.py: 槽位键改写 {renamed} 处")

    # ---------- 5) 重建 .md 镜像 ----------
    library.invalidate_cache()
    library.sync_to_folder_snapshot()
    print("✅ .md 镜像已按 轴/槽位/ 结构重建")
    return 0


if __name__ == "__main__":
    sys.exit(main())
