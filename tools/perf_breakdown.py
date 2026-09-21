"""性能拆解: 把 TagLibraryNode.build() 的每一段分别计时。

    python tools/perf_breakdown.py

只读测量 + 会触发一次热同步 (与正常读库同路径)。跑完用 `git checkout -- data/` 还原。

⚠ 这是**进程内**直调, 不走 HTTP —— 就是为了避开"端点延迟"这种间接指标。
   用户报的是"一个提示词 6-7 秒", 对应日志里的 `Prompt executed in X seconds`,
   这里把 build() 内部的每一层拆开, 看时间到底花在哪一层。
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine          # noqa: E402
import library         # noqa: E402
import nodes           # noqa: E402
import runtime_snapshot as rs   # noqa: E402


def ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def bench(label: str, fn, rounds: int = 3) -> None:
    times = []
    val = None
    for _ in range(rounds):
        t0 = time.perf_counter()
        val = fn()
        times.append(ms(t0))
    print(f"  {label:<44} " + "  ".join(f"{t:8.1f}" for t in times) + "   ms")
    return val


def main() -> int:
    print("\n== TagLibrary build 路径逐层计时 (单位 ms, 各跑 3 次) ==\n")

    print("[库加载]")
    library.invalidate_cache()
    lib = bench("get_merged()  冷 (含热同步首次)", library.get_merged, 1)
    bench("get_merged()  热", library.get_merged, 3)

    print("\n[快照编译]")
    rs.invalidate_snapshot()
    bench("get_snapshot() 冷", lambda: rs.get_snapshot(library.get_merged()), 1)
    bench("get_snapshot() 热", lambda: rs.get_snapshot(library.get_merged()), 3)

    print("\n[抽取引擎]")
    state = {"tags": [{"en": "katana", "pinned": True, "enabled": True}],
             "fill_master": True, "fill_master_min": 2, "fill_master_max": 3,
             "nl_tail": True}
    cfg = engine.resolve_config(state, lib.get("settings") or {})
    bench("run_auto() 全抽一次",
          lambda: engine.run_auto(rs.get_snapshot(library.get_merged()), state, 12345,
                                  nsfw_on=False, avoid_conflicts=True,
                                  search_text="", cat_weights=None, config=cfg), 5)

    print("\n[完整节点 build]   <-- 这才是提示词实际走的那条路")
    n = nodes.TagLibraryNode()
    kwargs = {"selection_state": '{"tags":[],"fill_master":true,'
                                 '"fill_master_min":2,"fill_master_max":3,"nl_tail":true}',
              "mode": "auto", "seed": 42}
    bench("TagLibraryNode.build()", lambda: n.build(**kwargs), 5)

    print("\n[结论提示]")
    print("  若 get_merged() 冷 ≈ 热, 说明缓存每次都失效 (有东西在改那 3 个 json 的 mtime)")
    print("  1.12.0 起没有 .md 镜像层, 读路径不再写盘; 这里只剩 build() 与 get_merged() 两组基准")
    return 0


if __name__ == "__main__":
    sys.exit(main())
