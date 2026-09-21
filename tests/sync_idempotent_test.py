"""文件夹镜像幂等性门禁 —— 防止"越同步越变、永不收敛"回归。

    python tests/sync_idempotent_test.py

背景 (2026-09-19 性能排查): 一度怀疑 `.md` 镜像不幂等导致热同步永不收敛。
实测**它其实是幂等的** —— 但正因为这个性质很关键（不幂等就意味着每次热同步
都全量重写 67 个文件、并且指纹永远在变），值得固化成门禁。

判定标准:
  1. 连续 3 轮 `sync_to_folder_snapshot()` 之后, 全部 .md 的内容 hash 不再变化
  2. 每轮之后 `folder_sync_plan()` 都返回 `action=none`
  3. 解析 → 渲染 → 解析 的往返不丢字段 (nsfw / gender / weight)

⚠ 会真实写入 data/default/taglib/; 由 tools/run_gates.py 统一快照还原。
"""

from __future__ import annotations

import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library    # noqa: E402
import tagfiles   # noqa: E402

FAILS: list[str] = []


def chk(cond: bool, label: str, detail: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def md_hash() -> tuple[int, str]:
    h = hashlib.sha256()
    n = 0
    for root, _dirs, files in os.walk(tagfiles.LIBRARY_DIR):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, tagfiles.LIBRARY_DIR).encode("utf-8", "ignore"))
            with open(p, "rb") as fh:
                h.update(fh.read())
            n += 1
    return n, h.hexdigest()[:16]


def plan_action() -> str:
    key = (library._mtime(library.DEFAULT_PATH), library._mtime(library.USER_PATH))
    res = tagfiles.folder_sync_plan(tagfiles.LIBRARY_DIR, key)
    return res[0] if isinstance(res, tuple) and res else str(res)


def main() -> int:
    n, h0 = md_hash()
    print(f"起点: {n} 个 .md, hash={h0}, action={plan_action()}")
    chk(n > 0, "镜像里确实有 .md 文件", f"{n} 个")

    # 第一轮先把可能存在的差异同步掉 (例如上一次运行的残留)
    library.sync_to_folder_snapshot()
    n1, h1 = md_hash()
    a1 = plan_action()
    print(f"第 1 轮后: hash={h1}, action={a1}")
    chk(a1 == "none", "第 1 轮后即收敛 (action=none)", f"实际 {a1}")

    for i in (2, 3):
        library.sync_to_folder_snapshot()
        n2, h2 = md_hash()
        a2 = plan_action()
        print(f"第 {i} 轮后: hash={h2}, action={a2}")
        chk(h2 == h1, f"第 {i} 轮 .md 内容未变 (幂等)", f"{h1} -> {h2}")
        chk(a2 == "none", f"第 {i} 轮仍是 action=none", f"实际 {a2}")

    # 解析 → 渲染 → 解析 往返不丢字段
    probe = ("# 测试" + chr(10) + "## 测试槽" + chr(10) +
             "alpha(甲){1.2}, beta(乙)[nsfw], gamma(丙)[♀], delta(丁)[♂], epsilon(戊)")
    d1 = tagfiles.parse_tagfile(probe)
    ts1 = []
    for c in d1.get("categories", []) or []:
        for s in c.get("subcategories", []) or []:
            ts1 += s.get("tags", []) or []
    got = {t.get("en"): (bool(t.get("nsfw")), t.get("gender"), float(t.get("weight") or 1.0))
           for t in ts1}
    print(f"  解析样例: {got}")
    chk(got.get("beta", (False,))[0] is True, "往返: [nsfw] 被解析为 nsfw=True")
    chk(got.get("gamma", (0, None))[1] == "female", "往返: [♀] 被解析为 gender=female")
    chk(got.get("delta", (0, None))[1] == "male", "往返: [♂] 被解析为 gender=male")
    chk(abs(got.get("alpha", (0, None, 1.0))[2] - 1.2) < 1e-6, "往返: {权重} 被解析回来")

    print()
    if FAILS:
        print(f"sync_idempotent_test: {len(FAILS)} 项失败")
        for f in FAILS:
            print("   -", f)
        return 1
    print("sync_idempotent_test: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
